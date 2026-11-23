"""R441 voice continuity: bounded PCM silence repair and numeric-only QC.

Mono 24 kHz 16-bit LE, no user text or audio persisted. The repair removes
only unambiguously near-digital-silent pauses, not speech or ordinary breaths.
No DSP/voice-clone change outside these explicitly bounded repairs.
"""
from __future__ import annotations
from array import array
from dataclasses import dataclass
import math
import sys

SAMPLE_RATE=24000
BLOCK=240   # 10ms, aligned to the real 60ms WSS packet
SILENT_PEAK=220
SILENT_RMS=88

@dataclass(frozen=True)
class PcmSummary:
    duration_ms:int
    peak:int
    active_rms:int
    quiet_percent:int
    max_quiet_ms:int
    lead_quiet_ms:int
    tail_quiet_ms:int
    active_blocks:int

    def private_metrics(self)->dict[str,int]:
        return {"pcm_duration_ms":self.duration_ms,
                "pcm_peak":self.peak,
                "pcm_active_rms":self.active_rms,
                "pcm_quiet_percent":self.quiet_percent,
                "pcm_max_quiet_ms":self.max_quiet_ms,
                "pcm_lead_quiet_ms":self.lead_quiet_ms,
                "pcm_tail_quiet_ms":self.tail_quiet_ms}


def _samples(pcm:bytes)->array:
    if not isinstance(pcm,bytes) or len(pcm)%2:
        raise ValueError("pcm16le_mono_required")
    values=array("h")
    values.frombytes(pcm)
    if sys.byteorder!="little":
        values.byteswap()
    return values


def _quiet_windows(pcm:bytes)->tuple[array,list[bool],int,int,int]:
    values=_samples(pcm)
    flags=[];active_energy=0;active_count=0;peak=0
    for start in range(0,len(values),BLOCK):
        part=values[start:start+BLOCK]
        if len(part)!=BLOCK:
            break
        window_peak=max(abs(v) for v in part)
        peak=max(peak,window_peak)
        energy=sum(v*v for v in part)
        is_quiet=(window_peak<=SILENT_PEAK and
                  energy<=len(part)*SILENT_RMS*SILENT_RMS)
        flags.append(is_quiet)
        if not is_quiet:
            active_energy+=energy
            active_count+=len(part)
    return values,flags,peak,active_energy,active_count


def _runs(flags:list[bool]):
    begin=None
    for i,is_quiet in enumerate(flags):
        if is_quiet and begin is None:
            begin=i
        elif not is_quiet and begin is not None:
            yield begin,i
            begin=None
    if begin is not None:
        yield begin,len(flags)


def summary(pcm:bytes)->PcmSummary:
    values,flags,peak,active_energy,active_count=_quiet_windows(pcm)
    runs=list(_runs(flags))
    longest=max(((b-a)*10 for a,b in runs),default=0)
    lead=(runs[0][1]-runs[0][0])*10 if runs and runs[0][0]==0 else 0
    tail=(runs[-1][1]-runs[-1][0])*10 if runs and runs[-1][1]==len(flags) else 0
    return PcmSummary(
        duration_ms=len(values)*1000//SAMPLE_RATE,
        peak=peak,
        active_rms=round(math.sqrt(active_energy/max(1,active_count))),
        quiet_percent=round(100*sum(flags)/max(1,len(flags))),
        max_quiet_ms=longest,lead_quiet_ms=lead,tail_quiet_ms=tail,
        active_blocks=len(flags)-sum(flags))


def compress_excess_silence(pcm:bytes, *,
                            trigger_ms:int=1600,
                            keep_ms:int=500,
                            max_removed_ms:int=18000)->tuple[bytes,int,int]:
    """Shorten only strictly quiet windows > 1.6s, never nonquiet PCM.

    Threshold is per near-silent 10ms block. Preserve 0.5s of each internal
    gap and 0.2s at outer edges. Cap aggregate removal; avoid clicks by cutting
    *inside* proven near-zero windows. Does not trim arbitrary low-volume speech.
    """
    if trigger_ms<800 or keep_ms<200 or keep_ms>=trigger_ms:
        raise ValueError("invalid_pause_policy")
    values,flags,_,_,_=_quiet_windows(pcm)
    removed=0;spans=[];total_windows=len(flags)
    for start,end in _runs(flags):
        run_ms=(end-start)*10
        if run_ms<=trigger_ms:
            continue
        keep=(200 if start==0 or end==total_windows else keep_ms)//10
        extra=(end-start)-keep
        left=min(extra,max(0,(max_removed_ms-removed)//10))
        if left<=0:continue
        cut_start=start+(end-start-left)//2
        spans.append((cut_start*BLOCK,(cut_start+left)*BLOCK))
        removed+=left*10
    if not spans:return pcm,0,0
    out=array("h")
    cursor=0
    for a,b in spans:
        out.extend(values[cursor:a]);cursor=b
    out.extend(values[cursor:])
    if sys.byteorder!="little":out.byteswap()
    return out.tobytes(),removed,len(spans)


def match_phrase_level(pcm:bytes, previous_active_rms:int|None, *,
                       max_gain:float=1.12)->tuple[bytes,int]:
    """Conservatively reduce >2 dB phrase-to-phrase level jumps.

    Limits gain adjustment to 12%, protects samples from clipping and linearly
    ramps the first 120 ms so no new discontinuity is introduced.
    """
    if previous_active_rms is None or previous_active_rms<=0:
        return pcm,1000
    info=summary(pcm)
    if info.active_rms<=0 or info.peak<=0:
        return pcm,1000
    ratio=previous_active_rms/info.active_rms
    if 0.79<=ratio<=1.26:return pcm,1000
    gain=max(1/max_gain,min(max_gain,ratio))
    if gain>1:
        gain=min(gain,28400/max(1,info.peak))
    if abs(gain-1)<0.002:return pcm,1000
    values=_samples(pcm)
    ramp=min(len(values),SAMPLE_RATE*120//1000)
    for i,x in enumerate(values):
        alpha=min(1.0,i/max(1,ramp))
        values[i]=round(x*(1+(gain-1)*alpha))
    if sys.byteorder!="little":values.byteswap()
    return values.tobytes(),round(gain*1000)
