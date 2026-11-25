"""R511 true early-audio chunk gain for trusted incremental ESP32 WSS only.

The original authenticated DSH reply and synthesis voice must already be
selected before entering. One gain fixed for the turn; no per-chunk pumping.
Peak shaping is bounded and sample-local. The entire final PCM must exactly
match emitted chunks before the producer can claim success.
"""
from __future__ import annotations
from array import array
import math
import os
import sys
from app.r441_pcm_quality import summary

SAMPLE_RATE=24000
PEAK_KNEE=24500
PEAK_SPAN=5000
ENTRY_SAMPLES=840
PHRASE_RAMP_SAMPLES=3600  # 150 ms, only when the new phrase gain changes

class EarlyTurnPCM:
    def __init__(self,*,target_rms=3400,max_gain=1.85,long_answer=False):
        self.target_rms=target_rms
        self.max_gain=max_gain
        self.gain=None
        self.total_out=0
        self.peak=0
        self.limited_samples=0
        self.phrase_index=None
        self.phrase_samples=0
        self.global_onset_samples=0
        self.candidate_gain=None
        self.previous_candidate_gain=1.0
        self.phrase_ramp_samples=0
        self.long_answer=bool(long_answer)
        self.phrase_target_rms=4300 if long_answer else 4000
        self.phrase_max_gain=3.0 if long_answer else 2.4
        try:
            override=float(os.environ.get("DAFEIYU_TTS_TARGET_RMS", ""))
        except ValueError:
            override=None
        if override is not None and math.isfinite(override):
            self.phrase_target_rms=min(5200, max(2400, override))
    def process(self, pcm:bytes, *,phrase_index:int, candidate:bool=False)->bytes:
        if not isinstance(pcm,bytes) or not pcm or len(pcm)%2:
            raise ValueError('early_pcm_must_be_pcm16le')
        if not 1<=phrase_index<=64:
            raise ValueError('invalid_early_phrase_index')
        if self.phrase_index!=phrase_index:
            if self.phrase_index is not None and phrase_index!=self.phrase_index+1:
                raise ValueError('early_phrase_out_of_order')
            if self.phrase_index is not None and self.candidate_gain is not None:
                self.previous_candidate_gain=self.candidate_gain
            self.phrase_index=phrase_index
            self.phrase_samples=0
            self.phrase_ramp_samples=0
            self.candidate_gain=None
        inf=summary(pcm)
        # Establish the turn gain once from the first voiced audio chunk.
        # Silence does not decide the gain, and later chunks never pump it.
        if self.gain is None and inf.active_rms>=150:
            self.gain=max(1.0,min(self.max_gain,self.target_rms/inf.active_rms))
        gain=self.gain or 1.0
        if candidate and self.candidate_gain is None and inf.active_rms>=300:
            # R503 phrases are synthesized independently. A single turn-wide
            # gain lets a quiet later phrase stay quiet for its entire length.
            # Set one bounded gain per phrase, never chase individual chunks.
            # First phrase has been consistently too quiet on the board;
            # later phrases must not inherit its forced boost. Use a stronger
            # first-phrase floor and let later phrases normalize downward.
            # The measured Wi-Fi answer had 2291/2412/4000 active RMS
            # across three phrases. Boost quiet phrases but also *reduce*
            # independently synthesized hot phrases; boost-only cannot
            # correct a phrase that is already 40% louder than the others.
            floor=(0.9 if phrase_index==1 else 0.8) if self.long_answer else (1.35 if phrase_index==1 else 0.75)
            self.candidate_gain=max(floor,min(self.phrase_max_gain,
                                               self.phrase_target_rms/inf.active_rms))
        vals=array('h');vals.frombytes(pcm)
        if sys.byteorder!='little':vals.byteswap()
        for i,x in enumerate(vals):
            if self.gain is not None and self.global_onset_samples<ENTRY_SAMPLES:
                if abs(x)>300:
                    self.global_onset_samples+=1
                attack=min(1.,self.global_onset_samples/ENTRY_SAMPLES)
            else:
                attack=1.
            effective=1.+(gain-1.)*attack
            if candidate:
                # Fix gain within each phrase. Long buffered replies blend
                # over 35ms; early streamed replies retain the 150ms blend.
                target=self.candidate_gain or self.previous_candidate_gain
                if phrase_index==1:
                    effective=1.+(target-1.)*attack
                else:
                    ramp_limit=ENTRY_SAMPLES if self.long_answer else PHRASE_RAMP_SAMPLES
                    if abs(x)>300 and self.phrase_ramp_samples<ramp_limit:
                        self.phrase_ramp_samples+=1
                    blend=min(1.,self.phrase_ramp_samples/ramp_limit)
                    effective=self.previous_candidate_gain+(target-self.previous_candidate_gain)*blend
            # R511 review: never artificially duck an entire later phrase.
            # A 35% boundary cut audibly faded up after each TTS restart,
            # even though this same turn already has one fixed gain.
            # Keep the first-turn onset ramp and bounded peak ceiling only.
            y=x*effective
            if abs(y)>PEAK_KNEE:
                y=math.copysign(PEAK_KNEE+PEAK_SPAN*
                    math.tanh((abs(y)-PEAK_KNEE)/PEAK_SPAN),y)
                self.limited_samples+=1
            vals[i]=max(-30000,min(30000,round(y)))
        self.phrase_samples+=len(vals)
        self.total_out+=len(pcm)
        self.peak=max(self.peak,max((abs(x) for x in vals),default=0))
        if sys.byteorder!='little':vals.byteswap()
        return vals.tobytes()
