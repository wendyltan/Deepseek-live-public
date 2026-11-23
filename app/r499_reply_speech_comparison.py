"""R499: one latest private, verified original-answer vs TTS-input receipt.

This is display-only after synthesis has completed. It never proves that
the ESP32 has played every byte of audio and never starts a model call.
"""
from __future__ import annotations

import json
import hashlib
import re
import os
import tempfile
import time
from pathlib import Path

from app.native_companion_projection import NativeCompanionProjector, DEFAULT

FILENAME = "reply-speech-comparison-v1.json"
HISTORY_FILENAME = "reply-speech-history-v1.json"
MAX_HISTORY_BYTES = 800_000
HISTORY_RECORD_LIMIT = 120
MAX_ORIGINAL = 12000
MAX_SPOKEN = 8000
ORIGINS = {
    "official_dsh_verified": "model",
    "verified_mac_local_datetime": "clock",
    "verified_open_meteo_weather": "weather",
    "local_weather_source_unavailable": "weather_unavailable",
}

def _append_verified_spoken_history(directory:Path, receipt:dict)->bool:
    """Atomically preserve finished TTS inputs for current-session Mac history.

    The caller already proved the official answer/session/TTS text. No DSH
    call, original conversation mutation or playback-success inference.
    """
    target=directory/HISTORY_FILENAME
    rows=[]
    try:
        if target.is_symlink():return False
        if target.exists():
            info=target.stat()
            if (not target.is_file() or info.st_uid!=os.getuid() or
                info.st_mode&0o077 or info.st_size>MAX_HISTORY_BYTES or
                info.st_size<20):return False
            old=json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(old,dict) or old.get("schema")!=1:return False
            if old.get("session_id")==receipt["session_id"]:
                rows=old.get("records")
                if not isinstance(rows,list) or len(rows)>HISTORY_RECORD_LIMIT:return False
                if any(not isinstance(item,dict) or
                       not isinstance(item.get("original_text"),str) or
                       not isinstance(item.get("spoken_text"),str) or
                       len(item["original_text"])>MAX_ORIGINAL or
                       len(item["spoken_text"])>MAX_SPOKEN or
                       not isinstance(item.get("generated_at_unix"),(int,float))
                       for item in rows):return False
            # New official session means a new bounded private display log.
            else:rows=[]
        rows.append({"original_text":receipt["original_text"],
                     "spoken_text":receipt["spoken_text"],
                     **({"final_spoken_text":receipt["final_spoken_text"]}
                        if receipt.get("final_spoken_text") else {}),
                     "speech_id":receipt.get("speech_id"),
                     "generated_at_unix":receipt["generated_at_unix"]})
        rows=rows[-HISTORY_RECORD_LIMIT:]
        while rows:
            raw=json.dumps({"schema":1,"session_id":receipt["session_id"],
                            "records":rows},ensure_ascii=False,
                           separators=(",",":")).encode("utf-8")
            if len(raw)<=MAX_HISTORY_BYTES:break
            rows.pop(0)
        if not rows:return False
        temp=None
        try:
            with tempfile.NamedTemporaryFile(dir=directory,prefix=".spoken-history-",
                                             delete=False) as f:
                temp=Path(f.name);os.fchmod(f.fileno(),0o600)
                f.write(raw);f.flush();os.fsync(f.fileno())
            if target.is_symlink():return False
            os.replace(temp,target)
            os.chmod(target,0o600)
        finally:
            if temp is not None:temp.unlink(missing_ok=True)
        return True
    except (OSError,TypeError,ValueError,UnicodeError):return False


def save_verified_comparison(native, original, spoken, origin, *,
                             segments=(), voice_profile_id="dafeiyu-qwen3-d10",
                             final_spoken_text:str|None=None,
                             directory: Path = DEFAULT, now=time.time,
                             tts_generated:bool=True, expected_speech_id=None) -> bool:
    """Publish verified TTS script before synthesis, then replace with full receipt.

    The caller must be the bound official NativeDshCompanionSession.
    A temporary file is 0600, replaced atomically in its 0700 directory.
    Any I/O error fails closed without affecting the generated PCM.
    """
    from app.native_dsh_companion_session import NativeDshCompanionSession
    if not isinstance(native, NativeDshCompanionSession) or not native.bound:
        return False
    projector = native.projector
    if not isinstance(projector, NativeCompanionProjector):
        return False
    state = projector.state
    if not isinstance(state, dict) or state.get("session_verified") is not True:
        return False
    if state.get("answer_verified") is not True or state.get("answer_origin") != ORIGINS.get(origin):
        return False
    sid = projector.session_id
    if not isinstance(sid, str) or not sid or state.get("session_id") != sid:
        return False
    if expected_speech_id is not None and state.get("answer_speech_id") != expected_speech_id:
        return False
    if type(tts_generated) is not bool:
        return False
    if not (isinstance(original, str) and original.strip() and
            isinstance(spoken, str) and spoken.strip() and
            len(original) <= MAX_ORIGINAL and len(spoken) <= MAX_SPOKEN):
        return False
    # The official projector holds a *bounded* version of the authoritative
    # answer. Refuse if the TTS producer offers another session's answer.
    bounded = state.get("answer_text")
    if not isinstance(bounded, str) or bounded != original[:len(bounded)] or not bounded:
        return False
    if not isinstance(segments, (tuple, list)) or len(segments)>64:
        return False
    if segments:
        if any(not isinstance(row, dict)
               or not isinstance(row.get("text"), str)
               or not isinstance(row.get("audio_ms"), int)
               or not (100 <= row["audio_ms"] <= 180_000)
               for row in segments):
            return False
        if "".join(row["text"] for row in segments) != spoken:
            return False
    if voice_profile_id not in ("dafeiyu-qwen3-d10",
                                "dafeiyu-r503-qwen06-long-trial"):
        return False
    # The full PCM receipt MUST still include already-broadcast interim
    # audio, whereas the final bubble should show only the verified result
    # that will be synthesized afterward. No hidden/unplayed words are
    # permitted and the final text must be a strict audio suffix.
    if final_spoken_text is not None and (
        not isinstance(final_spoken_text,str) or
        not final_spoken_text.strip() or
        len(final_spoken_text)>MAX_SPOKEN or
        not spoken.endswith(final_spoken_text)):
        return False
    payload = {
        "schema": 1, "session_id": sid,
        "speech_id": state.get("answer_speech_id"),
        "voice_profile_id": voice_profile_id,
        "generated_at_unix": float(now()),
        "origin": origin,
        "original_text": original,
        "spoken_text": spoken,
        **({"final_spoken_text":final_spoken_text}
           if final_spoken_text is not None else {}),
        "original_chars": len(original),
        "spoken_chars": len(spoken),
        "segments": [{"text": row["text"], "audio_ms": row["audio_ms"]}
                     for row in segments],
        "tts_generated": tts_generated,
        "device_playback_verified": False,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > 48_000:
        return False
    path = Path(directory)
    try:
        if path.is_symlink():
            return False
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            return False
        target = path / FILENAME
        if target.is_symlink():
            return False
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=path, prefix=".comparison-",
                                             delete=False) as f:
                name = Path(f.name)
                os.fchmod(f.fileno(), 0o600)
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, target)
            os.chmod(target, 0o600)
        finally:
            if name is not None:
                name.unlink(missing_ok=True)
        # Pending plans are explicitly not durable 'generated speech'. The
        # official answer remains independently available if disk I/O fails.
        return (_append_verified_spoken_history(path,payload)
                if tts_generated else True)
    except (OSError, ValueError, TypeError):
        return False


