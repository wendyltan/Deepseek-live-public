"""Official DSH -> native Mac mini status -> approved 35 motion director.

One existing DshP1Adapter, one official Harness Session, no new Agent and
no model/API requests unless chat_once is called with explicit user text.
This is not the ESP32 SD renderer or a microphone uplink by itself.
"""
from __future__ import annotations

import re
import time

from app.dsh_p1_adapter import DshP1Adapter,DshUnavailable
from app.native_companion_projection import NativeCompanionProjector,ProjectionError
from app.selected_motion_director import SelectedMotionDirector,MotionPlanError

_TAB=re.compile(r"^[a-f0-9]{32}$")

class NativeCompanionSessionError(RuntimeError):pass

class OfficialVisualObserver:
    def __init__(self,projector, director, mapping,clock,physical_motion_sink=None,
                 on_verified_progress=None):
        self.projector=projector
        self.director=director
        self.mapping=mapping
        self.clock=clock
        self.active=True
        self.failed_reason=None
        self.physical_motion_sink=physical_motion_sink
        self.on_verified_progress=on_verified_progress
        self._reported_progress=set()
        self._last_motion_receipt=None
        self._task_started_at=None
        self._last_phone_stage=None
        self._last_computer_stage=None
        self._reported_computer_step=0
    def _motion(self,phase,event=None):
        name=self.director.on_state(phase,self.clock(),verified=True,event=event)
        entry=self.mapping[name]
        self.projector.state.update(animation=name,animation_id=entry["id"],
            animation_role=entry["decision"],animation_source="user_selected35")
        self.projector.write()
        if self.physical_motion_sink is not None:
            try:
                # Only official DSH observer events reach the actual USB device.
                # Status file writes or unverified user text never create motion.
                # DSH sometimes repeats the same fact burst within a second.
                # Keep the previous *verified actual-frame receipt* instead
                # of re-hashing the same 3MB SD animation and blocking the
                # official DSH observer. Any different phase always updates.
                stamp=self.clock()
                prev=self._last_motion_receipt
                if (prev is not None and prev[0]==(phase,entry['id'])
                    and stamp-prev[1]<1.0):
                    receipt=prev[2]
                else:
                    receipt=self.physical_motion_sink(phase,entry['id'])
                    if isinstance(receipt,dict) and receipt.get('actual_esp32_frame_verified') is True:
                        self._last_motion_receipt=((phase,entry['id']),stamp,receipt)
                    else:
                        self._last_motion_receipt=None
                self.projector.state['esp32_frame_verified']=(
                    isinstance(receipt,dict) and receipt.get('actual_esp32_frame_verified') is True)
                self.projector.state['esp32_frame_motion_id']=(
                    receipt.get('motion_id') if self.projector.state['esp32_frame_verified'] else None)
                # SD content capability is not proof of one decoded frame.
                self.projector.state['motion_sd_verified']=(
                    self.projector.state['esp32_frame_verified'] and
                    isinstance(receipt,dict) and receipt.get('sd_motion_verified') is True)
                self.projector.write()
            except (OSError,RuntimeError,ValueError):
                # Peripheral motion failure must not cancel a real DSH answer,
                # forge a tool outcome or resubmit the user's request.
                self.projector.state['esp32_frame_verified']=False
                self.projector.state['esp32_frame_motion_id']=None
                self.projector.state['motion_sd_verified']=False
                self.projector.record_step(phase,'ESP32动作未核实（DSH会话仍独立执行）')
                self.projector.write()
    def started(self,admission):
        if not self.active:return
        try:
            self.projector.begin_turn(admission,self.projector.state.get("pending_user_text",""))
            self._task_started_at=time.monotonic()
            self._motion("thinking",event="thinking")
            if (callable(self.on_verified_progress) and
                isinstance(admission,dict) and isinstance(admission.get("task_id"),str)
                and admission["task_id"]):
                self._reported_progress.add("submitted")
                self.on_verified_progress("submitted")
        except (ProjectionError,MotionPlanError,KeyError,ValueError) as err:
            self.unavailable()
    def facts(self,fact):
        if not self.active:return
        try:
            snap=self.projector.apply_verified_facts(fact)
            phase=snap["phase"]
            event="tool_verified" if fact.get("outcome")=="tool_verified" else None
            # A tool receipt is not generic task success.
            self._motion(phase,event=event)
            if callable(self.on_verified_progress) and isinstance(fact,dict):
                # R541: this stage derives from a verified native phone tool
                # call (not a model claim). Never assert successful execution.
                stages=frozenset(("connecting_phone","opening_app",
                    "entering_text","reading_screen","navigating_screen",
                    "delegated_task","releasing_phone","approval_requested",
                    "phone_tool_busy"))
                if (fact.get("task_phase")=="working" and
                    type(fact.get("tool_active_count")) is int and
                    fact["tool_active_count"]>0):
                    stage=fact.get("phone_tool_step")
                    self._last_phone_stage=stage if stage in stages else None
                    if stage in stages:
                        if stage not in self._reported_progress:
                            self._reported_progress.add(stage)
                            self.on_verified_progress(stage)
                    elif "tool_running" not in self._reported_progress:
                        self._reported_progress.add("tool_running")
                        self.on_verified_progress("tool_running")
                # R675: the Mac CUA has its own native tool receipt; Pinky
                # stage names must not be reused as imaginary Mac actions.
                # Announce only a real in-flight CUA or an increased success
                # count. Do not claim that the whole desktop task succeeded.
                computer=fact.get("computer_tool_step")
                if (fact.get("task_phase") in ("working","approval_pending") and
                    computer in ("cua_running","cua_waiting_permission")):
                    self._last_computer_stage=computer
                    if computer not in self._reported_progress:
                        self._reported_progress.add(computer)
                        self.on_verified_progress(computer)
                n=fact.get("computer_tool_succeeded_count")
                if type(n) is int and 0<n<=32 and n>self._reported_computer_step:
                    # Send at most one step update per facts revision. The
                    # count is the Bridge's actual successful native calls.
                    self._reported_computer_step=n
                    key="cua_step_%d"%n
                    if key not in self._reported_progress:
                        self._reported_progress.add(key)
                        self.on_verified_progress(key)
                if (fact.get("task_phase")=="approval_pending" and
                    fact.get("approval_pending") is True and
                    "approval_pending" not in self._reported_progress):
                    self._reported_progress.add("approval_pending")
                    self.on_verified_progress("approval_pending")
        except (ProjectionError,MotionPlanError,KeyError):
            self.unavailable()
    def tick(self):
        # Polling only an existing authenticated DSH task. No phone calls.
        if not self.active or self._task_started_at is None:return
        elapsed=time.monotonic()-self._task_started_at
        if not callable(self.on_verified_progress):return
        for after,name in ((70.0,"still_working_later"),
                           (25.0,"still_working"),
                           # R679: native CUA quick operations should
                           # finish without unnecessary spoken steps;
                           # Pinky keeps its six-second re-offer.
                           (10.0 if self._last_computer_stage else 6.0,
                            "initial_ongoing")):
            if elapsed>=after and name not in self._reported_progress:
                self._reported_progress.add(name)
                if name=="initial_ongoing":
                    # Re-offer a live tool stage skipped during the first
                    # 6 seconds. Otherwise only say the DSH turn is working.
                    stage=(self._last_computer_stage if
                           self._last_computer_stage=="cua_waiting_permission" else
                           ("cua_step_%d"%self._reported_computer_step if
                            self._reported_computer_step>0 else
                            self._last_computer_stage))
                    self.on_verified_progress(self._last_phone_stage or
                                              stage or "tool_running")
                else:
                    self.on_verified_progress(name)

    def unavailable(self):
        self.active=False
        self.failed_reason="native_facts_gap"
        # Never substitute invented animations/tools/approvals.
        if self.projector.state:
            self.projector.state["native_facts_connected"]=False
            self.projector.record_step("error","DSH事实流中断，停止推测状态")
            self.projector.write()

