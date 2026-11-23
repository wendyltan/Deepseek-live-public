"""R209 one-stage, peak-aware gentle speech lift for 24kHz mono PCM16.
This does not replace Qwen timbre or re-synthesize; no limiter/clipping,
no stacked compressor. State is continuous across synthesized phrases.
"""
from __future__ import annotations
from array import array
import math
import sys

class GentleVoiceLift:
    def __init__(self, *, headroom=30000.0, maximum_gain=1.28):
        if not 25000.0<=headroom<=30000.0 or not 1.0<=maximum_gain<=1.28:
            raise ValueError('unsafe_voice_gain_profile')
        self.gain = 1.0
        self.blocks = 0
        self.input_energy = 0
        self.output_energy = 0
        self.samples = 0
        self.max_input = 0
        self.max_output = 0
        self.target_active_rms = 8500.0
        self.maximum_gain = maximum_gain
        self.headroom = headroom

    def process(self, pcm:bytes)->bytes:
        if not isinstance(pcm,bytes) or len(pcm)%2:
            raise ValueError("24k_pcm16_required")
        if not pcm:return b""
        values=array("h");values.frombytes(pcm)
        if sys.byteorder!="little":values.byteswap()
        peak=max(abs(v) for v in values)
        active=[v for v in values[::8] if abs(v)>=320]
        enough=len(active)>=max(8,len(values)//96)
        wanted=1.0
        if enough and peak:
            rms=math.sqrt(sum(int(v)*int(v) for v in active)/len(active))
            wanted=max(1.0,min(self.maximum_gain,self.target_active_rms/max(1.0,rms)))
        # The gain is capped against *this block's* real peak. No PCM
        # sample is flattened at a fixed threshold as in R207.
        ceiling=min(2.0,max(0.10,self.headroom/max(1,peak)))
        wanted=min(wanted,ceiling)
        # Smooth within each 640ms Qwen chunk. Preserve zero exactly.
        old=min(self.gain,ceiling)
        # Reach the safe quiet-speech lift earlier in the first 2 chunks.
        # Later chunks change slowly to avoid an audible gain pump between
        # independently synthesized Qwen phrases. The peak cap still wins.
        blend=0.75 if self.blocks<2 else 0.32
        goal=old*(1.0-blend)+wanted*blend if enough else min(1.0,ceiling)
        goal=min(goal,ceiling)
        size=len(values)
        self.input_energy+=sum(int(v)*int(v) for v in values)
        self.samples+=size
        self.max_input=max(self.max_input,peak)
        if (peak>self.headroom or abs(old-1.0)>0.0001 or
            abs(goal-1.0)>0.0001):
            # Unlike the old boost-only path, a naturally hot Qwen chunk
            # also needs safe DOWN gain. Scale the entire block smoothly,
            # never hard-clip a peak or stack a second compressor.
            for i,x in enumerate(values):
                factor=old+(goal-old)*i/max(1,size-1)
                values[i]=round(x*factor)
        self.gain=goal
        self.blocks+=1
        self.max_output=max(self.max_output,max(abs(v) for v in values))
        self.output_energy+=sum(int(v)*int(v) for v in values)
        if sys.byteorder!="little":values.byteswap()
        return values.tobytes()

    def metrics(self):
        n=max(1,self.samples)
        return {"peak_in":self.max_input,"peak_out":self.max_output,
                "rms_in":round(math.sqrt(self.input_energy/n),1),
                "rms_out":round(math.sqrt(self.output_energy/n),1),
                "blocks":self.blocks,"last_gain":round(self.gain,3),
                "added_clipped_samples":0}