def _trusted_receipt(native, directory: Path, now):
    """Read same verified official session with restrictive local permissions."""
    from app.native_dsh_companion_session import NativeDshCompanionSession
    if not isinstance(native, NativeDshCompanionSession) or not native.bound:
        return None
    proj=native.projector
    if not isinstance(proj, NativeCompanionProjector):
        return None
    state=proj.state
    if not state.get("session_verified") or not proj.session_id:
        return None
    parent=Path(directory)
    target=parent/FILENAME
    try:
        if parent.is_symlink() or target.is_symlink():
            return None
        d=parent.stat()
        f=target.stat()
        if (d.st_uid!=os.getuid() or d.st_mode&0o077 or
            f.st_uid!=os.getuid() or f.st_mode&0o077 or
            f.st_size>48_000 or f.st_size<20):
            return None
        row=json.loads(target.read_text())
        age=float(now())-row.get("generated_at_unix",0)
        if (row.get("schema")!=1 or
            row.get("session_id")!=proj.session_id or
            state.get("session_id")!=proj.session_id or
            row.get("speech_id")!=state.get("answer_speech_id") or
            not isinstance(row.get("spoken_text"),str) or
            not row.get("tts_generated") or
            not 0<=age<=1200):
            return None
        return row
    except (OSError,ValueError,TypeError,AttributeError):
        return None


def _update_receipt(directory: Path, row: dict) -> bool:
    target=Path(directory)/FILENAME
    raw=json.dumps(row,ensure_ascii=False,separators=(",",":")).encode()
    if len(raw)>48_000:
        return False
    name=None
    try:
        with tempfile.NamedTemporaryFile(dir=directory,prefix=".playback-",
                                         delete=False) as f:
            name=Path(f.name)
            os.fchmod(f.fileno(),0o600)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if target.is_symlink():
            return False
        os.replace(name,target)
        return True
    except OSError:
        return False
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def _binding_digest(turn_id: str, playback_id: str) -> str:
    return hashlib.sha256((turn_id+"|"+playback_id).encode()).hexdigest()


def bind_device_playback(native, turn_id: str, playback_id: str,
                         frames: int, answer_origin: str,
                         spoken_chars: int, *,
                         directory: Path=DEFAULT, now=time.time) -> bool:
    """Bind latest actual TTS script to one verified WSS playback offer."""
    if (type(frames) is not int or not 0<frames<=3000 or
        type(spoken_chars) is not int or not 0<spoken_chars<=MAX_SPOKEN or
        not isinstance(turn_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}",turn_id) or
        not isinstance(playback_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}",playback_id)):
        return False
    row=_trusted_receipt(native,directory,now)
    if (row is None or row.get("tts_generated") is not True
            or row.get("origin")!=answer_origin or row.get("spoken_chars")!=spoken_chars):
        return False
    row["playback_binding"]={"digest":_binding_digest(turn_id,playback_id),
                             "frames":frames}
    row["device_playback_verified"]=False
    return _update_receipt(Path(directory),row)


def confirm_device_playback(native, turn_id: str, playback_id: str,
                            frames: int, *, directory: Path=DEFAULT,
                            now=time.time) -> bool:
    """Mark after full WSS frame ACK, not user-perceived speaker audibility."""
    row=_trusted_receipt(native,directory,now)
    if row is None or row.get("device_playback_verified"):
        return False
    binding=row.get("playback_binding")
    if (not isinstance(binding,dict) or
        not isinstance(turn_id,str) or not isinstance(playback_id,str) or
        not isinstance(binding.get("digest"),str) or
        binding["digest"]!=_binding_digest(turn_id,playback_id) or
        type(frames) is not int or frames!=binding.get("frames")):
        return False
    row["device_playback_verified"]=True
    row["device_playback_reported_at_unix"]=float(now())
    row.pop("playback_binding",None)
    return _update_receipt(Path(directory),row)
