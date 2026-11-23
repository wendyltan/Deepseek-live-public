"""R539: protect exceptional Qwen D10 *short buffered* voice from high-rate squeal.

Actual reproducible "今天星期日。" D10 PCM contains >1,000 very large
sample-to-sample changes clustered around 5.4-5.54 seconds despite no 16-bit
clipping. These are isolated, extremely strong high-frequency bursts, not
a Wi-Fi underrun. Remove only their ultrasonic/ringing component with a
short triangular FIR and a smooth boundary. Never resynthesize, crop voice,
boost gain, touch long R503 or change the PCM duration/voice identity.
"""
from __future__ import annotations
from array import array
import sys

RATE=24000
FRAME=RATE//10 # 100ms
STEP=20000
MIN_HIGH_STEPS=40
CROSS=RATE//50 # 20ms


def suppress_short_d10_spikes(pcm:bytes, *, permitted:bool) -> tuple[bytes,dict[str,int]]:
    meta={"applied":0,"hot_100ms_windows":0,"big_steps_before":0,
          "big_steps_after":0,"max_step_before":0,"max_step_after":0}
    if not isinstance(pcm,bytes) or len(pcm)%2:
        raise ValueError("r539_d10_pcm16_required")
    n=len(pcm)//2
    if not permitted or not RATE//2<=n<=RATE*15:
        return pcm,meta
    a=array("h")
    a.frombytes(pcm)
    if sys.byteorder!="little":a.byteswap()
    windows=[]
    for at in range(0,n,FRAME):
        end=min(n,at+FRAME)
        hits=0;biggest=0
        for k in range(at+1,end):
            delta=abs(int(a[k])-int(a[k-1]))
            biggest=max(biggest,delta)
            hits+=int(delta>STEP)
        meta["big_steps_before"]+=hits
        meta["max_step_before"]=max(meta["max_step_before"],biggest)
        if hits>=MIN_HIGH_STEPS and biggest>=30000:
            windows.append((at,end))
    meta["hot_100ms_windows"]=len(windows)
    if not windows or len(windows)>max(3,n//FRAME//5):
        return pcm,meta
    # Merge adjoining outlier windows, filtering ~20ms at each edge.
    spans=[]
    for first,last in windows:
        left=max(0,first-CROSS)
        right=min(n,last+CROSS)
        if spans and left<=spans[-1][1]:
            spans[-1]=(spans[-1][0],max(spans[-1][1],right))
        else:spans.append((left,right))
    # Positive-coefficient symmetric 7-tap triangle. Suppresses synthetic
    # high-frequency oscillation while preserving ordinary low-pitched
    # syllable energy. Apply ONLY within outlier spans, no full-utterance EQ.
    out=array("h",a)
    weights=(1,2,3,4,3,2,1)
    for first,last in spans:
        for i in range(first,last):
            filt=round(sum(weights[j]*a[
                min(n-1,max(0,i+j-3))] for j in range(7))/16)
            factor=min(1.0,(i-first)/max(1,CROSS),
                       (last-1-i)/max(1,CROSS))
            candidate=round(a[i]*(1-factor)+filt*factor)
            out[i]=max(-32767,min(32767,candidate))
    for at in range(0,n,FRAME):
        end=min(n,at+FRAME)
        for k in range(at+1,end):
            delta=abs(int(out[k])-int(out[k-1]))
            meta["big_steps_after"]+=int(delta>STEP)
            meta["max_step_after"]=max(meta["max_step_after"],delta)
    # No accidental change that *creates* more high-step noise.
    if meta["big_steps_after"]>meta["big_steps_before"] or (
            max(map(abs,out))>max(map(abs,a))):
        return pcm,{**meta,"applied":0}
    meta["applied"]=1
    if sys.byteorder!="little":out.byteswap()
    return out.tobytes(),meta
