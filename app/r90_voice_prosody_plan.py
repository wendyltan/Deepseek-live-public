"""Lossless, deterministic rebalancing of local-Qwen long reply segments.

No audio API, model inference, disk writes or microphone. Repair avoidable
tiny trailing fragments without splitting English words or Chinese clauses.
All approved speech content must stay in exact order. The caller still
enforces the local Qwen <=150-character text budget.
"""
from __future__ import annotations
import re

MAX_CHARS = 150
MIN_TAIL = 40
BOUNDARY = re.compile(r'[，,。！？!?；;：:\n、]|(?<=\w)\s+(?=\w)')

def _redistribute(previous: str, last: str, cap: int):
    # Try a natural boundary in the previous chunk, then move its suffix
    # in front of the short tail (without resynthesizing or dropping text).
    if len(last)>=MIN_TAIL or not previous:
        return previous,last
    need=MIN_TAIL-len(last)
    options=[]
    for m in BOUNDARY.finditer(previous):
        cut=m.end()
        if cut<max(10,len(previous)//3) or len(previous)-cut<need:continue
        if len(previous)-cut+len(last)>cap:continue
        if len(previous[:cut].strip())<20:continue
        options.append(cut)
    if not options:return previous,last
    # A balanced rearrangement avoids two independent 2-3 word generations.
    target=(len(previous)+len(last))//2
    cut=min(options,key=lambda i:abs(len(previous)-i-target))
    return previous[:cut],previous[cut:]+last

def rebalance_phrases(phrases: list[str], *, cap:int=MAX_CHARS, favor_consistency:bool=False)->list[str]:
    if not isinstance(phrases,(list,tuple)) or not 2<=len(phrases)<=16:
        raise ValueError("bad_phrase_count")
    if not isinstance(cap,int) or isinstance(cap,bool) or not 64<=cap<=MAX_CHARS:
        raise ValueError("invalid_tts_limit")
    if any(not isinstance(p,str) or not p.strip() or len(p)>cap for p in phrases):
        raise ValueError("invalid_phrase_text")
    original="".join(phrases)
    merged=[]
    for segment in phrases:
        if (merged and len(merged[-1])+len(segment)<=cap and
            (len(merged[-1])+len(segment)<=110 or len(segment)>=MIN_TAIL)):
            merged[-1]+=segment
        else:
            merged.append(segment)
    if len(merged)>1:
        merged[-2],merged[-1]=_redistribute(merged[-2],merged[-1],cap)
    # Keep the first audible Qwen request short when there is a natural
    # break. The single-worker TTS service can then reach the speaker sooner;
    # this is NOT a guarantee of faster synthesis or better timbre.
    if not favor_consistency and len(merged)<16 and merged and len(merged[0])>105:
        candidates=[m.end() for m in BOUNDARY.finditer(merged[0])
                    if 38<=m.end()<=85 and len(merged[0])-m.end()>=18]
        if candidates:
            cut=min(candidates,key=lambda i:abs(i-68))
            first=merged[0]
            merged[:1]=[first[:cut],first[cut:]]
    assert "".join(merged)==original
    if any(not item.strip() or len(item)>cap for item in merged):
        raise ValueError("rebalanced_phrase_invalid")
    return merged
