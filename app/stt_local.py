"""Local, request-scoped microphone transcription using the already installed whisper.cpp.

Input bytes never get sent to the DeepSeek API; they are decoded by local ffmpeg
into a temporary mono WAV for whisper-cli and removed even on failure.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import wave

from app.stt_simplify import to_simplified
from app.mandarin_asr_context import recover_known_terms

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "app/runtime/models"
TOOLS = Path(os.environ.get("DAFEIYU_TOOLS_ROOT", str(ROOT.parent.parent / "Tools")))


def _pick_path(env_key: str, *candidates: Path) -> Path:
    configured = os.environ.get(env_key, "").strip()
    if configured:
        return Path(configured).expanduser()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


WHISPER = _pick_path(
    "DAFEIYU_WHISPER_CLI",
    *( [Path(found)] if (found := shutil.which("whisper-cli")) else [] ),
    ROOT / "app/runtime/bin/whisper-cli",
    TOOLS / "whisper.cpp/build/bin/whisper-cli",
)
MODEL_DIR = (
    Path(os.environ["DAFEIYU_WHISPER_MODELS"]).expanduser()
    if os.environ.get("DAFEIYU_WHISPER_MODELS", "").strip()
    else next(
        (d for d in (MODELS, TOOLS / "whisper.cpp/models") if (d / "ggml-small.bin").is_file()),
        MODELS,
    )
)
MODEL = MODEL_DIR / "ggml-small.bin"
# R323: conservative, reversible model selection. A candidate is never enabled
# just because a file was downloaded; the launch environment must opt in.
ASR_MODELS = {
    "small": MODEL,
    "medium": MODEL.with_name("ggml-medium.bin"),
    "turbo-q5": MODEL.with_name("ggml-large-v3-turbo-q5_0.bin"),
}

def selected_asr_model() -> tuple[str, Path]:
    name = os.environ.get("DAFEIYU_ASR_MODEL", "small").strip().lower()
    if name not in ASR_MODELS:
        raise TranscriptionError("语音模型配置无效，未执行识别")
    model = ASR_MODELS[name]
    if not model.is_file() or model.stat().st_size < 100_000_000:
        raise TranscriptionError("所选语音模型未就绪，未执行识别")
    return name, model
VAD_MODEL = _pick_path(
    "DAFEIYU_WHISPER_VAD_MODEL",
    MODELS / "silero-v6.2.0-ggml.bin",
    MODELS / "ggml-silero-v6.2.0.bin",
    MODEL_DIR / "silero-v6.2.0-ggml.bin",
    MODEL_DIR / "for-tests-silero-v6.2.0-ggml.bin",
)
FFMPEG = Path(os.environ.get("DAFEIYU_FFMPEG", shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"))
ALLOWED_TYPES = {"audio/webm", "audio/mp4", "audio/ogg", "audio/wav", "audio/x-wav"}
MAX_AUDIO_BYTES = 4_000_000
MAX_SECONDS = 20.0
MIN_SECONDS = 0.35


class TranscriptionError(ValueError):
    pass


class NoSpeechDetected(TranscriptionError):
    """Successful STT but zero valid speech, distinct from engine/USB failure."""


def _extract_whisper_text(output_json: Path) -> str:
    data = json.loads(output_json.read_text(encoding="utf-8"))
    text = "".join(
        segment.get("text", "") for segment in data.get("transcription", [])
        if isinstance(segment, dict)
    ).strip()
    for mark in ("[BLANK_AUDIO]", "(无语音)", "[无语音]"):
        if mark in text:
            text = text.replace(mark, "")
    return " ".join(text.split()).strip()


def transcribe_bytes(raw: bytes, content_type: str, runtime_root: Path, *, require_vad: bool = False) -> dict:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in ALLOWED_TYPES:
        raise TranscriptionError("录音格式不支持，请使用浏览器提供的音频录制")
    if not raw or len(raw) > MAX_AUDIO_BYTES:
        raise TranscriptionError("录音过大或为空，请缩短录音（每次不超过20秒）")
    if not WHISPER.is_file() or not FFMPEG.is_file():
        raise TranscriptionError("本地 Whisper 或 FFmpeg 尚未就绪")
    model_name, model_path = selected_asr_model()
    runtime_root.mkdir(parents=True, exist_ok=True)
    st = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="speech-", dir=runtime_root) as folder:
            directory = Path(folder)
            wav = directory / "microphone.wav"
            # Restrict both resource use and supported input formats.
            # Some browser-produced MP4/WebM chunks are only readable from a
            # seekable file. Keep this file ONLY inside auto-deleted temp storage.
            # Decode the in-memory pipe first, and retry from a private temp file
            # if necessary; never retain recordings in normal app/runtime/audio.
            args = [str(FFMPEG), "-hide_banner", "-loglevel", "error",
                    "-nostdin", "-i", "pipe:0", "-t", "21", "-vn", "-ac", "1",
                    "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(wav)]
            conversion = subprocess.run(args, input=raw,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=14, check=False)
            if conversion.returncode != 0 or not wav.is_file():
                suffix = {"audio/mp4":".mp4", "audio/webm":".webm",
                          "audio/ogg":".ogg", "audio/wav":".wav",
                          "audio/x-wav":".wav"}[media_type]
                uploaded = directory / ("browser-recording" + suffix)
                uploaded.write_bytes(raw)
                fallback = args[:]
                fallback[fallback.index("pipe:0")] = str(uploaded)
                conversion = subprocess.run(fallback, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    timeout=14, check=False)
            if conversion.returncode != 0 or not wav.is_file():
                # Do not misdiagnose a malformed audio container as a permission
                # error: permissions are already granted if bytes arrived here.
                raise TranscriptionError("收到录音但无法解码音频流。请播放本地录音预听，检查是否有声音；可尝试重新录制。")
            decode_ms = round((time.monotonic() - st) * 1000)
            with wave.open(str(wav), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
                if audio.getnchannels() != 1 or audio.getframerate() != 16000:
                    raise TranscriptionError("录音音频格式异常")
                if not MIN_SECONDS <= duration <= MAX_SECONDS:
                    raise TranscriptionError("请录制 0.5～20 秒的语音，再点击发送")
            output_path = directory / "transcript"
            base_command = [
                str(WHISPER), "-m", str(model_path), "-f", str(wav),
                "-l", "zh", "-sns",
                "-t", "4", "-oj", "-of", str(output_path),
                "-np", "-nt", "-nf",
            ]
            # Use Silero VAD on all turns when present (cuts ~7-13s silent
            # beam-5 stalls down to <1s). On wake, missing VAD fails closed;
            # on manual touch, fall back once to full-buffer decode if VAD
            # trims an ultra-quiet utterance.
            vad_ready = VAD_MODEL.is_file() and VAD_MODEL.stat().st_size >= 100_000
            if require_vad and not vad_ready:
                raise TranscriptionError("本地语音活动检测模型未就绪，唤醒录音未发送")
            use_vad = require_vad or (vad_ready and os.environ.get("DAFEIYU_ASR_VAD", "1") != "0")
            vad_flags = ["--vad", "-vm", str(VAD_MODEL), "-vt", "0.50" if require_vad else "0.42", "-vspd", "200" if not require_vad else "250", "-vp", "600"]
            whisper_start = time.monotonic()
            try:
                result = subprocess.run(
                    base_command + (vad_flags if use_vad else []),
                    capture_output=True, text=True, timeout=45, check=False,
                )
            except subprocess.TimeoutExpired:
                raise TranscriptionError("本地语音识别超时，请稍后重试") from None
            output_json = output_path.with_suffix(".json")
            if result.returncode != 0 or not output_json.is_file():
                raise TranscriptionError("本地语音识别失败，请稍后重试")
            data_json = _extract_whisper_text(output_json)
            text = data_json
            if not text and use_vad and not require_vad:
                try:
                    output_json.unlink(missing_ok=True)
                    result = subprocess.run(
                        base_command, capture_output=True, text=True, timeout=45, check=False,
                    )
                except subprocess.TimeoutExpired:
                    raise TranscriptionError("本地语音识别超时，请稍后重试") from None
                if result.returncode != 0 or not output_json.is_file():
                    raise TranscriptionError("本地语音识别失败，请稍后重试")
                text = _extract_whisper_text(output_json)
            whisper_ms = round((time.monotonic() - whisper_start) * 1000)
            # whisper.cpp -l zh can still emit Traditional or mixed characters.
            # Normalize after ASR; never modify the stored user's own message.
            try:
                text = to_simplified(text)
            except (ValueError, RuntimeError):
                raise TranscriptionError("简体中文转换失败，本轮语音未发送。请使用文字输入。") from None
            text,context_edits=recover_known_terms(text)
            if not text or text in ("。", "！", "？", "（音乐）", "[音乐]"):
                raise NoSpeechDetected("没有听清有效讲话，未发送给 DeepSeek。请重试")
            if len(text) > 1200:
                raise TranscriptionError("识别结果过长，请分几次讲话")
            return {
                "text": text,
                "wake_vad_checked": bool(require_vad),
                "audio_seconds": round(duration, 2),
                "stt_seconds": round(time.monotonic() - st, 2),
                "asr_decode_ms": decode_ms,
                "asr_whisper_ms": whisper_ms,
                "engine": f"local-whisper-{model_name}-mandarin-context",
                "asr_context_corrections": list(context_edits),
            }
    except subprocess.TimeoutExpired:
        raise TranscriptionError("录音格式转换超时，请缩短录音") from None
    except (OSError, ValueError) as err:
        if isinstance(err, TranscriptionError):
            raise
        raise TranscriptionError("本地录音处理出现错误，请稍后重试") from None
