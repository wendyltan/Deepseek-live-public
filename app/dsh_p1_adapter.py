"""Optional, single-owner P1 -> project-owned native DSH Bridge adapter.

No direct DeepSeek REST requests, key copying, generic shell or external
desktop dependency. A submitted native turn is never automatically repeated.
"""
from __future__ import annotations
import ipaddress
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ID = re.compile(r"^[a-f0-9]{32}$")
TERMINAL = frozenset(("answered", "completed", "failed", "cancelled"))


class DshUnavailable(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def enabled():
    return os.getenv("P1_DSH_BRIDGE_ENABLED", "") == "1"


class DshP1Adapter:
    def __init__(self, endpoint=None, token=None, transport=None, timeout=65):
        endpoint = endpoint if endpoint is not None else os.getenv("P1_DSH_BRIDGE_URL", "")
        token = token if token is not None else os.getenv("P1_DSH_BRIDGE_TOKEN", "")
        url = urllib.parse.urlsplit(endpoint)
        try:
            host = ipaddress.ip_address(url.hostname or "")
            port = url.port
        except ValueError:
            raise DshUnavailable("DSH 连接地址必须是本机回环地址和合法端口") from None
        if (url.scheme != "http" or not host.is_loopback or
                not (1 <= (port or 0) <= 65535) or
                url.username or url.password or url.path not in ("", "/") or
                url.query or url.fragment or port in (8765, 8878, 8879)):
            raise DshUnavailable("DSH 连接地址不安全或与现有服务冲突")
        if not isinstance(token, str) or not 32 <= len(token) <= 256:
            raise DshUnavailable("DSH 专用连接密钥未配置")
        self.url = f"http://{url.hostname}:{port}" if host.version == 4 else f"http://[{url.hostname}]:{port}"
        self.token = token
        self.transport = transport or urllib.request.build_opener(_NoRedirect()).open
        # The opt-in native approval answerer may await a human for up to 120s.
        # The P1 chat transport must outlive that bounded approval wait so the
        # final native deny/abort can be observed rather than reported unknown.
        self.timeout = max(timeout, 150) if os.getenv('P1_DSH_APPROVAL_ENABLED') == '1' else timeout

    def _call(self, path, params):
        data = json.dumps({"protocolVersion": 1, **params}, ensure_ascii=False).encode("utf8")
        request = urllib.request.Request(
            self.url + "/dsh-live-bridge/" + path, data=data,
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
            method="POST")
        try:
            with self.transport(request, timeout=8) as response:
                body = response.read(64000)
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ValueError("not an object")
                return result
        except urllib.error.HTTPError as exc:
            # Exact 404 is useful only for a not-yet-bound conversation.
            if exc.code == 404 and path == "session":
                return {"ok": False, "error": "unknown_conversation"}
            raise DshUnavailable("DSH 服务拒绝了请求（HTTP %s）" % exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError,
                json.JSONDecodeError):
            raise DshUnavailable("DSH 本地服务无法确认结果，请检查 Bridge 状态") from None

    def _ok(self, path, params):
        data = self._call(path, params)
        if not data.get("ok"):
            raise DshUnavailable("DSH 未完成请求：" + str(data.get("error", "unknown"))[:75])
        return data

    def models(self):
        data = self._ok("models", {})
        models = data.get("models")
        if not isinstance(models, list) or not models or any(
                not isinstance(m, dict) or not re.fullmatch(r"[\w.-]{1,80}", m.get("id", ""))
                for m in models):
            raise DshUnavailable("DSH 模型列表无效")
        return {"models": models, "default": data["default"],
                "source": "DSH scoped model resolution"}

    @staticmethod
    def conversation(tab_id):
        if not isinstance(tab_id, str) or not ID.fullmatch(tab_id):
            raise DshUnavailable("无效的浏览器会话")
        return "p1_" + tab_id

    def inspect(self, tab_id):
        return self._call("session", {"conversation_id": self.conversation(tab_id)})

    def ensure(self, tab_id):
        return self._ok("bind", {"conversation_id": self.conversation(tab_id)})

    def selected(self, tab_id):
        data = self.inspect(tab_id)
        if not data.get("ok"):
            return None
        return data.get("selected", {}).get("model")

    def switch(self, tab_id, model):
        self.ensure(tab_id)
        response = self._ok("model", {
            "conversation_id": self.conversation(tab_id), "model": model})
        effective = response.get("selected", {}).get("model")
        if effective != model:
            raise DshUnavailable("DSH 未确认模型切换")
        return effective

    def phone_capabilities(self, tab_id):
        """Free, same-bound Agent-scoped Pinky tool check before paid submit."""
        data=self._ok("phone-capabilities",{
            "conversation_id":self.conversation(tab_id)})
        count=data.get("pinky_tool_count")
        if (data.get("scoped_checked") is not True or
            data.get("agent_tools_native") is not True or
            data.get("pinky_dafeiyu_visible") is not True or
            type(count) is not int or not 2<=count<=64):
            raise DshUnavailable("R538 手机工具暂不可用，不发起本轮模型任务")
        return {"verified":True,"tool_count":count}

    def pinky_policy_capabilities(self, tab_id):
        """Only current native Agent scope, no model/phone operation."""
        data=self._ok("phone-policy-capabilities",{
            "conversation_id":self.conversation(tab_id)})
        count=data.get("pinky_tool_count")
        if (data.get("agent_tools_native") is not True or
            data.get("pinky_policy_available") is not True or
            data.get("foreground_screen_read_available") is not True or
            data.get("app_launch_available") is not True or
            data.get("approval_decisions_bypassed") is not False or
            type(count) is not int or not 20<=count<=64):
            raise DshUnavailable("Pinky 完整原生工具未就绪，尚未发起本轮任务")
        return {"verified":True,"tool_count":count,
                "foreground_screen_read_available":True,
                "pinky_rules_preserved":True}

    def search_status(self, tab_id):
        data = self.inspect(tab_id)
        if not data.get("ok"):
            raise DshUnavailable("DSH 会话尚未绑定")
        # Persisted metadata is not an active Agent scope. Bind/resume
        # without a model request before reporting native tool availability.
        if data.get("pending_resume") is True:
            data = self.ensure(tab_id)
        return {"supported": data.get("search_supported") is True,
                "enabled": data.get("search_enabled") is True,
                "source": "dsh-session"}

    def switch_search(self, tab_id, enabled):
        if type(enabled) is not bool:
            raise DshUnavailable("联网搜索开关必须为布尔值")
        self.ensure(tab_id)
        data = self._ok("search", {
            "conversation_id": self.conversation(tab_id), "enabled": enabled})
        if data.get("supported") is not True or data.get("enabled") is not enabled:
            raise DshUnavailable("Harness 未确认联网搜索开关")
        return {"supported": True, "enabled": enabled, "source": "dsh-session"}

    def approval_pending(self, tab_id):
        # No Bridge credentials, text or tool arguments reach the browser.
        data=self._ok("approval/pending", {
            "conversation_id": self.conversation(tab_id)})
        pending=data.get("pending")
        if pending is not None:
            if (not isinstance(pending,dict) or
                not all(isinstance(pending.get(k),str) for k in (
                    "task_id","request_id","tool","description","scope")) or
                pending["tool"]!="dsh_live_approval_probe" or
                len(pending["description"])>200):
                raise DshUnavailable("审批请求来源或范围无效")
        return {"pending":pending}

    def approval_decide(self, tab_id, task_id, request_id, decision):
        if not isinstance(task_id,str) or not re.fullmatch(r"[a-f0-9-]{36}",task_id):
            raise DshUnavailable("审批任务标识无效")
        if not isinstance(request_id,str) or not re.fullmatch(r"[a-f0-9-]{36}",request_id):
            raise DshUnavailable("审批请求标识无效")
        if decision not in ("allowed-once","rejected","cancelled"):
            raise DshUnavailable("审批决定无效")
        result=self._ok("approval/decide", {
            "conversation_id":self.conversation(tab_id),
            "task_id":task_id, "request_id":request_id,"decision":decision})
        if not result.get("submitted"):
            raise DshUnavailable("Harness 尚未收到审批决定")
        return {"submitted":True, "native_confirmation_pending":True}

    def end(self, tab_id):
        # Ends the active Session; physical native-history erasure remains
        # pending and must never be presented to users as completed.
        return self._ok("end", {"conversation_id": self.conversation(tab_id)})

    def chat(self, tab_id, prompt, visual_observer=None, *,
             phone_read_only=False, phone_policy=False):
        # One native task_id per turn; no blind retry if /submit timed out.
        self.ensure(tab_id)
        turn_id = uuid.uuid4().hex
        start = time.monotonic()
        if (type(phone_read_only) is not bool or
                type(phone_policy) is not bool or
                (phone_read_only and phone_policy)):
            raise DshUnavailable("手机操作权限范围标记无效")
        response = self._ok("submit", {
            "conversation_id": self.conversation(tab_id),
            "turn_id": turn_id, "prompt": prompt,
            **({"phone_read_only":True} if phone_read_only else {}),
            **({"phone_policy":"pinky"} if phone_policy else {})})
        task_id = response.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise DshUnavailable("DSH 未返回任务 ID；不能自动重试")
        if visual_observer is not None:
            try:
                visual_observer.started(response)
            except Exception:
                # Visual failure cannot resubmit or change the model/tool result.
                try: visual_observer.unavailable()
                except Exception: pass
        native_session = response.get("session_id")
        last_visual_revision = -1
        def observe():
            nonlocal last_visual_revision
            if visual_observer is None or not visual_observer.active:
                return
            try:
                # Reuse the existing scoped Bearer + loopback transport.
                facts = self._ok("companion-facts", {
                    "task_id": task_id, "session_id": native_session,
                    "after_revision": last_visual_revision})
                changes = facts.get("changes")
                if not isinstance(changes, list) or len(changes) > 64:
                    raise DshUnavailable("DSH视觉增量事件不可用")
                for item in changes:
                    if (not isinstance(item, dict) or
                            type(item.get("revision")) is not int or
                            item["revision"] != last_visual_revision + 1):
                        raise DshUnavailable("DSH视觉事件序号缺失")
                    visual_observer.facts(item)
                    last_visual_revision = item["revision"]
                if facts.get("revision") != last_visual_revision:
                    raise DshUnavailable("DSH视觉事件有缺口")
            except Exception:
                try: visual_observer.unavailable()
                except Exception: pass
        while True:
            observe()
            status = response.get("status")
            # Never narrate continued work once this exact native turn is
            # already terminal, even if its final facts just arrived.
            if (status not in TERMINAL and visual_observer is not None and
                getattr(visual_observer,"active",False)):
                try:visual_observer.tick()
                except (AttributeError,ValueError,RuntimeError):pass
            if status in TERMINAL:
                if status in ("answered", "completed"):
                    result = response.get("result") or {}
                    reply = result.get("text")
                    if not isinstance(reply, str) or not reply.strip():
                        raise DshUnavailable("DSH 任务结束但未取得文本，任务 " + task_id)
                    session = self.inspect(tab_id)
                    model = (session.get("last_request") or
                             session.get("selected") or {}).get("model")
                    return {"reply": reply.strip()[:5000], "model": model,
                            "task_id": task_id, "status": status,
                            "reasoning_observed": result.get("reasoning_observed")
                                if type(result.get("reasoning_observed")) is bool else None,
                            "execution_verified": bool(result.get("execution_verified", False))}
                # A native refusal/cancellation is an expected user choice,
                # not a transport failure. These exact codes originate only from
                # validated native approval/decided events after terminal turn.
                # Never surface a plausible assistant/tool result as executed.
                denied = {
                    "native_approval_rejected": ("approval_rejected",
                        "已拒绝本次工具授权；该工具未获准执行。"),
                    "native_approval_cancelled": ("approval_cancelled",
                        "已取消本次工具授权；该工具未获准执行。"),
                }
                outcome = denied.get(response.get("failure")) if status == "failed" else None
                if outcome and response.get("result") is None:
                    session = self.inspect(tab_id)
                    model = (session.get("last_request") or
                             session.get("selected") or {}).get("model")
                    return {"reply": outcome[1], "model": model,
                            "task_id": task_id, "status": status,
                            "action": outcome[0], "execution_verified": False}
                # R584: one recovered navigation tap is NOT a successful
                # shopping/business outcome, but neither should we say the
                # entire later sequence failed. The proof comes only from
                # the original producer-correlated Bridge tool events.
                if (phone_policy and status=="failed" and
                    response.get("failure")=="native_tool_failed" and
                    response.get("result") is None and
                    response.get("phone_recovery_state")==
                        "navigation_retried_final_unconfirmed" and
                    isinstance(response.get("tools"),list)):
                    return {"reply":("本鱼中途有一次点击失败，后来重新点击并继续执行了。"
                                      "不过最后一步后的页面还没有再次核对，所以本鱼暂时"
                                      "不把最终结果说成失败或成功。请按手机当前页面确认，"
                                      "先别重复操作。"),
                            "model":None,"task_id":task_id,"status":"failed",
                            "action":"phone_recovered_unverified",
                            "execution_verified":False}
                # R541: if this EXACT native Pinky turn is terminal failed,
                # some phone tools succeeded and at least one failed, do not
                # turn that into 129s silence + ESP stage11 reason3. Preserve
                # FAILED outcome and forbid any 'cart succeeded' claim; the
                # user must inspect the phone, not blindly resubmit.
                # Other DSH failures and missing/uncertain receipts still fail.
                rows=response.get("tools")
                if (phone_policy and status=="failed" and
                    response.get("failure")=="native_tool_failed" and
                    response.get("result") is None and
                    isinstance(rows,list) and 1<=len(rows)<=128 and
                    all(isinstance(x,dict) and
                        isinstance(x.get("name"),str) and
                        x["name"].startswith("mcp__pinky_dafeiyu__phone_") and
                        x.get("outcome") in ("success","failed") for x in rows) and
                    any(x["outcome"]=="success" for x in rows) and
                    any(x["outcome"]=="failed" for x in rows)):
                    return {"reply":"本鱼操作手机时有一步失败，部分步骤可能已经执行，但无法确认最终结果。请看一下手机当前页面，先别重复操作。",
                            "model":None,"task_id":task_id,"status":"failed",
                            "action":"phone_partial_failure",
                            "execution_verified":False}
                # R542: an initial phone_connect can be refused by a stale
                # scoped guard, a locked/unavailable phone or Pinky's own
                # policy. Such a VERIFIED terminal native failure must still
                # produce a truthful spoken terminal, not ESP stage11 reason3.
                # Never infer an actual phone connection or silent retry.
                if (phone_policy and status=="failed" and
                    response.get("failure")=="native_tool_failed" and
                    response.get("result") is None and
                    isinstance(rows,list) and 1<=len(rows)<=128 and
                    all(isinstance(x,dict) and
                        isinstance(x.get("name"),str) and
                        x["name"].startswith("mcp__pinky_dafeiyu__phone_") and
                        x.get("outcome") in ("success","failed") for x in rows) and
                    any(x["outcome"]=="failed" for x in rows)):
                    if (len(rows)==1 and
                        rows[0]["name"]=="mcp__pinky_dafeiyu__phone_connect" and
                        rows[0]["outcome"]=="failed"):
                        message=("本鱼没能建立手机连接，所以这次没能开始操作。"
                                 "请检查Pinky连接状态和手机是否解锁，再决定要不要重试。")
                        action="phone_connect_failed"
                    else:
                        message=("本鱼这次手机任务没能完成，"
                                 "没有确认手机操作成功，请看一下实际界面，先别重复提交。")
                        action="phone_tool_failed"
                    return {"reply":message,"model":None,"task_id":task_id,
                            "status":"failed","action":action,
                            "execution_verified":False}
                # R675: the exact native Mac CUA task may fail after a User
                # Questions refusal/abort. This must still yield a truthful
                # spoken terminal and a FAILED history bubble; no new submit,
                # no claim that earlier native steps were rolled back.
                if (status=="failed" and response.get("result") is None and
                    response.get("failure")=="native_tool_failed" and
                    isinstance(rows,list) and 1<=len(rows)<=128 and
                    all(isinstance(t,dict) and t.get("name")=="cua" and
                        t.get("outcome") in ("success","failed") for t in rows) and
                    any(t["outcome"]=="failed" for t in rows)):
                    return {"reply":("本鱼这轮 Mac 电脑操作有一步失败，"
                                     "最终窗口结果没有得到完整核实。"
                                     "这不代表电脑操作权限开关没打开；"
                                     "先前已经执行的步骤不会自动撤销。"),
                            "model":None,"task_id":task_id,
                            "status":"failed","action":"computer_tool_failed",
                            "execution_verified":False}
                # Bridge reports a bounded machine error code. Never expose
                # raw tool messages, prompts, private thought or credentials.
                failure=response.get("failure")
                code=(failure if isinstance(failure,str) and
                      re.fullmatch(r"[a-z][a-z0-9_]{0,47}",failure) else "unspecified")
                raise DshUnavailable("DSH 执行%s reason=%s；原任务 %s（不要重复提交）"
                                     % (status,code,task_id))
            # R672: native CUA can hang after earlier successful tool calls.
            # Bound only the confirmed in-flight CUA tool, never a phone turn,
            # pending human approval, or an unrelated long DSH answer. The
            # hardware's pre-audio timeout is 190s, so settle before that.
            if (time.monotonic()-start >= 120 and status=="running" and
                isinstance(response.get("tools"),list) and
                any(isinstance(t,dict) and t.get("name")=="cua" and
                    t.get("outcome")=="pending" for t in response["tools"])):
                # One native cancellation request; no replay, shell kill or
                # false declaration that earlier CUA actions were undone.
                try:
                    self._ok("cancel", {"task_id":task_id})
                    for _ in range(8):
                        time.sleep(0.4)
                        settled=self._ok("result", {"task_id":task_id})
                        if settled.get("status") in TERMINAL:
                            break
                    if settled.get("status")=="cancelled":
                        return {"reply":("本鱼查看 Mac 窗口时等待太久，已取消这轮任务。"
                                         "此前部分步骤可能已执行，但最终结果没有确认，"
                                         "请勿直接重复操作。"),
                                "model":None,"task_id":task_id,
                                "status":"cancelled",
                                "action":"computer_timeout_cancelled",
                                "execution_verified":False}
                except DshUnavailable:
                    pass
                raise DshUnavailable("Mac CUA 超时，已请求终止但原任务结局未确认：%s；不要重复提交"%task_id)
            if time.monotonic() - start >= self.timeout:
                raise DshUnavailable("DSH 仍在执行或状态不明，任务 %s；请先查询原任务，勿再次提交" % task_id)
            time.sleep(0.3)
            response = self._ok("result", {"task_id": task_id})


class SpeechOnlyDshP1Adapter(DshP1Adapter):
    """One isolated Flash text-only native Agent. Never use ordinary /bind.

    Uses the same trusted localhost Bridge transport and owner-only token,
    but binds a separate model-fixed Session with empty tools/monotonic guard.
    """
    @staticmethod
    def conversation(tab_id):
        if not isinstance(tab_id,str) or not ID.fullmatch(tab_id):
            raise DshUnavailable("speech_session_id_invalid")
        return "speech_" + tab_id

    def capabilities(self):
        data=self._ok("speech-capabilities",{})
        if (data.get("model")!="deepseek-flash" or
                data.get("tools_denied") is not True):
            raise DshUnavailable("speech_isolated_capability_unverified")
        return True

    def ensure(self,tab_id):
        self.capabilities()
        data=self._ok("speech-bind",{"conversation_id":self.conversation(tab_id)})
        if (data.get("speech_only") is not True or
            data.get("tools_denied") is not True or
            (data.get("selected") or {}).get("model") != "deepseek-flash"):
            raise DshUnavailable("speech_scope_or_flash_model_unverified")
        return data

    def switch(self,tab_id,model):
        raise DshUnavailable("speech_model_is_fixed")

    def chat(self,tab_id,prompt,visual_observer=None):
        if visual_observer is not None:
            raise DshUnavailable("speech_scope_cannot_observe_private_dsh")
        result=super().chat(tab_id,prompt,visual_observer=None)
        if (result.get("status")!="answered" or
            result.get("model")!="deepseek-flash" or
            result.get("execution_verified") is not False):
            raise DshUnavailable("speech_result_must_be_text_only_verified")
        return result