class NativeDshCompanionSession:
    def __init__(self,adapter:DshP1Adapter,tab_id:str,*,clock=time.monotonic,
                 projector=None,director=None):
        if not isinstance(tab_id,str) or not _TAB.fullmatch(tab_id):
            raise NativeCompanionSessionError("native_session_id_invalid")
        self.adapter=adapter
        self.tab_id=tab_id
        self.clock=clock
        self.projector=projector or NativeCompanionProjector()
        self.director=director or SelectedMotionDirector()
        profile=self.director.profile
        self.mapping={x["name"]:x for x in profile["selected"]}
        self.bound=False
        self.executed_turns=set()
        self.physical_motion_sink=None  # activated only after real ESP32 CAPS+USB proof

    def attach_authoritative_session(self):
        if self.bound:
            return self.projector.snapshot()
        # The existing P1/Bridge /bind endpoint is free and session-scoped.
        # Do not generate an LLM request, change model or mutate tools here.
        native=self.adapter.ensure(self.tab_id)
        self.projector.bind_session(native)
        self.bound=True
        name=self.director.current
        item=self.mapping[name]
        self.projector.state.update(animation=name,animation_id=item["id"],
            animation_role=item["decision"],animation_source="user_selected35",
            native_facts_connected=False)
        self.projector.write()
        return self.projector.snapshot()

    def chat_once(self,verified_user_text:str,*,memory_context:str="",
                  on_verified_progress=None):
        if not self.bound:
            raise NativeCompanionSessionError("official_session_not_attached")
        if not isinstance(verified_user_text,str) or not verified_user_text.strip() or len(verified_user_text)>4000:
            raise NativeCompanionSessionError("verified_transcript_required")
        # R540: explicit owner approval grants the normal Pinky tool catalog
        # to this one authenticated, user-spoken phone turn. Pinky itself,
        # not this bridge, enforces all app/device/human approval rules.
        from app.r517_pinky_voice_contract import is_phone_task,is_phone_readonly_request
        phone_intent=is_phone_task(verified_user_text)
        if phone_intent:
            try:
                self.adapter.pinky_policy_capabilities(self.tab_id)
            except DshUnavailable:
                self.projector.state.update(
                    user_text=verified_user_text[:600],
                    pending_user_text=verified_user_text[:600],
                    answer_text="Pinky 手机工具暂时无法确认，请检查连接和权限。",
                    answer_origin="local_phone_policy",answer_verified=False,
                    current_task_id=None,last_outcome="phone_policy_unavailable")
                self.projector.record_step(
                    "error","Pinky 官方手机工具未就绪，未执行手机操作")
                self.projector.write()
                raise
        # Caller must accept only actual user/STT-verified utterances.
        # This module deliberately does not self-authenticate ESP32 mic input.
        self.projector.state["pending_user_text"]=verified_user_text[:600]
        obs=OfficialVisualObserver(self.projector,self.director,self.mapping,self.clock,
                                   physical_motion_sink=self.physical_motion_sink,
                                   on_verified_progress=on_verified_progress)
        if not isinstance(memory_context,str) or len(memory_context)>900:
            raise NativeCompanionSessionError("memory_context_too_large")
        # Only one verified original user turn. Context is bounded local data;
        # the status/history bubble still displays the actual transcribed words.
        final_prompt=(memory_context+"\n\n本次用户原话："+verified_user_text) if memory_context else verified_user_text
        try:
            reply=self.adapter.chat(self.tab_id,final_prompt,visual_observer=obs,**({'phone_policy':True} if phone_intent else {}))
            task_id=reply.get("task_id")
            if not isinstance(task_id,str) or task_id in self.executed_turns:
                raise NativeCompanionSessionError("duplicate_or_unknown_native_task")
            self.executed_turns.add(task_id)
            # MUST re-read exact official Bridge result: P1's normal response strips
            # turn/session IDs and tool provenance for browser privacy.
            verified=self.adapter._ok("result",{"task_id":task_id})
            snap=self.projector.finish_verified_result(verified)
            if verified.get("status")=="completed" and snap.get("tool_execution_verified"):
                name=self.director.on_state("tool_pending",self.clock(),verified=True,event="tool_verified")
            else:
                name=self.director.on_state("idle",self.clock(),verified=True)
            item=self.mapping[name]
            self.projector.state.update(animation=name,animation_id=item["id"],
                animation_role=item["decision"],animation_source="user_selected35",
                native_facts_connected=obs.active)
            if reply.get("action") in (
                "phone_partial_failure","phone_connect_failed","phone_tool_failed",
                "phone_recovered_unverified"):
                # Local truthful error message, NOT a verified DSH answer.
                self.projector.state.update(
                    answer_text=reply["reply"][:600],
                    answer_origin="local_phone_failure",
                    answer_verified=False,tool_execution_verified=False,
                    last_outcome=reply["action"])
                # A recovered intermediate tap and a truly failed final
                # task are distinct. The original official failed status
                # remains preserved; never rewrite a native tool outcome.
                if reply["action"]=="phone_recovered_unverified":
                    self.projector.record_step(
                        "error","手机曾有一次失败点击；后续操作已继续，最终页面待核对")
                else:
                    self.projector.record_step("error","手机有步骤失败，等待本人检查")
                self.projector.record_failed_phone_reply(reply["reply"])
            elif reply.get("action") in ("computer_timeout_cancelled","computer_tool_failed"):
                # Only a verified native cancelled or failed terminal is spoken. This
                # may follow partial CUA side effects, never imply rollback.
                self.projector.state.update(
                    answer_text=reply["reply"][:600],
                    answer_origin="local_tool_failure",answer_verified=False,
                    tool_execution_verified=False,
                    last_outcome=reply["action"])
                self.projector.record_step("error",
                    ("Mac 原生电脑工具超时，任务已取消；最终结果未核实" if
                     reply["action"]=="computer_timeout_cancelled" else
                     "Mac 原生电脑工具步骤失败；最终结果未核实"))
                self.projector.record_failed_phone_reply(reply["reply"])
            self.projector.write()
        except (DshUnavailable,ProjectionError,NativeCompanionSessionError):
            # P0 R458: an earlier DSH error could strand projector.turn_id,
            # causing next *new* microphone question to fail with ProjectionError.
            # Clear only the local UI ownership; adapter never retries a
            # possibly charged task, and backend/WSS still fails this turn.
            if self.projector.turn_id is not None:
                try:
                    # R672: retain a truthful failed conversation bubble,
                    # rather than silently losing a real ESP32 utterance.
                    self.projector.fail_current_turn("DSH本轮未取得可验证结果",
                                                    visible=True)
                    self.projector.write()
                except (ProjectionError,OSError,ValueError):
                    pass
            raise

        verified_receipts=(verified.get("result") or {}).get("tool_receipts")
        # Native completion is not automatically proof of the iPhone's
        # business state. A screen query is verified only with a successful
        # observe receipt from this one Pinky-scoped official turn.
        phone_policy_scoped=(phone_intent and
            (verified.get("result") or {}).get("phone_pinky_policy_scoped") is True)
        from app.r517_pinky_voice_contract import (
            readonly_query_receipts_verified,front_app_observation_verified,
            screen_observation_verified,phone_tool_stage,is_unsent_draft_request,
            unsent_draft_receipts_consistent,
            direct_action_receipts_consistent,
            is_phone_search_only_request,
            recovered_readonly_search_receipts_consistent,
            completed_readonly_search_receipts_consistent)
        phone_search_completed=(phone_intent and
            phone_policy_scoped and
            verified.get("status")=="completed" and
            snap.get("tool_execution_verified") is True and
            (verified.get("result") or {}).get(
                "phone_completed_readonly_search") is True and
            is_phone_search_only_request(verified_user_text) and
            completed_readonly_search_receipts_consistent(verified_receipts))
        phone_search_recovered=(phone_intent and
            phone_policy_scoped and
            verified.get("status")=="completed" and
            snap.get("tool_execution_verified") is True and
            (verified.get("result") or {}).get(
                "phone_recovered_readonly_search") is True and
            is_phone_search_only_request(verified_user_text) and
            recovered_readonly_search_receipts_consistent(verified_receipts))
        phone_readonly_scoped=(phone_intent and
            (verified.get("result") or {}).get("phone_read_only_scoped") is True)
        phone_readonly_query=(phone_readonly_scoped and
            readonly_query_receipts_verified(verified_receipts,enforced=True) and
            is_phone_readonly_request(verified_user_text) and
            verified.get("status")=="completed" and
            snap.get("tool_execution_verified") is True)
        phone_front_app_observed=(phone_policy_scoped and
            front_app_observation_verified(verified_user_text,verified_receipts) and
            verified.get("status")=="completed" and
            snap.get("tool_execution_verified") is True)
        phone_screen_observed=(phone_policy_scoped and
            screen_observation_verified(verified_user_text,verified_receipts) and
            verified.get("status")=="completed" and
            snap.get("tool_execution_verified") is True)
        # Only exact official Pinky task result, never assistant text.
        delegation=(verified.get("result") or {}).get("phone_delegation_state")
        if (not phone_policy_scoped or
            verified.get("status")!="completed" or
            snap.get("tool_execution_verified") is not True or
            delegation not in ("running","done","failed","stopped","cancelled",
                               "partial","waiting_for_person","uncertain")):
            delegation=None
        confirmed_launch=(verified.get("result") or {}).get("phone_confirmed_launch_app")
        if (not phone_policy_scoped or verified.get("status")!="completed" or
            snap.get("tool_execution_verified") is not True or
            not isinstance(confirmed_launch,str) or
            not 1<=len(confirmed_launch)<=48):
            confirmed_launch=None
        confirmed_unsent_draft=(phone_policy_scoped and
            is_unsent_draft_request(verified_user_text) and
            verified.get("status")=="completed" and
            snap.get("tool_execution_verified") is True and
            unsent_draft_receipts_consistent(verified_receipts) and
            (verified.get("result") or {}).get("phone_confirmed_unsent_draft") is True)
        direct_finalized=(phone_policy_scoped and
            verified.get("status")=="completed" and
            snap.get("tool_execution_verified") is True and
            direct_action_receipts_consistent(verified_receipts) and
            (verified.get("result") or {}).get(
                "phone_direct_actions_finalized") is True)
        pinky_receipt=(verified.get("status")=="completed" and
                       snap.get("tool_execution_verified") is True and
                       isinstance(verified_receipts,list) and
                       any(isinstance(row,dict) and
                           isinstance(row.get("name"),str) and
                           row["name"].startswith("mcp__pinky_dafeiyu__phone_") and
                           row.get("receipt")=="success"
                           for row in verified_receipts))
        return {"status":verified["status"],"reply":reply["reply"],
                "session_id":self.projector.session_id,"task_id":task_id,
                "origin":"harness_verified_result","animation_id":item["id"],
                "native_facts_verified":obs.active,
                "tool_execution_verified":snap.get("tool_execution_verified") is True,
                "pinky_tool_execution_verified":bool(pinky_receipt),
                # A successful MCP call can be only connect+release or a
                # delegated task still running: never call that business done.
                "pinky_tool_stage":(
                    "read_only_search_recovered" if phone_search_recovered
                    else "read_only_search_verified" if phone_search_completed
                    else phone_tool_stage(verified_receipts)
                    if phone_intent else "none"),
                "pinky_readonly_search_recovered":bool(phone_search_recovered),
                "pinky_readonly_search_completed":bool(phone_search_completed),
                "pinky_delegation_state":delegation,
                "pinky_confirmed_launch_app":confirmed_launch,
                "pinky_confirmed_unsent_draft":bool(confirmed_unsent_draft),
                "pinky_direct_actions_finalized":bool(direct_finalized),
                "pinky_readonly_query_verified":bool(phone_readonly_query),
                "pinky_readonly_scope_verified":bool(phone_readonly_scoped),
                "pinky_policy_scope_verified":bool(phone_policy_scoped),
                "pinky_front_app_observed":bool(phone_front_app_observed),
                "pinky_screen_observed":bool(phone_screen_observed),
                "action":reply.get("action"),
                "audio_playback_verified":False}
