"""R32 isolated Qwen streaming boundary.

Host-side candidate for a future continuous ESP PCM protocol. The existing
R29/H10 device buffers a whole <=12s segment, so NEVER route this directly
to its serial writer; it does not establish an on-device streaming feature.
"""
from __future__ import annotations
import base64
import binascii
import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Callable
from app.h11_checked_tts import CheckedTTSError, LOCAL_TTS, RATE, MAX_OUTPUT_SECONDS

@dataclass(frozen=True)
class StreamReceipt:
    chunks:int
    bytes_sent:int
    first_audio_s:float
    complete_s:float
    completed:bool

def validated_stream_to_sink(sentence:str,sink:Callable[[bytes,int],None],*,
                             opener=None,clock=time.monotonic)->StreamReceipt:
    """Deliver validated PCM *incrementally* with strict terminal success gate.

    On any failure after one PCM chunk the caller MUST cancel/stop the target
    speaker; successfully received partial sound does not count as a turn.
    """
    if not isinstance(sentence,str) or not 1<=len(sentence.strip())<=150 or not callable(sink):
        raise CheckedTTSError("TTS_INVALID_TEXT")
    opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req=urllib.request.Request(LOCAL_TTS+"/stream",
         data=json.dumps({"text":sentence},ensure_ascii=False).encode("utf-8"),
         method="POST",headers={"Content-Type":"application/json"})
    start=clock();first=None;started=False;completed=False;count=0;total=0
    try:
        response=opener.open(req,timeout=45)
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise CheckedTTSError("TTS_LOCAL_SERVER_UNAVAILABLE") from exc
    with response:
        for raw in response:
            try:event=json.loads(raw)
            except (ValueError,TypeError) as exc:raise CheckedTTSError("TTS_INVALID_STREAM_JSON") from exc
            if not isinstance(event,dict):raise CheckedTTSError("TTS_INVALID_EVENT")
            kind=event.get("type")
            if kind=="start":
                if started:raise CheckedTTSError("TTS_DUPLICATE_START")
                started=True
            elif kind=="audio":
                if not started or completed:raise CheckedTTSError("TTS_AUDIO_OUT_OF_ORDER")
                frames=event.get("frames")
                if type(frames) is not int or not 0<frames<=RATE*10 or event.get("rate")!=RATE:
                    raise CheckedTTSError("TTS_AUDIO_FORMAT_INVALID")
                try:pcm=base64.b64decode(event["pcm_b64"],validate=True)
                except (KeyError,TypeError,binascii.Error) as exc:
                    raise CheckedTTSError("TTS_AUDIO_BASE64_INVALID") from exc
                if len(pcm)!=frames*2:raise CheckedTTSError("TTS_AUDIO_LENGTH_MISMATCH")
                if "seq" in event and event["seq"]!=count+1:
                    raise CheckedTTSError("TTS_SEQUENCE_GAP")
                total+=len(pcm)
                if total>MAX_OUTPUT_SECONDS*RATE*2:raise CheckedTTSError("TTS_AUDIO_TOO_LONG")
                if first is None:first=round(clock()-start,3)
                # sink call occurs now, BEFORE HTTP end and before full audio completion
                sink(pcm,count+1)
                count+=1
            elif kind=="end":
                if not started or event.get("cancelled") or not count:
                    raise CheckedTTSError("TTS_CANCELLED_OR_EMPTY")
                completed=True
                break
            elif kind=="error":raise CheckedTTSError("TTS_WORKER_ERROR")
            else:raise CheckedTTSError("TTS_UNKNOWN_EVENT")
    if not completed or first is None:raise CheckedTTSError("TTS_INCOMPLETE_STREAM")
    return StreamReceipt(count,total,first,round(clock()-start,3),True)
