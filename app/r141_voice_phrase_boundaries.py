"""Sentence-first spoken segmentation: one character never stranded by near-cap cut.

Use human clause punctuation before fallback. No TTS calls or original DSH
answer edits, only lossless segmentation of already normalized speech text.
"""
from __future__ import annotations
import re
PUNCTUATION="。！？!?；;，,：:、\n"
STRONG="。！？!?；;\n"
def natural_segments(text,*,limit=145):
    if not isinstance(text,str) or not text.strip() or len(text)>8000:
        raise ValueError("invalid_speech_text")
    if type(limit)!=int or not 32<=limit<=150:raise ValueError("invalid_limit")
    # Preserve all characters in the speech version; punctuation stays attached
    # to the preceding phrase, not alone at the start of the next Qwen request.
    clauses=[]
    start=0
    for m in re.finditer(r"[。！？!?；;，,：:、\n]",text):
        end=m.end()
        if end>start:clauses.append(text[start:end]);start=end
    if start<len(text):clauses.append(text[start:])
    parts=[];current=""
    def split_long(clause):
        items=[]
        while len(clause)>limit:
            # Avoid a 1-12 character tail from a naïve hard limit.
            pieces=(len(clause)+limit-1)//limit
            target=(len(clause)+pieces-1)//pieces
            lo=max(16,target-22)
            hi=min(limit,target+22)
            candidates=[m.end() for m in re.finditer(r"[，,、：:]|(?<=\w)\s+(?=\w)",clause[:hi])
                        if lo<=m.end()<=hi]
            cut=min(candidates,key=lambda x:abs(x-target)) if candidates else target
            if not (0<cut<=limit):raise ValueError("invalid_speech_cut")
            items.append(clause[:cut]);clause=clause[cut:]
        if clause:items.append(clause)
        return items
    for clause in clauses:
        for part in split_long(clause):
            if len(current)+len(part)<=limit:
                current+=part
            else:
                if current:parts.append(current)
                current=part
    if current:parts.append(current)
    # Merge an avoidable very short final generation into its predecessor.
    if len(parts)>1 and len(parts[-1].strip())<10 and len(parts[-2])+len(parts[-1])<=limit:
        parts[-2]+=parts.pop()
    if not parts or len(parts)>90 or any(len(p)>limit or not p for p in parts):
        raise ValueError("invalid_speech_plan")
    assert "".join(parts)==text
    return parts
