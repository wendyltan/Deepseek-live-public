"""One-shot GUI search toggle: owner-only bounded command for SAME DSH session.

No network credentials in file; no autonomous model invocation or transcription.
"""
from __future__ import annotations
import json
import os
import stat
import time
from pathlib import Path

CONTROL=Path.home()/"Library/Application Support/Deepseek-live/companion-native/search-request.json"

def apply_pending_search(native, *, target=CONTROL, clock=time.time, output=print):
    if not native.bound or native.projector.session_id is None:
        return False
    if target.is_symlink() or not target.exists():
        return False
    info=target.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>512 or (info.st_mode & 0o077):
        output("H29_SEARCH_REQUEST_REJECTED_UNSAFE_FILE")
        return False
    try:
        raw=json.loads(target.read_text(encoding="utf-8"))
        target.unlink()
    except (OSError,UnicodeError,ValueError):
        return False
    if (not isinstance(raw,dict) or raw.get("schema")!=1
        or raw.get("session_id")!=native.projector.session_id
        or type(raw.get("enabled")) is not bool
        or type(raw.get("at")) not in (int,float)
        or abs(clock()-raw["at"])>60):
        output("H29_SEARCH_REQUEST_REJECTED_SESSION_OR_EXPIRED")
        return False
    try:
        checked=native.adapter.switch_search(native.tab_id,raw["enabled"])
        if checked.get("supported") is not True or checked.get("enabled") is not raw["enabled"]:
            raise RuntimeError("dsh_search_toggle_not_verified")
        native.projector.state["search_supported"]=True
        native.projector.state["search_enabled"]=raw["enabled"]
        native.projector.record_step("idle","联网搜索已由官方DSH会话确认"+("启用" if raw["enabled"] else "关闭"))
        native.projector.write()
        output("H29_REAL_DSH_SEARCH_CONFIRMED="+str(raw["enabled"]))
        return True
    except Exception as exc:
        output("H29_DSH_SEARCH_CHANGE_FAILED="+type(exc).__name__)
        return False
