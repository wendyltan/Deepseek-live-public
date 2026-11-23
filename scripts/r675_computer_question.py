#!/usr/bin/env python3
"""R675 owner-only CUA permission question proxy to the exact current DSH turn.

Never prompts, answers or invokes tools on its own. The Mac UI must show
the exact native question/choice and obtain a human click before 'decide'.
"""
from __future__ import annotations
import json,os,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.r659_plugin_manager import DEFAULT_HOME
def official():
    from scripts.r18_h10_native_dialogue import read_private_token,stable_local_conversation_tab_id,official_bridge_token_path
    from app.dsh_p1_adapter import DshP1Adapter
    token_path=None
    for candidate in (DEFAULT_HOME/"secrets/deepseek-live-bridge.token",
                      DEFAULT_HOME/"secrets/bridge.token"):
        if candidate.is_file():
            token_path=candidate;break
    if token_path is None:token_path=official_bridge_token_path()
    return DshP1Adapter("http://127.0.0.1:3080",read_private_token(token_path)),stable_local_conversation_tab_id()
ID=re.compile(r"^[a-f0-9-]{16,128}$")
def perform(action,payload):
    if action not in ("status","decide"):raise ValueError("bad_action")
    a,tab=official()
    data={"conversation_id":a.conversation(tab)}
    if action=="decide":
        if not isinstance(payload,dict) or set(payload)!={"task_id","request_id","question_id","choice"}:
            raise ValueError("invalid_decision")
        for k in ("task_id","request_id","question_id"):
            if not isinstance(payload[k],str) or not 1<=len(payload[k])<=160:
                raise ValueError("invalid_decision_id")
        if not isinstance(payload["choice"],str) or not 1<=len(payload["choice"])<=96:
            raise ValueError("invalid_choice")
        data.update(payload)
        result=a._ok("computer-question/decide",data)
        return {"ok":result.get("submitted") is True,"submitted":result.get("submitted") is True}
    response=a._ok("computer-question/pending",data)
    q=response.get("pending")
    if q is None:return {"ok":True,"pending":None}
    if not isinstance(q,dict) or set(q)!={"task_id","request_id","question_id","question","detail","header","options"}:
        raise ValueError("malformed_question")
    if (any(not isinstance(q[k],str) or len(q[k])>n for k,n in (
        ("task_id",160),("request_id",160),("question_id",160),
        ("question",350),("detail",1600),("header",100))) or
        not isinstance(q["options"],list) or not 2<=len(q["options"])<=5 or
        any(not isinstance(c,str) or not 1<=len(c)<=96 for c in q["options"])):
        raise ValueError("malformed_question")
    return {"ok":True,"pending":q}
if __name__=="__main__":
    try:
        action=sys.argv[1] if len(sys.argv)==2 else ""
        payload={}
        if action=="decide":
            raw=sys.stdin.buffer.read(4097)
            if len(raw)>4096:raise ValueError("input_oversize")
            payload=json.loads(raw)
        answer=perform(action,payload)
        print(json.dumps(answer,ensure_ascii=False,separators=(",",":")))
    except Exception:
        print(json.dumps({"ok":False,"error":"question_unavailable"}))
        raise SystemExit(2)
