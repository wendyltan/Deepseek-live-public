"""R681: source-grounded spoken briefings for hierarchical procedures and file facts.

Source text/DSH journal are immutable. A HOW-TO with independently numbered
sections needs an ordered, complete operational narrative, not a random
opening/middle/tail extract. File facts should never read absolute paths.
No model calls, hidden tool operations or topic-specific recipe templates.
"""
from __future__ import annotations
from dataclasses import dataclass
import os
import re
from pathlib import PurePosixPath

_DETAIL=re.compile(r"步骤|制作|做法|流程|怎么做|如何做|教我|教程|详细|分步")
_EXACT=re.compile(r"逐字朗读|完整朗读|原文照读|一字不漏")
_SENSITIVE=re.compile(r"密码|口令|授权|审批|转账|支付|删库|删除系统|格式化|急救|用药|剂量|处方|手术")
_HEADING=re.compile(r"^\s{0,3}#{1,6}\s*(?:[一二三四五六七八九十0-9]{1,3}[、.．]\s*)?(.+)$")
_STEP=re.compile(r"^\s*([1-9]|1[0-8])[.．、)）]\s+(.{3,})$")
_TABLE=re.compile(r"^\s*\|(.+)\|\s*$")
_PATH=re.compile(r"(?<![\w/])/(?:Users|Volumes|home|private|tmp|Library|Applications|opt|var)(?:/[A-Za-z0-9_.+%\u3400-\u9fff-]+){1,15}")
_NAME=re.compile(r"`([\u3400-\u9fff][^`/\r\n]{1,80}\.(?:md|txt|pdf|docx|xlsx|csv))`",re.I)
_WHITESPACE=re.compile(r"[ \t]+")
_HAS_QUANTITY=re.compile(r"\d|[一二三四五六七八九十]克")
_PRIORITY=re.compile(r"停|完成|不要|不能|别|放下|移开|结束|关掉")
_COMMA="，、"
_ENDS="。；"

@dataclass(frozen=True)
class StructuredVoice:
    text:str
    kind:str
    source_chars:int
    steps:int
    sections:int

def _clean(raw:str)->str:
    x=re.sub(r"\*\*|__|`","",raw).strip()
    return _WHITESPACE.sub(" ",x).strip(" \t：:，。；")

