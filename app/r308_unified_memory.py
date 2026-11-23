"""Bounded local E1b bridge. All production reads/writes use one owner vault.

Only the current authenticated ESP32 verified-STT service can invoke remember;
Node independently checks source-scoped voice user preference and strict fact
shape. This code never persists raw transcripts or calls models.
"""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
# The production USB LaunchAgent deliberately runs from an isolated private
# Python runtime. Its Node E1b owner remains the canonical project vault;
# never create a second memory store under the private runtime copy.
if not (ROOT/"scripts/r308_unified_memory.mjs").is_file():
    ROOT=Path(".")
SCRIPT=ROOT/"scripts/r308_unified_memory.mjs"
FLAG=Path.home()/"Library/Application Support/Deepseek-live/companion-native/r308-unified-active.json"
NODE=Path("/opt/homebrew/bin/node")

def enabled(flag:Path=FLAG)->bool:
    try:
        if flag.is_symlink() or not flag.is_file() or flag.stat().st_mode&0o077:
            return False
        b=flag.read_bytes()
        return len(b)<512 and json.loads(b)=={"schema":1,"canonical":"e1b_owner_vault"}
    except (OSError,ValueError,TypeError):return False

def _call(action,payload,*,runner=subprocess.run,timeout=6):
    if action not in {"lookup","remember","status","remove"} or not isinstance(payload,dict):
        return None
    try:
        raw=json.dumps(payload,ensure_ascii=False,separators=(",",":"))
        if len(raw.encode())>4096:return None
        p=runner([str(NODE),str(SCRIPT),action],cwd=ROOT,input=raw,
             capture_output=True,text=True,timeout=timeout,check=False)
        if p.returncode!=0 or len(p.stdout)>24576 or not p.stdout.startswith("R308_UNIFIED_RESULT "):
            return None
        x=json.loads(p.stdout[len("R308_UNIFIED_RESULT "):])
        if isinstance(x,dict) and x.get("ok") is True:return x
    except (OSError,ValueError,TypeError,subprocess.TimeoutExpired):
        pass
    return None

def remember_verified(fact,*,runner=subprocess.run):
    if not enabled() or not isinstance(fact,dict):
        return "failed"
    x=_call("remember",{"fact":fact},runner=runner)
    value=x.get("status") if x else None
    return value if value in {"saved","already_saved","disabled"} else "failed"

def facts_for_query(query,*,runner=subprocess.run):
    if not enabled() or not isinstance(query,str) or not 1<=len(query)<=600:
        return []
    x=_call("lookup",{"query":query},runner=runner)
    facts=x.get("facts") if x else None
    if not isinstance(facts,list) or len(facts)>4:
        return []
    if any(not isinstance(s,str) or not s or len(s)>512 for s in facts):
        return []
    unique=[]
    for x in facts:
        if x not in unique and len(json.dumps([*unique,x],ensure_ascii=False))<=700:
            unique.append(x)
    return unique
