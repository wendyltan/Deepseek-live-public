"""Private, durable, numeric-only lifecycle receipts for verified ESP LAN voice.

No microphone audio, user text, DSH output, identities, auth headers, tokens,
or model secrets. Never logs user speech or reply content; production opt-in.
"""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import re
import stat
import threading
import time

_ALLOWED = frozenset({
    "wss_hello_verified","recording_started","processing_ping_sent","capture_submitted",
    "backend_started","mic_quality","asr_done","dsh_started","dsh_answer_ready",
    "tts_plan_ready","tts_phrase_started","tts_phrase_done",
    "pcm_ready","audio_gain_metrics","audio_offer_sent","window_sent",
    "device_playback_started","device_playback_finished",
    "backend_failed","gateway_protocol_error","wss_closed",
    "r305_voice_memory_status","tts_pcm_quality","audio_playback_health",
    "r458_local_clock_verified","r461_no_speech_returned",
    "r526_buffered_loudness_smoothed","r526_buffered_phrase_reduction",
    "r528_parallel_facts_compacted","r529_oral_script_compiled",
    "r532_r503_tempo","r536_later_phrase_balance","r537_fade_guard",
    "r537_semantic_tts_boundary","r537_semantic_pause",
    "r538_pinky_readonly_query","r539_d10_spike_guard",
    "r518_verified_phone_progress","r518_phone_progress_skipped",
    "r518_phone_progress_failed","r541_asr_context_correction",
    "r631_phone_audio_tail_guard",
    "r687_pinky_full_phrase_loudness",
})
_NUMERIC = frozenset({
    "input_pcm_bytes","input_frames","duration_ms","close_code","pending_backend","asr_ms","dsh_ms",
    "asr_decode_ms","asr_whisper_ms","reply_chars","phrase_index","phrase_total","phrase_chars","tts_ms",
    "pcm_bytes","audio_frames","frames_sent","frames_played",
    "tts_peak","tts_clipped","lifted_peak","gain_blocks","tts_first_pcm_ms",
    "rms_dbfs_tenths","peak_permille","clipped_ppm","gain_applied","gain_hundredths",
    "pcm_duration_ms","source_pcm_duration_ms","pcm_max_quiet_ms",
    "source_max_quiet_ms","pcm_quiet_percent","pcm_active_rms","pcm_peak",
    "pcm_trimmed_ms","pcm_trimmed_runs","phrase_level_permille",
    "source_pcm_active_rms","source_pcm_peak","phrase_gain_ramp_ms","turn_boost_permille",
    "max_ack_gap_ms","slow_ack_gaps","ack_count","playback_elapsed_ms",
    "playback_completed","max_frames_inflight","clock_source","no_speech",
    "frames_expected","frames_acked","frames_submitted",
    "first_ack_delay_ms", "delay_ms",
    "soft_peak_limited_ppm","global_peak_restricted",
    "attenuated_200ms_windows","old_phrases","new_phrases","items",
    "original_chars","spoken_chars",
    "applied","original_duration_ms","slowed_duration_ms",
    "topic_gap_chars","phrase1_chars","phrase2_chars","inserted_ms",
    "early_rms","late_rms","peak_in","peak_out",
    "min_gain_permille","max_gain_permille",
    "hot_100ms_windows","big_steps_before","big_steps_after",
    "max_step_before","max_step_after","progress_code",
    "correction_count","corrected_observed_app_term",
    "padded_ms","original_tail_ms",
    "enabled","prior_progress_frames",})
_CLASS = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,60}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,65}$")


class SafeLanReceipt:
    """Records only allowlisted stage names and bounded metadata; no PII."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        # A complete 60-second 3-phrase reply can emit >80 numeric lifecycle
        # entries; preserve several turns so first-phrase latency/level
        # evidence does not disappear behind later playback ACKs.
        self._events = deque(maxlen=256)
        if self.path.is_symlink():
            raise RuntimeError("receipt_symlink_not_allowed")
        if self.path.exists():
            st = self.path.stat()
            if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                raise RuntimeError("receipt_private_mode_required")
            try:
                old = json.loads(self.path.read_text())
                for item in old.get("events", []):
                    if (isinstance(item, dict) and item.get("stage") in _ALLOWED
                            and isinstance(item.get("at_unix"), (int, float))):
                        self._events.append(item)
            except (ValueError, TypeError, OSError):
                pass

    def record(self, stage: str, **attrs) -> None:
        if stage not in _ALLOWED:
            return
        event = {"stage": stage, "at_unix": round(time.time(), 3)}
        for key, value in attrs.items():
            if key in _NUMERIC and type(value) is int and 0 <= value <= 10**9:
                event[key] = value
            elif key == "error_kind" and isinstance(value, str) and _CLASS.fullmatch(value):
                event[key] = value
            elif key == "error_code" and isinstance(value, str) and _CODE.fullmatch(value):
                event[key] = value
            elif stage == "r305_voice_memory_status" and key == "status" and value in (
                "saved","already_saved","review_pending","not_supported",
                "disabled","failed"):
                # Only bounded outcome enums: no spoken facts/DSH reply.
                event["status"] = value
            elif stage == "r305_voice_memory_status" and key == "category" and value in (
                "name","likes","dislikes",""):
                event["category"] = value
        with self._lock:
            self._events.append(event)
            payload = {"schema": 1, "latest_stage": stage,
                       "events": list(self._events)}
            temp = self.path.with_name(self.path.name + ".tmp-" + str(os.getpid()))
            try:
                fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as out:
                    json.dump(payload, out, ensure_ascii=True, separators=(",", ":"))
                    out.write("\n")
                os.chmod(temp, 0o600)
                temp.replace(self.path)
            except (OSError, ValueError):
                # Diagnostics must never interfere with an authoritative DSH turn.
                pass