def _clause(raw:str,limit:int)->str:
    x=_clean(raw)
    if not x:return ""
    # Keep source meaning without cutting midway through a measurement.
    x=re.split(r"[。；]",x,1)[0].strip(" ，；。")
    if len(x)<=limit:return x
    bounds=[i for i,c in enumerate(x[:limit]) if c in _COMMA
            and i>=max(12,limit//2)]
    return x[:bounds[-1]].strip(" ，、") if bounds else ""

def _action(raw:str,children:list[str],limit:int)->str:
    x=_clean(raw)
    if not x:return ""
    # A sentence like "grinder: this is important. First adjust it..."
    # is an introduction, not a usable instruction. Prefer the *next*
    # verified actionable sentence when the first one has no imperative.
    pieces=re.split(r"[。；]",x,2)
    if len(pieces)>=2 and re.search(r"这是.{0,12}(?:关键|重点|核心)|主要是",pieces[0]):
        if re.search(r"先|再|把|用|调|开|磨|压|称|放|冲|搅",pieces[1]):
            x=x.replace(pieces[0]+"。","",1).replace(pieces[0]+"；","",1)
    head=_clause(x,limit)
    if not head:return ""
    # If a numbered step has only a label/title, its indented bullet
    # statements hold the actual operation; keep first observed action plus
    # a measurement-backed termination instruction.
    short_title=(x.endswith(("：",":")) or len(x)<=20 or
                 (len(head)<=24 and not _HAS_QUANTITY.search(head)))
    if short_title and children:
        bullet=[_clause(v,max(32,limit-8)) for v in children]
        bullet=[v for v in bullet if v]
        if bullet:
            extra=bullet[0]
            terminal=next((v for v in bullet[1:]
                           if _PRIORITY.search(v) and _HAS_QUANTITY.search(v)),
                          None)
            head=extra if x.endswith(("：",":")) else (head+"，"+extra)
            if terminal and terminal!=extra:
                head=head.rstrip(" ，")+"，"+terminal
    # The original direct main clause can contain "start and stop" in
    # separate sentences. Explicit stop/negation is not incidental.
    trailing=re.split(r"[。；]",x,2)
    if len(trailing)>1:
        second=_clause(trailing[1],limit)
        if second and _PRIORITY.search(second) and len(head)+len(second)+1<=limit+20:
            head+="，"+second
    return head.strip(" ，、。；")

def _sections(source:str):
    sections=[]
    current=None
    inside_code=False
    for raw in source.splitlines():
        s=raw.strip()
        if s.startswith("```"):inside_code=not inside_code;continue
        if inside_code or not s:continue
        m=_HEADING.match(s)
        if m:
            name=_clean(m.group(1))
            if 2<=len(name)<=40:
                current={"name":name,"steps":[],"table":[]}
                sections.append(current)
            continue
        if current is None:continue
        m=_STEP.match(s)
        if m:
            current["steps"].append({"index":int(m.group(1)),
                                     "title":m.group(2),"children":[]})
            continue
        t=_TABLE.match(s)
        if t:
            cells=[_clean(v) for v in t.group(1).split("|")]
            if (len(cells)>=2 and cells[0] and cells[1] and
                not all(re.fullmatch("[-:+ ]+",v or "-") for v in cells)):
                current["table"].append(cells)
            continue
        if s.startswith(("-", "*")) and current["steps"]:
            # Nested bullet detail, not a brand new numbered step.
            line=_clean(s[1:])
            if line:current["steps"][-1]["children"].append(line)
    return sections

def compile_hierarchical_procedure(source:str,user_text:str,
                                   *,limit:int=680)->StructuredVoice|None:
    if (not isinstance(source,str) or not isinstance(user_text,str)
        or not 250<=len(source)<=7500 or not 420<=limit<=760
        or not _DETAIL.search(user_text) or _EXACT.search(user_text)
        or _SENSITIVE.search(source)):
        return None
    found=_sections(source)
    numbered=[s for s in found if s["steps"]]
    total=sum(len(s["steps"]) for s in numbered)
    if not 2<=len(numbered)<=5 or not 6<=total<=18:return None
    # Each independent section can reset its numbering; within that
    # section, numbering must still be complete and unambiguous.
    if any([p["index"] for p in sec["steps"]]!=
           list(range(1,len(sec["steps"])+1)) for sec in numbered):
        return None
    # Parameter tables immediately preceding the first operational section
    # are recipe baselines, not a random grab from all troubleshooting tables.
    prefix=[]
    firstpos=found.index(numbered[0])
    for section in found[:firstpos]:
        lines=section["table"]
        if not 2<=len(lines)<=9:continue
        if not any("参数" in row[0] or "基准" in row[1]
                   for row in lines[:1]):continue
        pairs=[]
        for cells in lines[1:7]:
            k,val=cells[:2]
            if not (1<=len(k)<=12 and 1<=len(val)<=22
                    and re.search(r"[0-9]",val)):continue
            pairs.append(k+"是"+val)
        if len(pairs)>=2:
            prefix.append(section["name"]+"："+ "，".join(pairs)+"。")
            break
    # A budget does not permit dropping a whole operational step or
    # replacing a missing step with an isolated fact from the end.
    for cap in (48,40,34,28):
        parts=list(prefix)
        dominant=max(numbered,key=lambda sec:len(sec["steps"]))
        for section in numbered:
            parts.append(section["name"]+"：")
            for at,step in enumerate(section["steps"],1):
                content=_action(step["title"],step["children"],cap)
                if not content:
                    parts=[];break
                # Only the substantial operational section needs spoken
                # ordinal markers; do not let "tools/equipment" swallow
                # the actual how-to steps or read 13 repetitive ordinals.
                lead=(f"第{at}步，" if section is dominant and len(section["steps"])>=5
                      else "")
                parts.append(lead+content.rstrip(" ，、。")+"。")
            if not parts:break
        if not parts:continue
        result="".join(parts)
        if 145<=len(result)<=limit and len(result)<len(source)*.90:
            # If a 2-level document includes a baseline table, an
            # action-oriented summary should retain it or decline.
            return StructuredVoice(result,"hierarchical_steps",len(source),
                                   total,len(numbered))
    return None

def file_facts_voice(source:str)->StructuredVoice|None:
    if not isinstance(source,str) or not 30<=len(source)<=12000:return None
    if (not _PATH.search(source) or
        re.search(r"未找到|没有找到|未查到|不存在|未能确认",source)):
        return None
    # This only applies when a source records a read-only file metadata
    # observation. An arbitrary webpage with a path isn't file evidence.
    size_line=next((line for line in source.splitlines()
                    if ("文件大小" in line or "大小" in line)
                    and "字节" in line),None)
    time_line=next((line for line in source.splitlines()
                    if "修改时间" in line or "最后修改" in line),None)
    if not size_line or not time_line:return None
    size=re.search(r"(\d{1,3}(?:,\d{3})+|\d+)\s*字节",size_line)
    date=re.search(r"((?:19|20)\d\d[-/.]\d{1,2}[-/.]\d{1,2}"
                   r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)",time_line)
    if not size or not date:return None
    # If the model self-corrects a path, the last cited native path wins;
    # the TTS must never voice the rejected earlier spellings.
    paths=_PATH.findall(source)
    names=_NAME.findall(source)
    corrected=PurePosixPath(paths[-1]).name if paths else ""
    chosen=corrected if corrected and "." in corrected else names[0] if names else ""
    if not chosen or len(chosen)>90:return None
    label=chosen.rsplit(".",1)[0]
    if not label or len(label)>70:return None
    approx=re.search(r"约\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB)",size_line,re.I)
    count=(size.group(0)+
           (f"（约 {approx.group(1)} {approx.group(2)}）" if approx else ""))
    where="，保存在桌面" if any("/Desktop/" in p for p in paths) else ""
    utterance=(f"查到了，文件名是{label}{where}。"
               f"文件大小{count}。"
               f"最后修改时间是{date.group(1)}。"
               "完整路径可以在Mac对话里查看。")
    return StructuredVoice(utterance,"file_facts",len(source),0,0)
