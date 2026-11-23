#!/usr/bin/env python3
"""Check local Whisper, Qwen3-TTS, Pinky and macOS tool dependencies.

Reports each module's installation status as JSON."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
DEFAULT_WHISPER=str(Path.home()/"Library/Application Support/Deepseek-live/dependencies/whisper.cpp")
DEFAULT_MODEL=str(Path.home()/"Library/Application Support/Deepseek-live/dependencies/qwen3-tts/model")
_LEGACY_REFERENCE=Path.home()/"Library/Application Support/Deepseek-live/voice-r503-production/r644/reference.wav"
_BUNDLED_REFERENCE=PROJECT/"release-assets/voice/r503-reference.wav"
DEFAULT_REFERENCE=str(_LEGACY_REFERENCE if _LEGACY_REFERENCE.is_file() else _BUNDLED_REFERENCE)


def file_ready(path: Path, min_size: int = 1) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= min_size
    except OSError:
        return False


def is_executable(path: Path) -> bool:
    return file_ready(path) and os.access(path, os.X_OK)


def reference_wav(path: Path) -> bool:
    if not file_ready(path):
        return False
    try:
        with wave.open(str(path), "rb") as w:
            return 0 < w.getnframes() and 8000 <= w.getframerate() <= 96000
    except (wave.Error, OSError, EOFError):
        return False


def asr() -> dict[str, bool]:
    home=Path(os.environ.get("DAFEIYU_WHISPER_HOME",DEFAULT_WHISPER)).expanduser()
    exe=Path(os.environ.get("DAFEIYU_WHISPER_CLI",str(home/"build/bin/whisper-cli")))
    models=Path(os.environ.get("DAFEIYU_WHISPER_MODELS",str(home/"models")))
    vad=Path(os.environ.get("DAFEIYU_WHISPER_VAD_MODEL",str(models/"ggml-silero-v6.2.0.bin")))
    ffmpeg=Path(os.environ.get("DAFEIYU_FFMPEG",shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"))
    return {
        "whisper_cli_executable":is_executable(exe),
        "multilingual_small_model":file_ready(models/"ggml-small.bin",100_000_000),
        "silero_vad_model":file_ready(vad,100_000),
        "ffmpeg_executable":is_executable(ffmpeg),
    }


def tts() -> dict[str, bool]:
    model=Path(os.environ.get("DAFEIYU_R503_MODEL_DIR",DEFAULT_MODEL)).expanduser()
    reference=Path(os.environ.get("DAFEIYU_R503_REFERENCE_AUDIO",DEFAULT_REFERENCE)).expanduser()
    py=Path(os.environ.get("DAFEIYU_TTS_PYTHON",sys.executable)).expanduser()
    result={
        "tts_python_executable":is_executable(py),
        "model_weights":file_ready(model/"model.safetensors",1_000_000),
        "speech_tokenizer_weights":file_ready(model/"speech_tokenizer/model.safetensors",1_000_000),
        "private_reference_wav":reference_wav(reference),
        "reference_transcript_set":bool(os.environ.get("DAFEIYU_R503_REFERENCE_TEXT","").strip()),
        "mlx_audio_installed":False,
    }
    if result["tts_python_executable"]:
        try:
            completed=subprocess.run(
                [str(py),"-c","from importlib.metadata import version; print(version('mlx-audio'))"],
                capture_output=True,text=True,timeout=12,check=False,
                env={**os.environ,"PYTHONNOUSERSITE":"1"},
            )
            result["mlx_audio_installed"]=completed.returncode==0
        except (OSError,subprocess.TimeoutExpired):
            pass
    return result


def phone() -> dict[str, bool]:
    cmd=os.environ.get("DAFEIYU_PINKYCTL") or shutil.which("pinkyctl") or "/opt/homebrew/bin/pinkyctl"
    app=Path(os.environ.get("DAFEIYU_PINKY_APP","/Applications/Pinky.app"))
    return {"pinkyctl_executable":is_executable(Path(cmd)),
            "pinky_app_installed":app.is_dir()}


def desktop() -> dict[str, bool]:
    helper=Path(os.environ.get("DAFEIYU_CUA_HELPER",
        str(Path.home()/".dsh/cua-native/dsh-cua-native")))
    return {"cua_native_helper_executable":is_executable(helper)}


def probe(stage: str) -> dict:
    checks={}
    for key,fun in (("asr",asr),("tts",tts),("pinky",phone),("cua",desktop)):
        if stage in ("all",key):checks[key]=fun()
    return {
      "schema":1,"mode":"read_only_dependency_preflight","stage":stage,
      "checks":checks,"ready":all(all(flags.values()) for flags in checks.values()),
      "did_start_services":False,"did_download_models":False,
      "did_operate_phone_or_desktop":False,
      "note":"File/package presence only; model inference, phone pairing and CUA grants require separate approval.",
    }


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage",choices=("all","asr","tts","pinky","cua"),default="all")
    p.add_argument("--strict",action="store_true",help="exit 2 when checks are incomplete")
    a=p.parse_args()
    data=probe(a.stage)
    print(json.dumps(data,ensure_ascii=False,indent=2))
    if a.strict and not data["ready"]:raise SystemExit(2)


if __name__=="__main__":main()
