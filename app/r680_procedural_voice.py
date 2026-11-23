"""R680: structural, zero-model-call oral briefing for numbered procedures.

Preserve every concrete sequential action from a verified DSH response,
not a first/middle/last one-line extract. Never edit the actual conversation.
Use only when the user explicitly requests a step-by-step how-to.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

_STEP=re.compile(r"^\s*([1-9]|1[0-8])[.．、)]\s+(.{5,})$")
_HEADING=re.compile(r"^\s*\*\*[一二三四五六七八九十]{1,3}[、.．]\s*(.+?)\*\*\s*$")
_DETAIL=re.compile(r"步骤|制作|做法|流程|怎么做|如何做|教我|教程|详细|分步")
_EXACT=re.compile(r"逐字朗读|完整朗读|原文照读|一字不漏")
_UNSAFE=re.compile(r"密码|口令|授权|审批|转账|支付|删库|删除系统|格式化|急救|用药|剂量|处方|手术")
@dataclass(frozen=True)
class ProceduralSpeech:
    text:str
    steps:int
    sections:int
    source_chars:int

def _action(text:str)->str|None:
    value=re.sub(r"\*\*|__|[	 ]+",lambda m:"" if m.group(0) in ("**","__") else " ",text).strip(" 。；")
    # Take the complete first actionable sentence, not a random fact from
    # the middle and not a mid-number truncation.
    fragments=re.split(r"[。；]",value,maxsplit=1)
    first=fragments[0].strip()
    if len(first)>92:
        bounds=[i for i,c in enumerate(first[:76]) if c in "，、" and i>=38]
        if not bounds:return None
        first=first[:bounds[-1]].rstrip("，、 ")
    if len(first)<6 or len(first)>92:return None
    # Keep a directly adjacent safety warning or factual numeric option if
    # space allows. This prevents a clear procedure from erasing e.g.
    # "water must not overflow" while keeping the order source-grounded.
    if len(fragments)>1:
        second=re.split(r"[。；]",fragments[1],maxsplit=1)[0].strip(" ，。；")
        if (second and len(first)+len(second)+1<=92 and
            (re.search(r"不要|不能|切勿|别|必须|不得",second) or
             (re.search(r"[0-9]",second) and
              any(k in second for k in ("℃","g","克","秒","分钟","度"))))):
            first+="，"+second
    return first.strip(" ，。；")

def compile_procedure(reply:str,transcript:str)->ProceduralSpeech|None:
    if (not isinstance(reply,str) or not isinstance(transcript,str) or
        not 150<=len(reply)<=7500 or not _DETAIL.search(transcript) or
        _EXACT.search(transcript) or _UNSAFE.search(reply)):
        return None
    seq=[];section="";seen=set()
    in_code=False
    for raw in reply.splitlines():
        stripped=raw.strip()
        if stripped.startswith("```"):in_code=not in_code;continue
        if in_code or stripped.count("|")>=2:continue
        stage=_HEADING.match(stripped)
        if stage:
            title=re.split(r"[（(]",stage.group(1),maxsplit=1)[0].strip(" ：:")
            if 2<=len(title)<=18:section=title
            continue
        match=_STEP.match(stripped)
        if not match:continue
        idx=int(match.group(1))
        if idx in seen:return None  # No partial or duplicated instructions
        seen.add(idx)
        action=_action(match.group(2))
        if action is None:return None
        seq.append((idx,section,action))
    if (not 5<=len(seq)<=18 or
        [i for i,_,_ in seq]!=list(range(1,len(seq)+1))):
        return None
    sections=len({s for _,s,_ in seq if s})
    if sections<2 and len(seq)<6:return None
    chunks=[];previous=None
    for _,stage,action in seq:
        if stage and stage!=previous:
            chunks.append(stage+"：")
            previous=stage
        chunks.append(action.rstrip(" 。；")+"。")
    out="".join(chunks)
    # Completeness is more important than a short but unusable summary.
    # Never drop a numbered instruction just to satisfy a 180-char target.
    if not 110<=len(out)<=560 or len(out)>=len(reply)*.94:return None
    return ProceduralSpeech(out,len(seq),sections,len(reply))
