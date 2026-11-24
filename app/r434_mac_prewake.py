"""R434 isolated Mac-side prewake KWS. One authorized device, bounded PCM only.

No DSH, ASR, TTS, audio recording or second microphone owner. This service
is opt-in within the existing R268 WSS authenticated device gateway. KWS
recognition emits a short-lived single-use wake ticket, scoped to device.
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import secrets
import struct
import time
from pathlib import Path

from app.device_audio_frame import MIC_UPLINK, unpack_frame, AudioFrameError

R434_SOURCE="onboard_mic_prewake"
R434_PROTOCOL="dafeiyu-r434-kws-v1"
FRAME_BYTES=1920
FRAME_MS=60
MAX_FRAMES=9000  # 9 minutes per session; bounded reconnect required.
# R489: The paired board can hard power off without a WebSocket Close frame.
# Server-origin WS ping is disabled for ESP-IDF compatibility; without an
# *application-level PCM idle deadline* an orphaned WSS connection holds the
# single DSH/prewake owner until OS-level TCP keepalive (potentially hours).
# 12s is well above the 60ms PCM cadence and the 4s model frame deadline.
PREWAKE_IDLE_TIMEOUT_S=12.0
RESULT_TIMEOUT=4.0
TICKET_SECONDS=12
WORKER=Path("scripts/mac_r434_stream_kws_worker.js")
_NODE=os.environ.get("R434_NODE_BIN","/opt/homebrew/bin/node")

class PrewakeProtocolError(ValueError):pass

class R434MacPrewake:
    """Receipt-only prewake control; never creates an official DSH turn."""
    def __init__(self, *,worker=WORKER, clock=time.monotonic):
        self.worker=Path(worker)
        self.clock=clock
        self.pending={}  # one-time token, device and expiry (no secrets in logs)
        self.sessions=0
        self.hits=0
        self.last_frame_count=0
        self.total_pcm_frames=0
        self.loud_pcm_frames=0
        self.no_hit_sessions=0
        self.worker_errors=0
        self.last_worker_startup_ms=0
        self.last_hit_at_unix=0
        self.idle_reclaims=0  # sanitized count, no audio or user data
    def _prune(self):
        now=self.clock()
        for device, (_,expiry) in list(self.pending.items()):
            if expiry<=now:self.pending.pop(device,None)
    def consume_ticket(self,device,ticket):
        """On authenticated WSS new start, consume once, only for same device."""
        self._prune()
        item=self.pending.get(device)
        if (not item or not isinstance(ticket,str)
                or not secrets.compare_digest(ticket,item[0])):
            return False
        self.pending.pop(device,None)
        return True
    def _issue_ticket(self,device):
        self._prune()
        self.pending.pop(device,None)
        token=secrets.token_urlsafe(24)
        self.pending[device]=(token,self.clock()+TICKET_SECONDS)
        return token
    async def handle(self,ws,device,hello):
        if not (isinstance(hello,dict)
            and hello.get("type")=="prewake_hello" and hello.get("v")==2
            and hello.get("source")==R434_SOURCE
            and hello.get("device_id")==device
            and hello.get("client_id")==ws.request.headers.get("Client-Id")
            and hello.get("audio_params")=={
                "format":"pcm16le","uplink_hz":16000,
                "downlink_hz":24000,"channels":1,"frame_ms":60}):
            await ws.close(code=1008,reason="invalid_prewake_hello")
            return
        if not self.worker.is_file() or self.worker.is_symlink():
            await ws.close(code=1011,reason="kws_worker_unavailable")
            return
        proc=None;self.sessions+=1;self.last_frame_count=0
        hit_this_session=False
        worker_start=self.clock()
        stream_id=secrets.randbits(64) or 1
        session=secrets.token_urlsafe(18)
        next_seq=0
        env=dict(os.environ)
        runtime_sherpa=(Path.home()/"Library/Application Support/Deepseek-live"
                        /"runtime/dsh-cli/node_modules/sherpa-onnx-node")
        if runtime_sherpa.is_dir() and not env.get("DAFEIYU_SHERPA_MODULE"):
            env["DAFEIYU_SHERPA_MODULE"]=str(runtime_sherpa)
        try:
            proc=await asyncio.create_subprocess_exec(
                _NODE,str(self.worker),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,env=env)
            # Cold ONNX mmap/initialization can exceed a normal frame deadline.
            # Bound startup separately; frame processing remains fail-closed.
            first=await asyncio.wait_for(proc.stdout.readline(),12.0)
            if not first or json.loads(first).get("protocol")!="r434-kws-worker-v1":
                raise PrewakeProtocolError("worker_not_ready")
            self.last_worker_startup_ms=max(0,round(
                (self.clock()-worker_start)*1000))
            await ws.send(json.dumps({"type":"prewake_ack","v":2,
                "protocol":R434_PROTOCOL,"session_id":session,
                "stream_id":f"{stream_id:016x}","frame_ms":FRAME_MS,
                "sample_rate":16000},separators=(",",":")))
            # Using async-for without an idle deadline traps a stale owner
            # after an ESP32 cold reboot when protocol Ping is disabled.
            # Reclaim ONLY a prewake stream that sent no PCM for 12 seconds;
            # the official DSH conversation path is never timed out here.
            frames=aiter(ws)
            while True:
                try:
                    raw=await asyncio.wait_for(anext(frames),
                                               PREWAKE_IDLE_TIMEOUT_S)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    self.idle_reclaims+=1
                    await ws.close(code=1001,reason="prewake_idle_released")
                    return
                # R439: an explicit Mac App OFF closes an existing prewake
                # uplink within <=16 PCM frames (960ms), without touching an
                # official DSH turn or changing the physical microphone owner.
                if next_seq % 16 == 0:
                    from app.r439_persistent_prewake import decision
                    if decision() is False:
                        await ws.close(code=1000,reason="prewake_user_disabled")
                        return
                if (not isinstance(raw,bytes) or len(raw)!=16+FRAME_BYTES
                        or next_seq>=MAX_FRAMES):
                    raise PrewakeProtocolError("invalid_prewake_frame_length_or_limit")
                sid,seq,pcm=unpack_frame(raw,MIC_UPLINK)
                if sid!=stream_id or seq!=next_seq or len(pcm)!=FRAME_BYTES:
                    raise PrewakeProtocolError("invalid_stream_or_duplicate_or_gap")
                assert proc.stdin is not None and proc.stdout is not None
                proc.stdin.write(struct.pack("!II",seq,len(pcm))+pcm)
                await asyncio.wait_for(proc.stdin.drain(),RESULT_TIMEOUT)
                line=await asyncio.wait_for(proc.stdout.readline(),RESULT_TIMEOUT)
                if not line:
                    raise PrewakeProtocolError("kws_worker_exited")
                outcome=json.loads(line)
                if outcome.get("seq")!=seq or type(outcome.get("hit")) is not bool:
                    raise PrewakeProtocolError("kws_worker_invalid_reply")
                next_seq+=1;self.last_frame_count=next_seq
                self.total_pcm_frames+=1
                # R533 diagnostics: frame energy is a number, NEVER a recording.
                # It cannot infer whether someone intentionally spoke the
                # keyword; do not label non-hit frames as misses.
                from audioop import rms
                self.loud_pcm_frames+=int(rms(pcm,2)>=900)
                if outcome["hit"]:
                    token=self._issue_ticket(device)
                    hit_this_session=True
                    self.last_hit_at_unix=round(time.time())
                    self.hits+=1
                    # Issued only after real audio-stream inference. Not DSH.
                    await ws.send(json.dumps({"type":"prewake_hit","v":2,
                       "session_id":session,"wake_ticket":token,
                       "keyword":"ni_hao_da_fei_yu"},separators=(",",":")))
                    return
        except (PrewakeProtocolError, AudioFrameError, ValueError,TypeError,
                asyncio.TimeoutError, BrokenPipeError, ConnectionError):
            self.worker_errors+=1
            await ws.close(code=1008,reason="prewake_invalid_or_timeout")
        finally:
            if not hit_this_session and self.last_frame_count >= 10:
                self.no_hit_sessions+=1
            if proc is not None:
                if proc.returncode is None:proc.kill()
                try:await asyncio.wait_for(proc.wait(),timeout=2)
                except asyncio.TimeoutError:
                    pass
