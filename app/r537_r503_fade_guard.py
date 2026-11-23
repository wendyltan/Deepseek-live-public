"""R537 R503 voice continuity: measured sustained-fade guard, not a blind tail cut.

Only fully buffered R503 after the R526 attenuation stage. If whole-window
voiced levels show a persistent late drop, use slow 2-second envelopes to
attenuate unusually hot opening windows and recover softer later voiced speech.
Never reacts to each phoneme/stream packet, never alters frame count, timing,
pitch, reference voice, or non-voice TTS. All computation is in memory.
"""
from __future__ import annotations

import statistics
from app.r441_pcm_quality import summary

SAMPLE_RATE = 24000
WINDOW_MS = 2000
WINDOW_BYTES = WINDOW_MS * 48
BLOCK_MS = 10
BLOCK_BYTES = BLOCK_MS * 48
MAX_BOOST = 1.65
MIN_GAIN = 0.78
VOICE_MIN = 450
PEAK_CEILING = 28000


def stabilize_fading_r503(pcm:bytes, *, phrase_index:int) -> tuple[bytes,dict[str,int]]:
    if not isinstance(pcm,bytes) or len(pcm)<2 or len(pcm)%2:
        raise ValueError("r537_pcm16le_required")
    if type(phrase_index) is not int or not 1<=phrase_index<=64:
        raise ValueError("r537_invalid_phrase_index")
    unchanged={"applied":0,"early_rms":0,"late_rms":0,
               "peak_in":0,"peak_out":0,"min_gain_permille":1000,
               "max_gain_permille":1000}
    if phrase_index==1 or len(pcm)<12*SAMPLE_RATE*2:
        return pcm,unchanged
    from app.r526_buffered_voice_smoothing import audioop
    if audioop is None:
        return pcm,unchanged
    parts=[pcm[a:a+WINDOW_BYTES] for a in range(0,len(pcm),WINDOW_BYTES)]
    info=[summary(p) for p in parts]
    n=len(info)
    if n<6:return pcm,unchanged
    # Skip window(s) with too little actual speech or too little PCM.
    voiced=[f.active_rms if f.active_rms>=VOICE_MIN and
            f.active_blocks>=max(15,(len(parts[i])//BLOCK_BYTES)//6)
            else 0 for i,f in enumerate(info)]
    earlier=[v for v in voiced[1:max(3,n//2)] if v]
    later=[v for v in voiced[max(n//2,n-4):] if v]
    if len(earlier)<2 or len(later)<2:return pcm,unchanged
    early=int(statistics.median(earlier))
    late=int(statistics.median(later))
    unchanged.update(early_rms=early,late_rms=late)
    # Do not flatten intentional natural intonation or stable source audio.
    if late*100>=early*70:return pcm,unchanged
    target=min(3350,max(2550,round(early*.95)))
    gains=[]
    for j,level in enumerate(voiced):
        if level<=0:
            gains.append(1.0)
            continue
        wanted=max(MIN_GAIN,min(MAX_BOOST,target/level))
        # Peak-safe guard for the whole 2-second window.
        if wanted>1.0 and info[j].peak>0:
            wanted=min(wanted,PEAK_CEILING/info[j].peak)
        gains.append(wanted)
    rendered=[]
    gain_min=gain_max=1.0
    blocks=len(pcm)//BLOCK_BYTES
    for at in range(0,len(pcm),BLOCK_BYTES):
        ix=at//WINDOW_BYTES
        # Slowly interpolate over a 2-second source window. A fast per-frame
        # compressor sounds like pumping; this envelope intentionally cannot.
        fraction=(at%WINDOW_BYTES)/WINDOW_BYTES
        gi=gains[min(ix,n-1)]
        gj=gains[min(ix+1,n-1)]
        gain=gi+(gj-gi)*fraction
        # The first ~100ms of a new phrase never gets a sudden level switch.
        gain=1.0+(gain-1.0)*min(1.0,(at//BLOCK_BYTES+1)/10)
        block=pcm[at:at+BLOCK_BYTES]
        if abs(gain-1.0)<.0005:
            rendered.append(block)
            continue
        # A conservative 10ms PCM peak bound prevents boost clipping in an
        # inter-window transition even if windows contain sparse peaks.
        if gain>1.0:
            peak=audioop.max(block,2)
            if peak>0:gain=min(gain,PEAK_CEILING/peak)
        gain_min=min(gain_min,gain)
        gain_max=max(gain_max,gain)
        rendered.append(audioop.mul(block,2,gain))
    out=b"".join(rendered)
    if len(out)!=len(pcm):raise ValueError("r537_length_mismatch")
    after=summary(out)
    if after.peak>PEAK_CEILING:
        # Never publish a new clipping risk or partially changed output.
        return pcm,unchanged
    return out,{"applied":1,"early_rms":early,"late_rms":late,
                "peak_in":max(f.peak for f in info),
                "peak_out":after.peak,
                "min_gain_permille":round(gain_min*1000),
                "max_gain_permille":round(gain_max*1000)}
