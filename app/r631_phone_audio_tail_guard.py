"""R631: bounded silent DAC drain margin for final *phone* Wi-Fi speech.

Does not alter any original PCM sample, voice identity, volume, tempo or
internal Qwen phrase boundaries. Silence follows only the final phrase and
is part of the authenticated WSS frame count BEFORE verified EOS.
"""
from __future__ import annotations

HZ=24000
FRAME_MS=60
BYTES_PER_MS=HZ*2//1000
TARGET_SILENT_TAIL_MS=240
MAX_PAD_MS=240

def final_tail_padding(pcm:bytes, *, quiet_tail_ms:int,
                       target_ms:int=TARGET_SILENT_TAIL_MS)->bytes:
    if (not isinstance(pcm,bytes) or not pcm or len(pcm)%2 or
        type(quiet_tail_ms) is not int or quiet_tail_ms<0 or
        quiet_tail_ms>len(pcm)//BYTES_PER_MS or
        type(target_ms) is not int or not 0<=target_ms<=MAX_PAD_MS):
        raise ValueError("invalid_final_pcm_tail_metrics")
    missing=max(0,target_ms-quiet_tail_ms)
    # Only 60ms whole frames: no fractional WSS padding, no early EOS.
    pad_ms=min(MAX_PAD_MS,((missing+FRAME_MS-1)//FRAME_MS)*FRAME_MS)
    return bytes(pad_ms*BYTES_PER_MS)
