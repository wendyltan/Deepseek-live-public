"""Pitch-preserving, local-only mild speech tempo increase for ESP PCM.

Only edits an already completely verified 24kHz mono signed16 TTS result.
Never generates/approves text or calls any remote service. Fails closed if
ffmpeg exits unsuccessfully; full PCM remains the authoritative source.
"""
from __future__ import annotations
import shutil
import subprocess
import os

class AudioTempoError(RuntimeError):pass

def adapt_pcm(pcm:bytes,*,rate:float=1.12,ffmpeg:str|None=None)->bytes:
    if not isinstance(pcm,bytes) or not pcm or len(pcm)%2 or len(pcm)>24_000*2*180:
        raise AudioTempoError('invalid_verified_pcm')
    if rate==1.0:return pcm
    if rate!=1.12:raise AudioTempoError('only_reviewed_tempos_supported')
    # Desktop-launched processes do not inherit Homebrew's interactive PATH.
    allowed=('/opt/homebrew/bin/ffmpeg','/usr/local/bin/ffmpeg')
    binary=ffmpeg or shutil.which('ffmpeg') or next((x for x in allowed if os.path.isfile(x) and os.access(x,os.X_OK)),None)
    if not binary:raise AudioTempoError('ffmpeg_unavailable')
    cmd=[binary,'-hide_banner','-loglevel','error',
         '-f','s16le','-ar','24000','-ac','1','-i','pipe:0',
         '-af','atempo=1.12','-f','s16le','-ar','24000','-ac','1','pipe:1']
    try:
        result=subprocess.run(cmd,input=pcm,stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,timeout=35,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise AudioTempoError('local_tempo_processor_unavailable') from exc
    out=result.stdout
    if result.returncode!=0 or not out or len(out)%2 or len(out)>len(pcm)*2:
        raise AudioTempoError('local_tempo_output_unverified')
    return out
