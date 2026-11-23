"""Verified ESP32 transcript -> explicit E1b lookup, never automatic memory.

This is optional, user-requested fact retrieval. No Mac mic, external model,
ReMe, or background learning. An empty vault must remain empty.
"""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/r22_explicit_memory_search.mjs'
PROMPT=re.compile(r'^(?:大肥鱼[,，]?\s*)?(?:你还记得|你记得|查一下我保存的记忆[：:]?|查找我保存的记忆[：:]?)(.{2,100})[吗？?。！!]*$')
class MemoryLookupUnavailable(RuntimeError):pass

def explicit_query(transcript,*,verified_stt=False):
    if verified_stt is not True or not isinstance(transcript,str):return None
    match=PROMPT.fullmatch(transcript.strip())
    if not match:return None
    query=match[1].strip('吗？?。！!，, ')
    if len(query)<2 or len(query)>100:return None
    return query

def lookup_explicit_memory(query,*,runner=subprocess.run):
    if not isinstance(query,str) or not 2<=len(query)<=100:
        raise MemoryLookupUnavailable('explicit_memory_query_invalid')
    try:
        proc=runner(['node',str(SCRIPT),query],capture_output=True,text=True,
                    check=False,timeout=6,cwd=ROOT)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise MemoryLookupUnavailable('explicit_memory_reader_unavailable') from exc
    if proc.returncode!=0 or len(proc.stdout)>8192:
        raise MemoryLookupUnavailable('explicit_memory_reader_failed')
    try:reply=json.loads(proc.stdout)
    except (TypeError,ValueError) as exc:
        raise MemoryLookupUnavailable('explicit_memory_reply_invalid') from exc
    if (not isinstance(reply,dict) or reply.get('schema')!=1 or
        reply.get('origin')!='explicit_e1b_user_facts_only' or
        reply.get('auto_extraction') is not False or
        not isinstance(reply.get('items'),list) or len(reply['items'])>3):
        raise MemoryLookupUnavailable('explicit_memory_provenance_invalid')
    for item in reply['items']:
        if (not isinstance(item,dict) or item.get('source')!='user_explicit' or
            not isinstance(item.get('text'),str) or not item['text'].strip() or
            len(item['text'])>1024):
            raise MemoryLookupUnavailable('explicit_memory_item_unverified')
    return reply

def short_spoken_memory(result):
    items=result['items']
    if not items:
        return '我查过已获你确认的本地记忆，目前没有找到相关记录。'
    # Limit spoken private facts without truncating other unrelated entries.
    return '这是你之前主动确认保存的记忆：'+'；'.join(x['text'][:120] for x in items[:2])
