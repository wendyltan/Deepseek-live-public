"""R576 user-confirmed R503 0.6B Mandarin Wi-Fi answer/progress voice policy.

Only the authenticated physical Wi-Fi voice owner uses this local, owner-only
opt-in. Neither model session, microphone, USB owner nor macOS app is modified.
The R505 long-only policy remains the exact fallback when this is off.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from app.r505_long_voice_trial import (
    ROOT, BASELINE, CANDIDATE, candidate_ready, select as original_select,
)

CONFIG=ROOT/"voice-policy-r576.json"
MODES={"r576-r503-all-mandarin"}

def enabled(*, config:Path=CONFIG) -> bool:
    try:
        p=Path(config)
        if p.is_symlink() or p.parent.is_symlink() or not p.is_file():
            return False
        folder=p.parent.stat()
        f=p.stat()
        if (folder.st_uid!=os.getuid() or folder.st_mode & 0o077 or
            f.st_uid!=os.getuid() or f.st_mode & 0o077 or
            f.st_size<10 or f.st_size>1024):return False
        item=json.loads(p.read_text())
        return (type(item) is dict and item.get("schema")==1 and
                item.get("mode") in MODES and item.get("enabled") is True and
                set(item)=={"schema","mode","enabled"})
    except (ValueError,OSError,TypeError,AttributeError):return False

def is_mandarin_speech(spoken:str)->bool:
    if not isinstance(spoken,str) or not 1<=len(spoken)<=8000:
        return False
    han=sum('\u4e00'<=c<='\u9fff' for c in spoken)
    # R503 is Chinese-reference clone: avoid silent degraded multilingual/code.
    return han>=2 and han*3>=len(spoken)

def choose(*, origin:str, spoken:str, source_chars:int=0,
           summarized_long:bool=False, phone_report:bool=False,
           config:Path=CONFIG, opener=None) -> str:
    if enabled(config=config):
        # The voice owner supplies only verified local sources or a bound
        # official DSH result; never select on an arbitrary web/tool string.
        authorized=origin in ('official_dsh_verified',
                              'verified_mac_local_datetime',
                              'verified_open_meteo_weather')
        if authorized and is_mandarin_speech(spoken):
            return CANDIDATE if candidate_ready(opener=opener) else BASELINE
        return BASELINE
    # Opt-in absent: exact R505 long-only behavior, including D10 phone
    # messages, unlike the new user-requested R576 policy.
    return BASELINE if phone_report else original_select(
        origin,spoken,source_chars=source_chars,
        summarized_long=summarized_long,opener=opener)

def choose_progress(text:str, *, config:Path=CONFIG,opener=None)->str:
    # Only called after a native authenticated phone-tool progress stage.
    if not (enabled(config=config) and is_mandarin_speech(text)):
        return BASELINE
    return CANDIDATE if candidate_ready(opener=opener) else BASELINE

def profile_name(endpoint:str, *, config:Path=CONFIG)->str:
    # R580 compatibility: the physical WSS gateway, real reply-comparison
    # ledger and board allowlist already identify this exact R503 voice as
    # "long-trial". Keep that trusted *VOICE ID* for both short and long;
    # r576_r503_voice_selected separately records new routing scope.
    if endpoint==CANDIDATE:
        return 'dafeiyu-r503-qwen06-long-trial'
    return 'dafeiyu-qwen3-d10'
