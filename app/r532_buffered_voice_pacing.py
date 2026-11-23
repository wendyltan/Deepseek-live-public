"""R532: optional pitch-preserving slight slow-down of COMPLETE R503 PCM.

Never used on streamed/in-flight frames, D10 short replies or USB, and never
generates partial output. FFmpeg is a local CPU tool; no audio is persisted.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

FFMPEG=Path("/opt/homebrew/bin/ffmpeg")
PCM_BYTES_PER_SEC=48000
MIN_PCM_SECONDS=5
SLOWDOWN=0.94
MAX_OUTPUT_BYTES=180*PCM_BYTES_PER_SEC


def soften_fast_r503(pcm:bytes, *, runner=subprocess.run) -> tuple[bytes,bool]:
    """Return full pitch-preserving PCM or original unchanged on any failure."""
    if not isinstance(pcm,bytes) or not pcm or len(pcm)%2:
        raise ValueError("r532_pcm16le_required")
    if len(pcm)<MIN_PCM_SECONDS*PCM_BYTES_PER_SEC or not FFMPEG.is_file():
        return pcm,False
    if len(pcm)*1.09>MAX_OUTPUT_BYTES:
        return pcm,False
    command=[str(FFMPEG),"-hide_banner","-loglevel","error","-nostdin",
             "-f","s16le","-ar","24000","-ac","1","-i","pipe:0",
             "-af",f"atempo={SLOWDOWN}",
             "-f","s16le","-ar","24000","-ac","1","pipe:1"]
    try:
        done=runner(command,input=pcm,stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,timeout=8,check=False)
    except (subprocess.TimeoutExpired,OSError):
        return pcm,False
    out=done.stdout
    if (done.returncode!=0 or not isinstance(out,bytes) or
        len(out)%2 or len(out)>MAX_OUTPUT_BYTES or
        not 1.025*len(pcm)<=len(out)<=1.09*len(pcm)):
        return pcm,False
    return out,True


def natural_spoken_punctuation(text:str) -> str:
    """Remove punctuation collisions from Markdown-to-voice conversion.

    Does not rewrite words, quantities or omit source evidence.
    """
    if not isinstance(text,str):raise ValueError("r532_spoken_requires_text")
    import re
    text=re.sub(r"([：:])\s*[；;]+",r"\1",text)
    text=re.sub(r"([。！？!?])\s*[；;]+",r"\1",text)
    text=re.sub(r"[；;]{2,}","；",text)
    # R536: long pest/feature lists generated from trustworthy DSH bullets
    # often race through six nouns with no breath. Keep ALL nouns, but a
    # semicolon before "还有" gives the same Qwen voice a real clause break.
    # This is punctuation only, NOT an extractive summary or a speed change.
    text=re.sub(r"(、[^，。！？；]{1,12})，还有",r"\1；还有",text)
    # A text-only sequence arrow is a step transition, not an instruction
    # for the TTS voice to pronounce a symbol or skip the next pause.
    text=re.sub(r"\s*[→⇒➜]\s*","，再",text)
    return text
