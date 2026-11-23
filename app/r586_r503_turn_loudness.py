"""R586: bounded whole-turn R503 loudness matching on already-buffered PCM.

Normalize only conspicuous >30% *inter-phrase* jumps. Never alter voice
reference, words, timing, frame counts or a previously offered WSS chunk.
No peak over 28k, no more than 1.45x boost or 0.72 attenuation. User hearing
acceptance still requires the actual physical board.
"""
from __future__ import annotations

import statistics
from app.r441_pcm_quality import summary
from app.r526_buffered_voice_smoothing import audioop

RATE=24000
BLOCK_BYTES=480  # 10ms
PEAK_LIMIT=28000
MIN_LEVEL=300

def balance_buffered_r503_turn(pcm:bytes, spans:list[tuple[int,int]]) -> tuple[bytes,dict]:
    unchanged={'applied':0,'phrases_matched':0,'max_before_ratio_permille':1000,
               'max_after_ratio_permille':1000,'min_gain_permille':1000,
               'max_gain_permille':1000}
    if (not isinstance(pcm,bytes) or len(pcm)%2 or not pcm or
        not isinstance(spans,list) or len(spans)<2 or len(spans)>64 or
        audioop is None):
        return pcm,unchanged
    prev=0
    for at,end in spans:
        if not (type(at) is int and type(end) is int and
                at==prev and end>at and end<=len(pcm) and
                (end-at)%2==0):
            return pcm,unchanged
        prev=end
    if prev!=len(pcm):return pcm,unchanged
    pieces=[pcm[a:b] for a,b in spans]
    measurements=[summary(x) for x in pieces]
    levels=[m.active_rms for m in measurements]
    valid=[x for x in levels if x>=MIN_LEVEL]
    if len(valid)<2:return pcm,unchanged
    before=max(valid)/min(valid)
    unchanged['max_before_ratio_permille']=round(before*1000)
    if before<1.30:return pcm,unchanged
    # Median of actual voiced levels, not silence-contaminated full PCM RMS.
    target=statistics.median(valid)
    goals=[]
    for level,info in zip(levels,measurements):
        if level<MIN_LEVEL:
            goals.append(1.)
            continue
        ratio=max(.72,min(1.45,target/level))
        if ratio>1.:
            ratio=min(ratio,PEAK_LIMIT/max(info.peak,1))
        goals.append(min(1.45,max(.72,ratio)))
    blocks=[]
    previous_gain=1.
    for source,gain in zip(pieces,goals):
        duration_ms=len(source)/48
        # Full 200ms transition to avoid a hard dynamic shift at phrase joins.
        ramp=max(1,min(20,round(min(duration_ms/3,200)/10)))
        for i,start in enumerate(range(0,len(source),BLOCK_BYTES)):
            part=source[start:start+BLOCK_BYTES]
            amount=min(1.,(i+1)/ramp)
            actual=previous_gain+(gain-previous_gain)*amount
            if actual>1.:
                actual=min(actual,PEAK_LIMIT/max(1,audioop.max(part,2)))
            blocks.append(audioop.mul(part,2,actual) if abs(actual-1.)>.0001 else part)
        previous_gain=gain
    out=b''.join(blocks)
    if len(out)!=len(pcm) or summary(out).peak>PEAK_LIMIT:
        return pcm,unchanged
    after_levels=[summary(out[a:b]).active_rms for a,b in spans]
    after_valid=[x for x in after_levels if x>=MIN_LEVEL]
    if len(after_valid)<2:return pcm,unchanged
    after_ratio=max(after_valid)/min(after_valid)
    # A disproportionate gain error cannot be called an improvement.
    if after_ratio>=before:return pcm,unchanged
    return out,{
        'applied':1,'phrases_matched':len(valid),
        'max_before_ratio_permille':round(before*1000),
        'max_after_ratio_permille':round(after_ratio*1000),
        'min_gain_permille':round(min(goals)*1000),
        'max_gain_permille':round(max(goals)*1000),
    }
