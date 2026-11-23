"""R138 opt-in stable short replies: verify *all* local Qwen PCM before speaker.

One real reference-voice generation and one physical codec; no provider request,
no disk recording, no second USB owner. More startup latency than streaming but
no synthesis starvation can occur during playback.
"""
from __future__ import annotations
import time
from app.h11_checked_tts import CheckedTTSError
from app.r32_streaming_tts_adapter import validated_stream_to_sink
from app.esp_pcm2_stream import PCM2Reply
from app.h10_usb_pcm_player import PCMTransportError

MAX_BUFFER_BYTES=48_000*180

def play_buffered_short(text,port,*,source=validated_stream_to_sink,
                        device_factory=PCM2Reply,on_started=None,
                        clock=time.monotonic):
    if not isinstance(text,str) or not 1<=len(text.strip())<=150:
        raise CheckedTTSError("TTS_STABLE_SHORT_TEXT_INVALID")
    chunks=[];total=0;peak=0;clipped=0
    def sink(pcm,sequence):
        nonlocal total,peak,clipped
        if not isinstance(pcm,bytes) or not pcm or len(pcm)%2:
            raise CheckedTTSError("TTS_STABLE_INVALID_PCM")
        total+=len(pcm)
        if total>MAX_BUFFER_BYTES:
            raise CheckedTTSError("TTS_STABLE_BUFFER_LIMIT")
        values=memoryview(pcm).cast('h')
        peak=max(peak,max(map(lambda v:abs(int(v)),values),default=0))
        clipped+=sum(abs(int(v))>=32760 for v in values)
        if clipped>128:raise CheckedTTSError("TTS_STABLE_EXCESSIVE_CLIPPING")
        chunks.append(pcm)
    began=clock()
    receipt=source(text,sink)
    if not receipt or receipt.completed is not True or not chunks:
        raise CheckedTTSError("TTS_STABLE_INCOMPLETE")
    # Keep Qwen's verified 24kHz PCM16 bit-exact. The old two-stage
    # nonlinear gain/compressor could flatten peaks even when input clipping=0.
    # Speaker hardware volume is unchanged; never add another gain stage.
    samples=b''.join(chunks)
    output=device_factory(port,on_started=on_started)
    try:
        output.start()
        send_began=clock()
        output.send(samples)
        physical=output.finish()
        if physical.get('pcm_written') is not True:
            raise PCMTransportError('pcm2_no_board_play_confirmation')
        return {'tts':receipt,'physical':physical,'chunks':len(chunks),
                'audio_telemetry':{'bytes':total,'peak':peak,
                    'clipped_samples':clipped,
                    'startup_audio_s':round(total/48000,3),
                    'send_max_s':round(clock()-send_began,3),
                    'fully_buffered':True,'tts_wait_s':round(send_began-began,3)}}
    except BaseException:
        output.cancel()
        raise
