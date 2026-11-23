"""In-memory physical ESP microphone capture quality signals, no audio persistence."""
from __future__ import annotations
import math
import struct

def pcm_level(pcm:bytes,*,rate:int=16000):
    if not isinstance(pcm,bytes) or len(pcm)%2 or not pcm or len(pcm)>rate*2*21:
        raise ValueError("invalid_capture")
    # Sample every fourth value, enough to detect silence and clipping without
    # retaining original speech or putting waveform data into logs.
    values=[x[0] for x in struct.iter_unpack("<h",pcm)][::4]
    count=len(values)
    peak=max(abs(v) for v in values)
    rms=math.sqrt(sum(v*v for v in values)/count)
    clipped=sum(1 for v in values if abs(v)>=32600)
    return {
        "seconds":round(len(pcm)/2/rate,2),
        "rms_dbfs":round(20*math.log10(max(rms/32768,1e-8)),1),
        "peak_percent":round(peak*100/32768,1),
        "clipped_percent":round(100*clipped/count,3)
    }

def normalize_for_asr(pcm:bytes,*,rate:int=16000):
    """Bounded in-memory gain only for verified weak board-mic captures.

    No persistent PCM, network use, or gain applied to already loud captures.
    Upper peak bound avoids creating new clipping on transients.
    """
    if not pcm or len(pcm)%2 or len(pcm)>rate*2*21:
        raise ValueError("invalid_capture")
    import array
    v=array.array("h")
    v.frombytes(pcm)
    if not v:return pcm,{"applied":False,"gain":1.0}
    peak=max(abs(z) for z in v)
    if peak==0 or peak>=3277:
        return pcm,{"applied":False,"gain":1.0}
    rms=math.sqrt(sum(z*z for z in v)/len(v))
    if rms>=32768*10**(-43/20):
        return pcm,{"applied":False,"gain":1.0}
    gain=min(6.0,max(1.0,(32768*10**(-29/20))/max(rms,1)),27000/max(peak,1))
    if gain<=1.05:return pcm,{"applied":False,"gain":1.0}
    output=array.array("h",(int(max(-27000,min(27000,round(z*gain)))) for z in v))
    return output.tobytes(),{"applied":True,"gain":round(gain,2)}
