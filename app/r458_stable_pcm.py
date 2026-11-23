"""R461 fixed per-phrase gain with conservative sparse-transient limiting.

The old R209 changed gain on each 640ms block, and R441 ignored up to
about 2dB phrase-to-phrase variance. This module calculates a single
bounded gain from each *complete verified* phrase and matches all phrases
to the same first-phrase baseline, with a 120ms entry ramp and peak cap.
No audio storage, resynthesis, model calls, or dynamic compression pump.
"""
from __future__ import annotations
from array import array
import math
import sys
from app.r441_pcm_quality import SAMPLE_RATE,summary

class TurnWideLoudnessLift:
    """Fixed gain decided by first verified phrase; safe peak ceiling each phrase.

    Unlike the old phrase matcher, lifts quiet first phrases as well as later
    ones. Bounded <=1.55 and no gain within a phrase; attack applies only to
    the very start of the first utterance.
    """
    def __init__(self,*,target_active_rms=2600,max_gain=1.55,
                 peak_ceiling=29000):
        self.target=target_active_rms
        self.max_gain=max_gain
        self.ceiling=peak_ceiling
        self.turn_gain=None
        self.phrases=0

    def process(self,pcm:bytes)->tuple[bytes,int]:
        info=summary(pcm)
        self.phrases+=1
        if not info.active_rms or not info.peak:
            return pcm,1000
        if self.turn_gain is None:
            self.turn_gain=min(self.max_gain,
                               max(1.0,self.target/info.active_rms))
        gain=min(self.turn_gain,self.ceiling/info.peak)
        if gain<=1.001 or info.peak>=32700:
            return pcm,1000
        vals=array("h");vals.frombytes(pcm)
        if sys.byteorder!="little":vals.byteswap()
        # 35ms initial entry ramp: avoid a click without masking a syllable.
        ramp=min(len(vals),SAMPLE_RATE*35//1000) if self.phrases==1 else 0
        for i,x in enumerate(vals):
            alpha=(min(1.0,i/max(1,ramp)) if ramp else 1.0)
            vals[i]=max(-32767,min(32767,round(x*(1+(gain-1)*alpha))))
        if sys.byteorder!="little":vals.byteswap()
        return vals.tobytes(),round(gain*1000)


class TurnLevelMatcher:
    def __init__(self, *, max_gain=1.55,peak_ceiling=30000):
        if not (1.0<=max_gain<=1.55 and 26500<=peak_ceiling<=30500):
            raise ValueError("unsafe_audio_gain")
        self.target_rms=None
        self.peak_out=0
        self.phrases=0
        self.max_gain=float(max_gain)
        self.peak_ceiling=int(peak_ceiling)
        self.last_limited_samples_ppm=0
        self.last_peak_restricted=False

    def process(self,pcm:bytes)->tuple[bytes,int]:
        info=summary(pcm)
        self.phrases+=1
        self.peak_out=max(self.peak_out,info.peak)
        self.last_limited_samples_ppm=0
        self.last_peak_restricted=False
        if not info.active_rms or not info.peak:
            return pcm,1000
        if self.target_rms is None:
            self.target_rms=info.active_rms
        # The verified first phrase supplies ONE turn-wide target.
        # Keep one static gain for each whole phrase; do not pump inside words.
        desired=self.target_rms/info.active_rms
        gain=max(1.0/self.max_gain,min(self.max_gain,desired))
        if info.peak>=32700:gain=min(gain,1.0) # existing clipped TTS
        soft=False
        knee=self.peak_ceiling-8000
        vals=array("h")
        vals.frombytes(pcm)
        if sys.byteorder!="little":vals.byteswap()
        if gain>1.0 and gain*info.peak>self.peak_ceiling:
            # R458 was capped by the *single largest sample*; a rare codec
            # spike could suppress the entire otherwise quiet phrase by 4dB.
            # Only repair sparse outliers (<1% of samples beyond the knee).
            # Sustained loud audio takes the old conservative global peak cap:
            # never reshape a normal vowel's waveform just for RMS equality.
            count=sum(1 for x in vals if abs(x)*gain>knee)
            soft=(count*100< len(vals))
            if not soft:
                gain=min(gain,self.peak_ceiling/info.peak)
                self.last_peak_restricted=True
        else:
            gain=min(gain,self.peak_ceiling/info.peak)
        if abs(gain-1.0)<.01 and not soft:
            return pcm,1000
        ramp=min(len(vals),SAMPLE_RATE*120//1000)
        limited=0
        for i,x in enumerate(vals):
            factor=1+(gain-1)*min(1.0,i/max(1,ramp))
            y=x*factor
            if soft and abs(y)>knee:
                # Continuous derivative at the knee; no hard clipping.
                # This is deliberately sample-peak shaping, NOT a claimed
                # ITU true-peak limiter and not a compressor for all speech.
                sign=-1 if y<0 else 1
                y=sign*(knee+8000*math.tanh((abs(y)-knee)/8000))
                limited+=1
            vals[i]=max(-32767,min(32767,round(y)))
        self.last_limited_samples_ppm=round(1000000*limited/max(1,len(vals)))
        self.peak_out=max(self.peak_out,max((abs(x) for x in vals),default=0))
        if sys.byteorder!="little":vals.byteswap()
        return vals.tobytes(),round(gain*1000)
