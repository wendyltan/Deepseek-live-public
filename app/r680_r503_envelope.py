"""R680: correct sustained MIDDLE or END R503 volume dips on full PCM.

R537 only handled phrase 2's late fade. This bounded secondary pass works
on each completed R503 phrase, including phrase 1. No sample addition,
voice/tempo alteration, packet-by-packet gain chasing or extra TTS calls.
"""
from __future__ import annotations
import statistics
from app.r441_pcm_quality import summary
from app.r526_buffered_voice_smoothing import audioop

FRAME_BYTES=48000 # 1 second, mono PCM16 24 kHz
BLOCK_BYTES=480 # 10 ms
MAX_PEAK=28000
VOICE_MIN=500
MAX_BOOST=1.65

def recover_sustained_voice_dips(pcm:bytes)->tuple[bytes,dict[str,int]]:
    if not isinstance(pcm,bytes) or not pcm or len(pcm)%2:
        raise ValueError("r680_even_pcm16_required")
    base={"applied":0,"baseline_rms":0,"quiet_windows":0,
          "min_before_rms":0,"min_after_rms":0,"peak_out":0}
    if audioop is None or len(pcm)<8*FRAME_BYTES:
        return pcm,base
    slices=[pcm[i:i+FRAME_BYTES] for i in range(0,len(pcm),FRAME_BYTES)]
    measures=[summary(chunk) for chunk in slices]
    valid=[i for i,q in enumerate(measures) if
           len(slices[i])>=FRAME_BYTES//2 and
           q.active_rms>=VOICE_MIN and q.active_blocks>=20]
    if len(valid)<5:return pcm,base
    # Include the first few seconds of normal speech, without letting one
    # clipped/over-hot opening syllable dominate the reference.
    early=[measures[i].active_rms for i in valid if i<5]
    if len(early)<2:return pcm,base
    baseline=int(statistics.median(early))
    base["baseline_rms"]=baseline
    if baseline<1100:return pcm,base
    quiet={i for i in valid if measures[i].active_rms < baseline*.70}
    runs=[];start=last=None
    for i in sorted(quiet):
        if start is None:start=last=i
        elif i==last+1:last=i
        else:runs.append((start,last));start=last=i
    if start is not None:runs.append((start,last))
    targets=set()
    for start,end in runs:
        # Two complete seconds of actual faint speech anywhere in the
        # middle or end are not natural last-phoneme attenuation.
        if end-start+1>=2:
            targets.update(range(start,end+1))
    if not targets:return pcm,base
    # Compute a conservative target per consecutive 1s region, never
    # attenuating already adequate voice. 2s attack and release prevent
    # audible pumping/abrupt changes in syllable boundaries.
    gains=[min(MAX_BOOST,baseline/max(1,measures[i].active_rms))
           if i in targets else 1. for i in range(len(slices))]
    out=[];current=1.;gain_min=1.;gain_max=1.;changed=0
    for i,chunk in enumerate(slices):
        target=gains[i]
        for at in range(0,len(chunk),BLOCK_BYTES):
            block=chunk[at:at+BLOCK_BYTES]
            # 10ms times 1/180 moves gain with ~1.8s relaxation.
            current += (target-current)/180.
            gain=current
            if gain>1.0:
                p=audioop.max(block,2)
                if p:gain=min(gain,MAX_PEAK/p)
            if gain>1.002:
                changed+=1
                out.append(audioop.mul(block,2,gain))
            else:out.append(block)
            gain_min=min(gain_min,gain);gain_max=max(gain_max,gain)
    rendered=b"".join(out)
    if len(rendered)!=len(pcm) or summary(rendered).peak>MAX_PEAK:
        return pcm,base
    after=[summary(rendered[i:i+FRAME_BYTES]).active_rms for i in range(0,len(rendered),FRAME_BYTES)]
    first=min(measures[i].active_rms for i in targets)
    last=min(after[i] for i in targets)
    if last<=first or changed==0:return pcm,base
    base.update(applied=1,quiet_windows=len(targets),min_before_rms=first,
                min_after_rms=last,peak_out=summary(rendered).peak)
    return rendered,base
