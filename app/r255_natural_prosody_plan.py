"""Bounded punctuation-aware natural TTS segments, lossless and model-free.

Prefer complete Chinese spoken sentences/clauses, avoid tiny orphan tails.
One source voice and one PCM2 stream are handled by the existing pipeline.
"""
from __future__ import annotations
import re
from app.r141_voice_phrase_boundaries import natural_segments

STRONG='。！？!?；;\n'
WEAK='，,：:、'

def prosodic_phrases(text:str,*,limit:int=55,target:int=43)->list[str]:
    if not isinstance(text,str) or not text.strip() or len(text)>8000:
        raise ValueError('r255_invalid_text')
    if type(limit) is not int or not 40<=limit<=75 or not 20<=target<=limit:
        raise ValueError('r255_invalid_limits')
    if len(text)<=limit:return [text]
    # Do not spend time on quadratic planning for long unbounded inputs.
    # A sentence-only regular expression does not introduce any new text.
    if len(text)>1200:return natural_segments(text,limit=limit)
    ends={0,len(text)}
    for m in re.finditer(r'[。！？!?；;，,：:、\n]|(?<=\w)\s+(?=\w)',text):
        ends.add(m.end())
    # Fallback boundary in punctuation-free spans: nearest whitespace if
    # possible, otherwise an unavoidable exact-width Chinese cut.
    fixed_points=sorted(ends)
    for start,end in zip(fixed_points,fixed_points[1:]):
        gap=end-start
        if gap<=limit:continue
        # Balance otherwise punctuation-free words/sentences instead of
        # creating a 10-character orphan after a maximal-width first cut.
        pieces=(gap+limit-1)//limit
        for part in range(1,pieces):
            ideal=start+round(gap*part/pieces)
            near=[i+1 for i in range(max(start+1,ideal-8),min(end,ideal+9))
                  if text[i].isspace()]
            cut=min(near,key=lambda pos:abs(pos-ideal)) if near else ideal
            if start<cut<end:ends.add(cut)
    points=sorted(ends);n=len(points)
    best=[float('inf')]*n;before=[-1]*n
    best[0]=0.0
    for k in range(1,n):
        ending=points[k]
        for j in range(k-1,-1,-1):
            length=ending-points[j]
            if length>limit:break
            if length<1 or best[j]==float('inf'):continue
            fragment=text[points[j]:ending]
            if not fragment.strip():continue
            # Sentence terminal boundary is worth fewer TTS restarts.
            if ending==len(text) or text[ending-1] in STRONG: boundary=0.0
            elif text[ending-1] in WEAK:boundary=5.0
            elif text[ending-1].isspace():boundary=9.0
            else:boundary=16.0
            tiny=(115.0 if length<20 else 25.0 if length<26 else 0.0)
            cost=best[j]+(length-target)**2/80.0+boundary+tiny
            if cost<best[k]:best[k]=cost;before[k]=j
    if before[-1]<0:return natural_segments(text,limit=limit)
    out=[];at=n-1
    while at:
        left=before[at]
        if left<0:return natural_segments(text,limit=limit)
        out.append(text[points[left]:points[at]])
        at=left
    out.reverse()
    assert ''.join(out)==text
    return out
