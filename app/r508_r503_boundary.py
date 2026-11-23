"""R508: tame R503's independent phrase-start attack, leave D10 unchanged.

Only first audible ~300ms of phrases 2+ is shaped; no PCM length change,
no dynamic compressor, no reference/model alteration or persisted audio.
"""
from __future__ import annotations
from array import array
import math
import sys

SAMPLE_RATE=24000
WINDOW=480
MAX_SEARCH_MS=1600
ATTACK_MS=300
START_RATIO=0.65


def smooth_candidate_phrase_start(pcm:bytes, *,phrase_index:int,
                                  target_rms:int=0) -> tuple[bytes,int]:
    """Return same-length PCM + actual changed milliseconds.

    Use 20ms windows and an absolute+relative voiced threshold to skip
    leading near-silence; never attenuate the start of phrase one.
    """
    if not isinstance(pcm,bytes) or len(pcm)%2:
        raise ValueError("pcm16le_required")
    if not isinstance(phrase_index,int) or phrase_index<1:
        raise ValueError("invalid_phrase_index")
    if phrase_index==1 or len(pcm)<2*WINDOW:
        return pcm,0
    vals=array("h");vals.frombytes(pcm)
    if sys.byteorder!="little":vals.byteswap()
    threshold=max(280,min(950,round(target_rms*0.22)))
    limit=min(len(vals),SAMPLE_RATE*MAX_SEARCH_MS//1000)
    onset=None
    for start in range(0,limit-WINDOW+1,WINDOW):
        part=vals[start:start+WINDOW]
        rms=math.sqrt(sum(v*v for v in part)/WINDOW)
        if rms>threshold:
            onset=start
            break
    if onset is None:
        return pcm,0
    attack=min(len(vals)-onset,SAMPLE_RATE*ATTACK_MS//1000)
    if attack<=0:return pcm,0
    for i in range(attack):
        scale=START_RATIO+(1-START_RATIO)*min(1.0,i/max(1,attack-1))
        vals[onset+i]=round(vals[onset+i]*scale)
    if sys.byteorder!="little":vals.byteswap()
    return vals.tobytes(),round(attack*1000/SAMPLE_RATE)
