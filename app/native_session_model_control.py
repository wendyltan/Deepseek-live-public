"""Explicit Mac button -> same official DSH Session model change.

File is a bounded single-use local request, not an LLM prompt, and results
become visible only after official /session confirms the model actually used.
"""
from __future__ import annotations
import json,stat,time
from pathlib import Path

CONTROL=Path.home()/'Library/Application Support/Deepseek-live/companion-native/model-switch-request.json'
APPROVED={'deepseek-flash','deepseek-v4-pro'}

def apply_pending_model(native, *, target=CONTROL, clock=time.time, output=print):
    if not native.bound or native.projector.session_id is None or native.projector.turn_id is not None:
        return False
    if target.is_symlink() or not target.is_file():return False
    meta=target.stat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_size>512 or meta.st_size<40 or meta.st_mode&0o077:
        output('R129_MODEL_REQUEST_UNSAFE')
        return False
    try:
        req=json.loads(target.read_text(encoding='utf-8'))
        target.unlink()
    except (OSError,ValueError,UnicodeError):
        return False
    if (not isinstance(req,dict) or req.get('schema')!=1 or
        req.get('session_id')!=native.projector.session_id or
        req.get('model') not in APPROVED or
        type(req.get('at')) not in (int,float) or
        abs(clock()-req['at'])>45):
        output('R129_MODEL_REQUEST_REJECTED_WRONG_SESSION')
        return False
    wanted=req['model']
    try:
        listed=native.adapter.models()
        known={m.get('id') for m in listed.get('models',[]) if isinstance(m,dict)}
        if wanted not in known:raise ValueError('model_not_advertised')
        before=native.adapter.inspect(native.tab_id)
        if before.get('ok') is not True or before.get('session_id')!=native.projector.session_id:
            raise ValueError('current_session_unverified')
        effective=native.adapter.switch(native.tab_id,wanted)
        after=native.adapter.inspect(native.tab_id)
        if (effective!=wanted or after.get('ok') is not True or
            after.get('session_id')!=native.projector.session_id or
            (after.get('selected') or {}).get('model')!=wanted):
            raise ValueError('model_switch_not_confirmed_by_dsh')
        native.projector.state.update(model_id=wanted,model_confirmed=True,
          model_selection_source='dsh_native_session',updated_at_unix=native.projector.clock())
        native.projector.record_step('idle','官方DSH会话已确认模型切换：'+wanted)
        native.projector.write()
        output('R129_MODEL_REQUEST_VERIFIED '+wanted)
        return True
    except (ValueError,RuntimeError,KeyError,TypeError,OSError) as exc:
        output('R129_MODEL_REQUEST_UNVERIFIED '+type(exc).__name__)
        return False
