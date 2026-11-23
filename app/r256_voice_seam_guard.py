"""R256 bounded PCM16 edge declick for independent Qwen phrase restarts.

No model/provider calls, time stretching or filter. Added silence is <=8 ms
per splice; the first 5 ms of newly synthesized PCM fades from zero, so a
nonzero prior sample does not become an audible single-sample pop.
"""
from __future__ import annotations
from array import array
import sys

RATE=24000
HEAD_SAMPLES=120  # 5ms
BRIDGE_SAMPLES=192 # 8ms

def fade_phrase_head(pcm:bytes)->bytes:
    if not isinstance(pcm,bytes) or len(pcm)%2:raise ValueError('r256_invalid_pcm')
    if not pcm:return pcm
    samples=array('h');samples.frombytes(pcm)
    if sys.byteorder!='little':samples.byteswap()
    n=min(HEAD_SAMPLES,len(samples))
    for i in range(n):
        samples[i]=round(samples[i]*i/max(1,n-1))
    if sys.byteorder!='little':samples.byteswap()
    return samples.tobytes()

def tail_to_silence(last:int)->bytes:
    if not isinstance(last,int) or not -32768<=last<=32767:
        raise ValueError('r256_invalid_last_sample')
    # Small continuous linear ramp, not an abrupt mute/clamp. Does not
    # claim to remove pops already present inside Qwen's original audio.
    samples=array('h',[round(last*(1-i/(BRIDGE_SAMPLES-1)))
                     for i in range(BRIDGE_SAMPLES)])
    if sys.byteorder!='little':samples.byteswap()
    return samples.tobytes()
