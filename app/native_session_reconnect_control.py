"""Bounded user-clicked reconnect for the existing ESP32-owned DSH Session.

This is polled by the *existing* Mac voice worker while the physical device
waits for a finger. It never captures Mac audio or submits a model/tool turn.
"""
from __future__ import annotations
import json
import stat
import time
from pathlib import Path

CONTROL = Path.home() / "Library/Application Support/Deepseek-live/companion-native/reconnect-request.json"

def apply_pending_reconnect(native, verify, *, target=CONTROL, clock=time.time,
                            output=print, on_rebind=None):
    """Consume a fresh request only when no native DSH turn is in progress."""
    if native.projector.session_id is None:
        return False
    if native.projector.turn_id is not None or native.projector.task_id is not None:
        return False
    if target.is_symlink() or not target.exists():
        return False
    info=target.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 512 or (info.st_mode & 0o077):
        output("NATIVE_RECONNECT_REJECTED_UNSAFE_FILE")
        return False
    try:
        request=json.loads(target.read_text(encoding="utf-8"))
        target.unlink()
    except (OSError, UnicodeError, ValueError):
        return False
    if (not isinstance(request,dict) or request.get("schema") != 1
        or request.get("action") != "verify_session"
        or not isinstance(request.get("session_id"),str)
        or request["session_id"] not in ("",native.projector.session_id)
        or type(request.get("at")) not in (int,float)
        or abs(clock()-request["at"]) > 60):
        output("NATIVE_RECONNECT_REJECTED_STALE_OR_CROSS_SESSION")
        return False
    try:
        if not native.bound:
            raise RuntimeError("official_session_not_bound")
        verify(native)
        native.projector.state["session_verified"]=True
        native.projector.record_step("idle","手动连接：原有官方DSH会话仍有效")
        native.projector.write()
        output("NATIVE_RECONNECT_SAME_SESSION_VERIFIED")
        return True
    except (OSError,RuntimeError,ValueError):
        pass
    # User explicitly requested a new bind, and no active turn can be lost.
    # Reuse the same DSH tab, not a second agent. No model/tool submit occurs.
    try:
        native.bound=False
        native.attach_authoritative_session()
        if on_rebind is not None:
            on_rebind()
        output("NATIVE_RECONNECT_OFFICIAL_SESSION_REBOUND")
        return True
    except (OSError,RuntimeError,ValueError) as exc:
        native.projector.state["session_verified"]=False
        native.projector.record_step("error","手动连接失败：官方DSH仍不可用")
        native.projector.write()
        output("NATIVE_RECONNECT_FAILED "+type(exc).__name__)
        return False
