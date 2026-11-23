"""Verified localhost Qwen stream: typed failures, complete PCM and no silent retry.

Does not open any microphone or contact a paid model. A complete /stream end
is mandatory; dropped sockets cannot become a truncated 'successful' answer.
"""
from __future__ import annotations

import base64
import binascii
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

LOCAL_TTS = 'http://127.0.0.1:8906'
RATE = 24000
MAX_OUTPUT_SECONDS = 180

class CheckedTTSError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code=code

@dataclass(frozen=True)
class TTSResult:
    pcm: bytes
    first_pcm_s: float
    complete_s: float
    peak: int
    clipped_samples: int


def synthesize(sentence: str, *, endpoint=LOCAL_TTS,
               opener=None, clock=time.monotonic, on_audio=None) -> TTSResult:
    if not isinstance(sentence, str) or not 1 <= len(sentence.strip()) <= 150:
        raise CheckedTTSError('TTS_INVALID_TEXT')
    # Only the two fixed loopback ports are permissible. Never infer a
    # caller-controlled URL, external host or proxy from voice text.
    if endpoint not in (LOCAL_TTS,"http://127.0.0.1:8907"):
        raise CheckedTTSError('TTS_ENDPOINT_NOT_ALLOWED')
    if on_audio is not None and not callable(on_audio):
        raise CheckedTTSError('TTS_AUDIO_CALLBACK_REQUIRED')
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        endpoint+'/stream',
        data=json.dumps({'text':sentence},ensure_ascii=False).encode('utf-8'),
        method='POST', headers={'Content-Type':'application/json'})
    start=clock(); first=None; got_start=False; got_end=False
    pieces=[]; total=0; peak=0; clips=0
    try:
        with opener.open(request,timeout=45) as response:
            for raw in response:
                try:
                    event=json.loads(raw)
                except (ValueError,UnicodeDecodeError) as exc:
                    raise CheckedTTSError('TTS_INVALID_STREAM_JSON') from exc
                if not isinstance(event,dict):
                    raise CheckedTTSError('TTS_INVALID_EVENT')
                kind=event.get('type')
                if kind=='start':
                    if got_start:raise CheckedTTSError('TTS_DUPLICATE_START')
                    got_start=True
                elif kind=='audio':
                    if not got_start or got_end:
                        raise CheckedTTSError('TTS_AUDIO_OUT_OF_ORDER')
                    frames=event.get('frames')
                    if type(frames) is not int or frames <= 0 or frames>RATE*10 or event.get('rate')!=RATE:
                        raise CheckedTTSError('TTS_AUDIO_FORMAT_INVALID')
                    try:
                        pcm=base64.b64decode(event['pcm_b64'],validate=True)
                    except (KeyError,TypeError,binascii.Error) as exc:
                        raise CheckedTTSError('TTS_AUDIO_BASE64_INVALID') from exc
                    if len(pcm)!=frames*2:
                        raise CheckedTTSError('TTS_AUDIO_LENGTH_MISMATCH')
                    total+=len(pcm)
                    if total>MAX_OUTPUT_SECONDS*RATE*2:
                        raise CheckedTTSError('TTS_AUDIO_TOO_LONG')
                    if first is None:first=round(clock()-start,3)
                    mv=memoryview(pcm).cast('h')
                    peak=max(peak,max(abs(x) for x in mv))
                    clips+=sum(abs(x)>=32760 for x in mv)
                    pieces.append(pcm)
                    # The authenticated WSS consumer may release this *validated*
                    # PCM chunk immediately; /end is still required for success.
                    if on_audio is not None:
                        on_audio(pcm)
                elif kind=='error':
                    raise CheckedTTSError('TTS_WORKER_ERROR')
                elif kind=='end':
                    if not got_start or event.get('cancelled'):
                        raise CheckedTTSError('TTS_CANCELLED_OR_UNSTARTED')
                    got_end=True;break
                else:
                    raise CheckedTTSError('TTS_UNKNOWN_EVENT')
    except urllib.error.HTTPError as exc:
        if exc.code==503:raise CheckedTTSError('TTS_BUSY') from exc
        raise CheckedTTSError('TTS_HTTP_ERROR') from exc
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise CheckedTTSError('TTS_STREAM_INTERRUPTED') from exc
    if not got_end or not pieces or first is None:
        raise CheckedTTSError('TTS_INCOMPLETE_STREAM')
    return TTSResult(b''.join(pieces),first,round(clock()-start,3),peak,clips)
