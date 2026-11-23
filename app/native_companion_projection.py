"""Trusted DSH -> read-only native SwiftUI status projection.

This is a sink of already authenticated DSH facts, not a separate Agent, not
another session, and never the source of actual tool approvals. No raw thought,
tool arguments, secrets or microphone PCM may cross this boundary.
"""
from __future__ import annotations
import json
import os
import re
import tempfile
import time
import uuid
from collections import deque
from pathlib import Path

DEFAULT=Path.home()/"Library/Application Support/Deepseek-live/companion-native"
ID=re.compile(r"^[a-zA-Z0-9_-]{8,128}$")
STATUS={"thinking","working","settling","approval_pending","cancel_requested","settled"}
PHASES={"idle","listening","transcribing","thinking","tool_pending",
        "approval_pending","voice_generating","speaking","error"}
FINAL={"answered","completed","failed","cancelled"}
APPROVED_SOURCES={"harness_assistant","harness_tool_events"}
MAX_TEXT=2000

class ProjectionError(ValueError):
    pass

def safe_text(value,limit):
    return value[:limit] if isinstance(value,str) else ""

class NativeCompanionProjector:
    def __init__(self,directory:Path=DEFAULT,clock=time.time):
        self.directory=directory
        self.clock=clock
        self.state=None
        self.revision=-1
        self.session_id=None
        self.turn_id=None
        self.task_id=None
        self.log=deque(maxlen=12)
        # Private durable, bounded *verified* current-session transcript.
        # The status.json stays small; it is NOT the source of history truth.
        self.history=deque(maxlen=120)

    def _history_path(self):
        return self.directory/"conversation-history-v3.json"

    def _save_history(self):
        if not self.session_id:return
        if self.history:
            self.state["answer_speech_id"]=self.history[-1].get("speech_id")
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.directory.is_symlink() or self.directory.stat().st_mode&0o077:
            raise ProjectionError("unsafe_history_directory")
        output=self._history_path()
        if output.is_symlink():raise ProjectionError("unsafe_history_target")
        raw=json.dumps({"schema":3,"session_id":self.session_id,
                        "session_verified":True,"turns":list(self.history)},
                       ensure_ascii=False,separators=(",",":")).encode()
        if len(raw)>220000:raise ProjectionError("history_oversize")
        temp=None
        try:
            with tempfile.NamedTemporaryFile(mode="wb",dir=self.directory,
                    prefix=".history-",delete=False) as f:
                temp=Path(f.name);os.fchmod(f.fileno(),0o600)
                f.write(raw);f.flush();os.fsync(f.fileno())
            os.replace(temp,output);os.chmod(output,0o600)
        finally:
            if temp is not None:temp.unlink(missing_ok=True)

    def _read_history(self,sid):
        output=self._history_path()
        try:
            info=output.lstat()
            if (output.is_symlink() or not output.is_file() or
                info.st_uid!=os.getuid() or info.st_mode&0o077 or
                info.st_size>220000 or info.st_size<20):
                return None
            saved=json.loads(output.read_text(encoding="utf-8"))
            if (saved.get("schema")!=3 or saved.get("session_id")!=sid or
                saved.get("session_verified") is not True):
                return None
            turns=saved.get("turns")
            if not isinstance(turns,list):return None
            origins={"model","preset","memory","clock","weather","weather_unavailable","failed"}
            results=[]
            for e in turns[-120:]:
                if (not isinstance(e,dict) or e.get("origin") not in origins or
                    not isinstance(e.get("user"),str) or
                    not isinstance(e.get("assistant"),str)):
                    return None
                steps=e.get("progress",[])
                if (not isinstance(steps,list) or len(steps)>8 or
                    not all(isinstance(z,str) and 1<=len(z)<=100 for z in steps)):
                    return None
                results.append({"user":e["user"][:400],
                    "assistant":e["assistant"][:900],"origin":e["origin"],
                    **({"progress":steps} if steps else {}),
                    **({"speech_id":e["speech_id"]} if isinstance(e.get("speech_id"),str) and ID.fullmatch(e["speech_id"]) else {})})
            return results
        except (OSError,ValueError,TypeError,UnicodeError,AttributeError):
            return None

    def _trusted_recent_preview(self,sid):
        # Never use history from another session, a symlink or an untrusted
        # local file. This is display-only, not a source of DSH approvals.
        if sid==self.session_id and self.history:
            return list(self.history)
        durable=self._read_history(sid)
        if durable is not None:return durable
        output=self.directory/"status.json"
        try:
            meta=output.lstat()
            if (not output.is_file() or output.is_symlink() or
                meta.st_mode & 0o077 or meta.st_size>32_768 or
                self.clock()-meta.st_mtime > 86400):
                return []
            saved=json.loads(output.read_text(encoding="utf-8"))
            if (saved.get("schema")!=1 or saved.get("session_id")!=sid or
                saved.get("session_verified") is not True):
                return []
            entries=saved.get("conversation_preview",[])
            if not isinstance(entries,list):return []
            safe=[]
            origins={"model","preset","memory","clock","weather","weather_unavailable","failed"}
            for e in entries[-20:]:
                if (not isinstance(e,dict) or e.get("origin") not in origins or
                    not isinstance(e.get("user"),str) or
                    not isinstance(e.get("assistant"),str)):
                    return []
                steps=e.get("progress",[])
                if (not isinstance(steps,list) or len(steps)>8 or
                    not all(isinstance(x,str) and 1<=len(x)<=100 for x in steps)):
                    return []
                safe.append({"user":e["user"][:400],
                             "assistant":e["assistant"][:900],
                             "origin":e["origin"],
                             **({"progress":steps} if steps else {})})
            return safe
        except (OSError,ValueError,TypeError,UnicodeError,AttributeError):
            return []

    def bind_session(self,result):
        if not isinstance(result,dict) or result.get("ok") is not True or result.get("pending_resume") is True:
            raise ProjectionError("unverified_dsh_session")
        sid=result.get("session_id")
        if not isinstance(sid,str) or not ID.fullmatch(sid):
            raise ProjectionError("invalid_authoritative_session")
        selected=result.get("last_request") or result.get("selected")
        if not isinstance(selected,dict):
            raise ProjectionError("missing_model_selection")
        model=selected.get("model")
        if not isinstance(model,str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}",model):
            raise ProjectionError("unverified_selected_model")
        recovered=self._trusted_recent_preview(sid)
        # R675: the small UI file can be truncated by an older gateway or
        # session rebinding, even while the official DSH v4 journal remains
        # intact. Recover only the same native session's user/final text,
        # never tool arguments/reasoning, and preserve local failed turns.
        from app.r675_native_history_recovery import recover_native_history
        journal=recover_native_history(sid,existing=recovered)
        rebuilt=len(journal)>len(recovered)
        if rebuilt:recovered=journal
        self.session_id=sid
        self.state={
            "schema":1,"updated_at_unix":self.clock(),"phase":"idle",
            "session_id":sid,"session_verified":True,
            "model_id":model,"model_confirmed":True,
            "answer_origin":"unknown","answer_verified":False,
            "user_text":"","answer_text":"",
            "reasoning_observed":False,
            "steps":[],"model_selection_source":"dsh_native_session",
            "search_enabled":result.get("search_enabled") is True,
            "search_supported":result.get("search_supported") is True,
            "tool_execution_verified":False,"last_outcome":"pending",
            "current_task_id":None,"conversation_preview":[],
            "turn_progress":[],
        }
        self.history.clear()
        self.history.extend(recovered)
        self.state["conversation_preview"]=list(self.history)[-12:]
        # R678: persist even a verified zero-turn new Session. Otherwise the
        # Mac UI keeps reading the prior Session's durable 60-turn history
        # while the Wi-Fi owner has already rebound to the new Agent.
        # R677 archives the previous exact history before any manual rotation;
        # the original native DSH journal remains immutable.
        self._save_history()
        self.revision=-1
        self.log.clear()
        self.turn_id=None
        self.task_id=None
        return self.snapshot()

    def _bound(self):
        if self.state is None or not self.session_id:
            raise ProjectionError("session_not_bound")

    def begin_turn(self,admission,text):
        self._bound()
        if self.turn_id is not None:
            raise ProjectionError("another_native_turn_active")
        if not isinstance(admission,dict) or admission.get("session_id")!=self.session_id:
            raise ProjectionError("turn_not_owned_by_session")
        turn,task=admission.get("turn_id"),admission.get("task_id")
        if not isinstance(turn,str) or not ID.fullmatch(turn) or len(turn)>64 or not isinstance(task,str) or not ID.fullmatch(task):
            raise ProjectionError("unverified_turn_identifiers")
        self.turn_id,self.task_id=turn,task
        self.revision=-1
        self.log.clear()
        self.state.pop("spoken_progress_text",None)
        self.state["turn_progress"]=[]
        self.state["failed_phone_reply_recorded"]=False
        self.state.update(phase="thinking",user_text=safe_text(text,600),
                          answer_text="",answer_verified=False,answer_speech_id=None,
                          answer_origin="unknown",reasoning_observed=False,
                          tool_execution_verified=False,last_outcome="pending",
                          current_task_id=task)
        self.record_step("thinking","已提交至原生会话，等待模型")
        return self.snapshot()

    def append_turn_progress(self,text):
        """Bounded, verified tool-phase timeline; never model thoughts."""
        self._bound()
        if not (self.turn_id and self.task_id and
                self.state.get("current_task_id")==self.task_id):
            raise ProjectionError("progress_without_current_turn")
        if not isinstance(text,str) or not 1<=len(text)<=100:
            raise ProjectionError("bad_verified_progress_text")
        entries=self.state.setdefault("turn_progress",[])
        if text not in entries:
            entries.append(text)
            self.state["turn_progress"]=entries[-8:]
        self.state["updated_at_unix"]=self.clock()

    def publish_spoken_progress(self,text):
        """Expose one verified current-turn line before its local TTS starts."""
        self._bound()
        if self.turn_id is None or self.task_id is None or self.state.get("current_task_id")!=self.task_id:
            raise ProjectionError("spoken_progress_without_current_turn")
        if not isinstance(text,str) or not text.strip() or len(text)>200:
            raise ProjectionError("spoken_progress_invalid")
        self.state["spoken_progress_text"]=text
        self.append_turn_progress(text[:100])
        self.state["updated_at_unix"]=self.clock()
        return self.snapshot()

    def record_step(self,kind,message):
        self._bound()
        if kind not in PHASES:
            raise ProjectionError("unsupported_step")
        self.log.append({"phase":kind,"label":safe_text(message,100)})
        self.state["phase"]=kind
        self.state["steps"]=list(self.log)
        self.state["updated_at_unix"]=self.clock()

    def apply_verified_facts(self,facts):
        self._bound()
        if not self.turn_id or not isinstance(facts,dict):
            raise ProjectionError("facts_without_native_turn")
        if facts.get("protocolVersion")!=1 or facts.get("session_id")!=self.session_id or facts.get("turn_id")!=self.turn_id:
            raise ProjectionError("cross_session_or_turn_facts")
        rev=facts.get("revision")
        if type(rev) is not int or rev<=self.revision or rev>1_000_000_000:
            raise ProjectionError("stale_or_malformed_revision")
        phase=facts.get("task_phase")
        if phase not in STATUS or type(facts.get("tool_active_count")) is not int:
            raise ProjectionError("invalid_native_phase")
        if type(facts.get("approval_pending")) is not bool or type(facts.get("tool_failed")) is not bool:
            raise ProjectionError("invalid_native_flags")
        if facts["approval_pending"]:
            if phase!="approval_pending":
                raise ProjectionError("approval_mismatch")
            ui_phase="approval_pending"
            label="等待原生工具权限审批"
        elif phase=="working":
            ui_phase="tool_pending"
            label="原生工具执行中 · 不展示未经确认的执行结果"
        elif phase=="settling":
            ui_phase="thinking"
            label="等待原生 Harness 最终执行回执"
        elif phase=="settled":
            ui_phase="voice_generating" if facts.get("outcome") in ("answered","tool_verified") else "error"
            label="模型回复已确认，待设备语音回执" if ui_phase=="voice_generating" else "任务未成功"
        else:
            ui_phase="thinking"
            label="模型处理中（不展示私有推理正文）"
        self.revision=rev
        self.record_step(ui_phase,label)
        # R585: only verified native tool-stage codes, no model claims or
        # screen/arguments enter conversation presentation.
        phase_labels={
            "connecting_phone":"正在连接手机",
            "opening_app":"正在打开应用",
            "entering_text":"正在输入内容",
            "reading_screen":"正在查看手机页面",
            "navigating_screen":"正在浏览手机页面",
            "releasing_phone":"正在结束手机操作",
            "approval_requested":"正在等待手机授权",
            "phone_tool_busy":"正在处理手机任务",
            "delegated_task":"手机任务已提交，正在等待真实结果",
        }
        if phase in ("working","approval_pending") and facts["tool_active_count"]>0:
            step=facts.get("phone_tool_step")
            if step in phase_labels:self.append_turn_progress(phase_labels[step])
            # Only the authenticated Bridge may report this native CUA stage.
            # Tool arguments, screenshots and model claims never enter the UI.
            if facts.get("computer_tool_step")=="cua_running":
                self.append_turn_progress("正在通过原生工具查看 Mac 窗口")
            elif facts.get("computer_tool_step")=="cua_waiting_permission":
                self.append_turn_progress("Mac 电脑操作等待本人在应用中选择授权")
        count=facts.get("computer_tool_succeeded_count")
        if (type(count) is int and 0<count<=32):
            self.append_turn_progress("Mac 电脑工具已完成 %d 步"%count)
        if facts["approval_pending"]:
            self.append_turn_progress("正在等待工具审批")
        return self.snapshot()

    def finish_verified_result(self,result):
        self._bound()
        if not self.turn_id or not isinstance(result,dict):
            raise ProjectionError("no_native_task")
        if result.get("session_id")!=self.session_id or result.get("task_id")!=self.task_id or result.get("turn_id")!=self.turn_id:
            raise ProjectionError("result_identity_mismatch")
        status=result.get("status")
        if status not in FINAL:
            raise ProjectionError("unsettled_native_result")
        self.state.pop("spoken_progress_text",None)
        if status in ("answered","completed"):
            answer=result.get("result")
            if not isinstance(answer,dict) or answer.get("source") not in APPROVED_SOURCES:
                raise ProjectionError("unverified_answer_provenance")
            msg=answer.get("text")
            if not isinstance(msg,str) or not msg.strip():
                raise ProjectionError("missing_native_answer")
            self.state.update(answer_text=safe_text(msg,MAX_TEXT),
                              answer_verified=True,answer_origin="model",
                              reasoning_observed=answer.get("reasoning_observed") is True,
                              tool_execution_verified=(status=="completed" and answer.get("execution_verified") is True),
                              last_outcome=status)
            tools=answer.get("tool_receipts",[])
            if isinstance(tools,list):
                for tool in tools[:8]:
                    if isinstance(tool,dict) and isinstance(tool.get("name"),str) and isinstance(tool.get("receipt"),str):
                        self.record_step("tool_pending",safe_text(tool["name"],40)+" · "+safe_text(tool["receipt"],30))
            # Only authoritative final text enters the six-turn UI preview.
            self.history.append({"speech_id":uuid.uuid4().hex,"user":safe_text(self.state.get("user_text"),400),
                                 "assistant":safe_text(msg,900),"origin":"model",
                                 "progress":list(self.state.get("turn_progress",[]))[-8:]})
            self.state["conversation_preview"]=list(self.history)[-12:]
            self._save_history()
            self.record_step("voice_generating","已收到原生模型最终回复；等待语音播放")
        else:
            self.state.update(answer_verified=False,answer_text="",last_outcome=status)
            self.record_step("error","原生任务结束："+status)
        self.turn_id=None
        self.task_id=None
        self.state["current_task_id"]=None
        return self.snapshot()

    def record_failed_phone_reply(self,reply):
        """Persist an actual, bounded local terminal for a failed tool turn.

        Only explicitly allowed native failures qualify; this never claims
        that earlier Pinky/CUA actions were rolled back or fully succeeded.
        """
        self._bound()
        if (self.turn_id is not None or self.task_id is not None or
            self.state.get("last_outcome") not in
            ("phone_partial_failure","phone_connect_failed",
             "phone_tool_failed","phone_recovered_unverified",
             "computer_timeout_cancelled","computer_tool_failed") or
            not isinstance(reply,str) or not 1<=len(reply)<=900 or
            not self.state.get("user_text") or
            self.state.get("failed_phone_reply_recorded") is True):
            raise ProjectionError("not_verified_failed_phone_terminal")
        item={"speech_id":uuid.uuid4().hex,
              "user":safe_text(self.state.get("user_text"),400),
              "assistant":safe_text(reply,900),"origin":"failed",
              "progress":list(self.state.get("turn_progress",[]))[-8:]}
        self.history.append(item)
        self.state["failed_phone_reply_recorded"]=True
        self.state["conversation_preview"]=list(self.history)[-12:]
        self._save_history()
        self.state["updated_at_unix"]=self.clock()
        return self.snapshot()

    def fail_current_turn(self,reason,*,visible=True):
        """Keep the real transcript and failure, never invent model output.

        Called when an official task has failed or its identity cannot be
        verified. Drop the active projector turn so subsequent real microphone
        recordings can be admitted without re-submitting the previous task.
        """
        self._bound()
        if not isinstance(reason,str):raise ProjectionError("bad_failure_reason")
        # A verified DSH answer belongs to the conversation even when the
        # *later* PCM2 speaker ACK fails. Keep its provenance and text;
        # report a playback failure separately without resubmitting DSH.
        self.state.pop("spoken_progress_text",None)
        answer_survived=(self.state.get("answer_verified") is True and
                         bool(self.state.get("answer_text")))
        if answer_survived:
            self.state.update(last_outcome="playback_failed",
                              current_task_id=None,native_facts_connected=False,
                              voice_playback_verified=False)
        else:
            self.state.update(answer_origin="failed",answer_verified=False,
                              answer_text="",tool_execution_verified=False,
                              last_outcome="failed",current_task_id=None,
                              native_facts_connected=False)
        if visible and not answer_survived and self.state.get("user_text"):
            self.history.append({"speech_id":uuid.uuid4().hex,"user":safe_text(self.state["user_text"],400),
                                 "assistant":"本次请求未取得可验证的回复，请查看诊断。",
                                 "origin":"failed",
                                 "progress":list(self.state.get("turn_progress",[]))[-8:]})
            self.state["conversation_preview"]=list(self.history)[-12:]
        self._save_history()
        self.turn_id=None
        self.task_id=None
        self.revision=-1
        self.record_step("error",safe_text(reason,100))
        return self.snapshot()

    def preset_result(self,reply,*,same_session:bool,verified:bool):
        self._bound()
        if not (same_session is True and verified is True) or self.turn_id is not None:
            raise ProjectionError("preset_without_verified_local_ownership")
        if not isinstance(reply,str) or not reply.strip():
            raise ProjectionError("bad_preset_reply")
        self.state.update(answer_origin="preset",answer_verified=True,
                          answer_text=safe_text(reply,MAX_TEXT),last_outcome="preset")
        self.history.append({"speech_id":uuid.uuid4().hex,"user":safe_text(self.state.get("user_text"),400),
                             "assistant":safe_text(reply,900),"origin":"preset"})
        self.state["conversation_preview"]=list(self.history)[-12:]
        self._save_history()
        self.record_step("idle","已确认的本地预置回复（无模型请求）")
        return self.snapshot()

    def clock_result(self,reply,*,same_session:bool,verified:bool,transcript=None):
        """Physical verified STT -> Mac system clock; zero model/tool calls."""
        self._bound()
        if same_session is not True or verified is not True or self.turn_id is not None:
            raise ProjectionError("clock_not_verified")
        if not isinstance(reply,str) or not reply.strip() or len(reply)>100:
            raise ProjectionError("clock_reply_invalid")
        if transcript is not None:
            self.state["user_text"]=safe_text(transcript,600)
        self.state.update(answer_origin="clock",answer_verified=True,
                          answer_text=reply,last_outcome="clock",
                          tool_execution_verified=False)
        self.history.append({"speech_id":uuid.uuid4().hex,"user":safe_text(self.state.get("user_text"),400),
                             "assistant":safe_text(reply,100),"origin":"clock"})
        self.state["conversation_preview"]=list(self.history)[-12:]
        self._save_history()
        self.record_step("voice_generating","本地系统时间已核实，正在播报")
        return self.snapshot()

    def weather_result(self,reply,*,same_session:bool,verified:bool,available:bool):
        """Local independently verified weather observation/provenance only."""
        self._bound()
        if same_session is not True or verified is not True or self.turn_id is not None:
            raise ProjectionError("weather_not_verified")
        if not isinstance(reply,str) or not reply.strip() or len(reply)>900:
            raise ProjectionError("weather_reply_invalid")
        origin="weather" if available else "weather_unavailable"
        self.state.update(answer_origin=origin,answer_verified=True,
                          answer_text=safe_text(reply,MAX_TEXT),last_outcome=origin,
                          tool_execution_verified=False)
        self.history.append({"speech_id":uuid.uuid4().hex,"user":safe_text(self.state.get("user_text"),400),
                             "assistant":safe_text(reply,900),"origin":origin})
        self.state["conversation_preview"]=list(self.history)[-12:]
        self._save_history()
        self.record_step("voice_generating",
                         "Open-Meteo 实时来源已核验，正在播报" if available
                         else "天气来源不可用；未编造实时数据")
        return self.snapshot()

    def explicit_memory_result(self,reply,*,same_session:bool,verified:bool):
        self._bound()
        if not (same_session is True and verified is True) or self.turn_id is not None:
            raise ProjectionError("explicit_memory_not_verified")
        if not isinstance(reply,str) or not reply.strip() or len(reply)>1200:
            raise ProjectionError("explicit_memory_reply_invalid")
        self.state.update(answer_origin="memory",answer_verified=True,
                          answer_text=reply,last_outcome="explicit_memory")
        self.history.append({"speech_id":uuid.uuid4().hex,"user":safe_text(self.state.get("user_text"),400),
                             "assistant":safe_text(reply,900),"origin":"memory"})
        self.state["conversation_preview"]=list(self.history)[-12:]
        self._save_history()
        self.record_step("idle","用户明确检索已有E1b事实，无自动保存或模型请求")
        return self.snapshot()

    def device_playback(self,*,started:bool,verified:bool):
        self._bound()
        if verified is not True:
            raise ProjectionError("playback_not_confirmed")
        if started:
            self.state["voice_last_start_at_unix"]=self.clock()
        else:
            self.state["voice_last_end_at_unix"]=self.clock()
        self.record_step("speaking" if started else "idle",
                         "实体扬声器开始播放" if started else "实体扬声器结束播放")
        return self.snapshot()

    def snapshot(self):
        self._bound()
        s=dict(self.state)
        s["steps"]=list(self.log)
        return s

    def write(self):
        self._bound()
        target=self.directory
        if target.is_symlink():
            raise ProjectionError("unsafe_snapshot_symlink")
        target.mkdir(parents=True,exist_ok=True,mode=0o700)
        if target.stat().st_mode&0o077:
            raise ProjectionError("snapshot_private_directory_required")
        output=target/"status.json"
        if output.is_symlink():
            raise ProjectionError("unsafe_snapshot_target")
        raw=json.dumps(self.snapshot(),ensure_ascii=False,separators=(",",":")).encode()
        if len(raw)>32_768:
            raise ProjectionError("snapshot_size_limit")
        temp=None
        try:
            with tempfile.NamedTemporaryFile(mode="wb",dir=target,prefix=".status-",delete=False) as f:
                temp=Path(f.name)
                os.fchmod(f.fileno(),0o600)
                f.write(raw);f.flush();os.fsync(f.fileno())
            os.replace(temp,output)
            os.chmod(output,0o600)
        finally:
            if temp is not None:temp.unlink(missing_ok=True)
        return output
