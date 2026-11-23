"""R237: reject untrustworthy post-wake recordings before any DSH / TTS call.

No Mac microphone, raw PCM retention, second ASR or model requests. Manual
screen-tap dictation retains its existing 0.1-20s protocol bounds.
"""
from __future__ import annotations

MIN_WAKE_SECONDS = 2.0
# Historical hallucination patterns appeared only in ~1s auto-wake samples.
# These strings are not corrections and must never be treated as user speech.
KNOWN_PROMPT_ECHOES = ("设备名大肥鱼；可能讨论", "以下为普通话日常语音对话")

def wake_capture_block(seconds: float, origin: str) -> str | None:
    if origin != "wake":
        return None
    if not 0 <= seconds <= 20:
        return "wake_capture_invalid_duration"
    if seconds < MIN_WAKE_SECONDS:
        return "wake_capture_too_short_no_submit"
    return None

def wake_transcript_block(text: str, origin: str) -> str | None:
    if origin == "wake" and any(s in text for s in KNOWN_PROMPT_ECHOES):
        return "wake_asr_prompt_echo_no_submit"
    return None
