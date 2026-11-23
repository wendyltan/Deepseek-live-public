"""R675 read-only, same-session reconstruction of verified DSH conversation display.

The private native journal is the last-resort historical source; its original
bytes are never edited. Only user text and completed assistant text are
extracted; tool arguments, hidden reasoning and transient approval details are
never projected into the Mac chat history.
"""
from __future__ import annotations
import json
import os
import re
import stat
import subprocess
from pathlib import Path

MAX_JOURNAL_BYTES=32_000_000
MAX_DECOMPRESSED_BYTES=16_000_000
MAX_TURNS=120
SID=re.compile(r"^[a-f0-9-]{36}$")
ORIGINS={"model","preset","memory","clock","weather","weather_unavailable","failed"}

def _default_dsh_home()->Path:
    env=os.environ.get("DAFEIYU_HOME","").strip()
    if env:return Path(env).expanduser()
    base=Path.home()/"Library/Application Support/Deepseek-live"
    for name in ("dsh-home-production-r645","my-companion","companion-public"):
        cand=base/name
        if (cand/"profiles/web/package.json").is_file():return cand
    return base/"my-companion"

def native_session_file(sid,*,home=None,project=None):
    if not isinstance(sid,str) or not SID.fullmatch(sid):return None
    home=home or _default_dsh_home()
    project=project or Path(__file__).resolve().parents[1]
    # Canonical DSH session location is scoped to the project and owner.
    key="--"+str(project.resolve()).strip("/").replace("/","-")+"--"
    p=home/"sessions"/key/sid/"session.v4.jsonl.zstd"
    try:
        st=p.lstat()
        if (not stat.S_ISREG(st.st_mode) or p.is_symlink() or
            st.st_uid != os.getuid() or st.st_mode&0o077 or
            not 50<=st.st_size<=MAX_JOURNAL_BYTES):
            return None
        return p
    except OSError:return None

def _user_text(source):
    if not isinstance(source,dict) or not isinstance(source.get("source"),dict) or source["source"].get("kind")!="user":return ""
    parts=source.get("content")
    if not isinstance(parts,list) or len(parts)>12:return ""
    text="".join(x.get("text","") for x in parts
        if isinstance(x,dict) and x.get("type")=="text"
        and isinstance(x.get("text"),str))
    if "本次用户原话：" in text:
        text=text.rsplit("本次用户原话：",1)[-1]
    return text.strip()[:400]

def recover_events(rows,*,existing=()):
    """Pure, testable merge. Never include tool/reasoning content."""
    if not isinstance(rows,list) or len(rows)>15000:return []
    current=None
    by_turn={}
    aborted=set()
    completed=set()
    for row in rows:
        if not isinstance(row,dict):continue
        event=row.get("type")
        d=row.get("data")
        if not isinstance(d,dict):continue
        if event=="turn/start" and type(d.get("turn")) is int:
            current=d["turn"]
            if 1<=current<=50000:by_turn.setdefault(current,{"user":"","answer":""})
        elif event=="user/message" and current in by_turn:
            if not by_turn[current]["user"]:
                by_turn[current]["user"]=_user_text(d)
        elif event=="assistant/message":
            index=d.get("turn")
            if type(index) is not int or index not in by_turn:continue
            message=d.get("message")
            if not isinstance(message,dict) or message.get("role")!="assistant":continue
            parts=message.get("content")
            if not isinstance(parts,list) or len(parts)>32:continue
            answer="".join(x["text"] for x in parts if
                isinstance(x,dict) and x.get("type")=="text" and
                isinstance(x.get("text"),str))
            if answer.strip():by_turn[index]["answer"]=answer.strip()[:900]
        elif event=="turn/end" and type(d.get("turn")) is int:
            reason=d.get("reason")
            if isinstance(reason,dict) and reason.get("kind")=="completed":
                completed.add(d["turn"])
            elif isinstance(reason,dict) and reason.get("kind")=="aborted":
                aborted.add(d["turn"])
    known=[]
    for item in existing:
        if (isinstance(item,dict) and item.get("origin") in ORIGINS and
            isinstance(item.get("user"),str) and
            isinstance(item.get("assistant"),str)):
            known.append(dict(item))
    used=set()
    result=[]
    for index in sorted(by_turn):
        row=by_turn[index]
        user=row["user"]
        if not user:continue
        answer=row["answer"]
        match=None
        for k,item in enumerate(known):
            if k in used or item["user"]!=user:continue
            if index in completed and answer and item["assistant"]==answer:
                match=k;break
            if index in aborted and item["origin"]=="failed":
                match=k;break
        if match is not None:
            result.append(known[match]);used.add(match)
        elif index in completed and answer:
            result.append({"user":user,"assistant":answer,"origin":"model"})
    # Preserve local clock/memory/weather/failed turns, not represented by DSH.
    for k,item in enumerate(known):
        if k not in used and not any(
            x["user"]==item["user"] and x["assistant"]==item["assistant"]
            for x in result):
            result.append(item)
    return result[-MAX_TURNS:]

def recover_native_history(sid,*,existing=(),home=None,project=None):
    src=native_session_file(sid,home=home,project=project)
    if src is None:return []
    proc=None
    try:
        proc=subprocess.Popen(["/opt/homebrew/bin/zstd","-dc",str(src)],
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        payload=proc.stdout.read(MAX_DECOMPRESSED_BYTES+1)
        if len(payload)>MAX_DECOMPRESSED_BYTES:return []
        if proc.wait(timeout=12)!=0:return []
        lines=payload.splitlines()
        if not lines or len(lines)>15000:return []
        rows=[json.loads(line) for line in lines]
        if rows[0].get("type")!="session" or rows[0].get("id")!=sid:
            return []
        return recover_events(rows,existing=existing)
    except (OSError,ValueError,TypeError,subprocess.TimeoutExpired):
        return []
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill();proc.wait()
