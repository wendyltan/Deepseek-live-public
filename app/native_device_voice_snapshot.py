"""Device-only real USB/STT facts for the Mac native mini window.

This *never* creates or impersonates an official DSH Session. When DSH is
connected, its native provenance takes priority over the hardware lab.
"""
from __future__ import annotations
import json
import os
import tempfile
import time
from pathlib import Path
from app.native_companion_projection import DEFAULT,ProjectionError

def emit_device_voice_snapshot(*,transcript:str,reply:str|None,
                               phase:str,confirmed_stt:bool,
                               confirmed_preset:bool,
                               now=None,directory:Path=DEFAULT):
    if confirmed_stt is not True:
        raise ProjectionError("native_device_transcript_unverified")
    if phase not in ("transcribing","voice_generating","speaking","idle","error"):
        raise ProjectionError("unverified_device_phase")
    if not isinstance(transcript,str) or len(transcript)>600 or not transcript.strip():
        raise ProjectionError("invalid_hardware_transcript")
    if reply is not None and (not isinstance(reply,str) or len(reply)>2000):
        raise ProjectionError("invalid_preset_text")
    if reply and confirmed_preset is not True:
        raise ProjectionError("unverified_preset_answer")
    now=time.time() if now is None else now
    if not isinstance(now,(int,float)) or now<=0:
        raise ProjectionError("invalid_snapshot_time")
    if directory.is_symlink():
        raise ProjectionError("native_private_directory_symlink")
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if directory.stat().st_mode&0o077:
        raise ProjectionError("native_snapshot_private_directory_required")
    target=directory/"status.json"
    if target.is_symlink():
        raise ProjectionError("native_snapshot_symlink")
    if target.exists() and target.is_file():
        if target.stat().st_size>32_768:
            raise ProjectionError("existing_snapshot_oversize")
        current=json.loads(target.read_text(encoding="utf-8"))
        if current.get("session_verified") is True and now-float(current.get("updated_at_unix",0))<30:
            raise ProjectionError("official_dsh_session_has_priority")
    s={
        "schema":1,"updated_at_unix":now,"phase":phase,
        "session_id":None,"session_verified":False,
        "model_id":None,"model_confirmed":False,
        "answer_origin":"preset" if reply and confirmed_preset else "unknown",
        "answer_verified":bool(reply and confirmed_preset),
        "user_text":transcript[:600],"answer_text":(reply or "")[:2000],
        "reasoning_observed":False,
        "steps":[
            {"phase":"transcribing","label":"来自ESP32实体麦克风的已完成本地Whisper语音识别"},
            {"phase":phase,"label":"本地预置回复；尚未调用原生DSH模型" if confirmed_preset
                    else "等待同一原生DSH会话处理"},
        ],
        "model_selection_source":None,
        "search_enabled":False,"search_supported":False,
        "tool_execution_verified":False,"last_outcome":"preset" if confirmed_preset else "pending",
        "current_task_id":None,
    }
    content=json.dumps(s,ensure_ascii=False,separators=(",",":")).encode()
    if len(content)>32_768:raise ProjectionError("oversized_local_snapshot")
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(mode="wb",dir=directory,prefix=".local-snapshot-",
                                         delete=False) as output:
            tmp=Path(output.name)
            os.fchmod(output.fileno(),0o600)
            output.write(content);output.flush();os.fsync(output.fileno())
        os.replace(tmp,target);os.chmod(target,0o600)
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)
    return target
