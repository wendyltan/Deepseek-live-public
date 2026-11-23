"""R268 authenticated Wi-Fi PCM audio transport; reuse CompanionGateway identity gate.

Wire: existing DF packet envelope v2, PCM16LE 16k upstream / 24k downstream.
Audio is only accepted after explicit device start; official DSH is invoked
once after a bounded complete capture. Backpressure limits device PSRAM.
No endpoint is started by import; LAN binding requires caller-supplied TLS.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import secrets
import time
import threading
import concurrent.futures
import inspect
from collections import deque
from dataclasses import dataclass

from websockets.exceptions import ConnectionClosed
from app.companion_ws import CompanionGateway, payload
from app.device_audio_frame import (
    pack_frame, unpack_frame, AudioFrameError, MIC_UPLINK, SPEAKER_DOWNLINK,
)

UP_HZ=16000
DOWN_HZ=24000
FRAME_MS=60
UP_BYTES=UP_HZ*FRAME_MS//1000*2
DOWN_BYTES=DOWN_HZ*FRAME_MS//1000*2
MAX_MIC_FRAMES=333
MAX_PCM_SECONDS=180
WINDOW_FRAMES=12  # R441-capable board max; legacy R436 remains 8 until upgrade
LEGACY_WINDOW_FRAMES=8
AUDIO_SPEC={"format":"pcm16le","uplink_hz":UP_HZ,
            "downlink_hz":DOWN_HZ,"channels":1,"frame_ms":FRAME_MS}
# Physical R487 accepts exactly this legacy field in audio_offer.
# It is a codec/transport compatibility ID, *not* the synthesized voice.
# Always provide the true voice separately. The board ignores new fields.
R487_WIRE_PROFILE="dafeiyu-qwen3-d10"
ALLOWED_SYNTH_VOICES=frozenset((
    "dafeiyu-qwen3-d10","dafeiyu-r503-qwen06-long-trial"))


class LanGateError(ValueError):pass

@dataclass
class Playback:
    pcm: bytes
    frames: int
    stream_id: int
    playback_id: str
    source: str
    next_index: int=0
    acked: int=0
    started: bool=False
    first_pcm_confirmed: bool=False
    first_ack_delay_ms: int=0
    eos_sent: bool=False
    producer_finished: bool=True  # Legacy finite offer; R299 streams until validated EOS.
    started_at_mono: float=0.0
    last_ack_mono: float=0.0
    max_ack_gap_ms: int=0
    slow_ack_gaps: int=0
    ack_count: int=0
    max_frames_inflight: int=0
    comparison_armed: bool=False

class R268LanGateway:
    """Single authorized device, one turn at a time, real DSH injected backend.

    Caller must reuse the existing NativeDshCompanionSession and never create
    another official DSH Agent in this websocket handler.
    """
    def __init__(self, backend, device_tokens:dict, diagnostics=None, *,
                 incremental_enabled:bool=False,prewake_service=None):
        if not device_tokens:
            raise LanGateError("paired_device_required")
        self.backend=backend
        # Production rollout gate: even a capable board still uses legacy
        # fully-buffered v2 until the Mac owner explicitly enables R299.
        self.incremental_enabled=bool(incremental_enabled)
        # Explicit opt-in only. Prewake never becomes a second DSH owner.
        self.prewake_service=prewake_service
        # Reuse existing anti-replay + strict header cardinality/constant-time
        # bearer authentication; v2 lab/USB behavior is unchanged.
        self.auth=CompanionGateway("x"*24,device_tokens=device_tokens)
        self.active=set()
        self.handshaking=set()  # Reserve before the first awaited hello read.
        # An asyncio cancellation cannot stop a Python to_thread DSH request.
        # Keep per-device ownership until its actual worker has returned;
        # otherwise a reconnect can submit a second billable DSH turn.
        self.backend_jobs={}
        self.total_real_turns=0
        self.ui_phase='disconnected'  # Read-only, sanitized status for Mac UI.
        self.ui_phase_changed_at_unix=time.time()
        self._diagnostics=diagnostics if callable(diagnostics) else None

    def _trusted_reply_origin(self, source: str) -> bool:
        base=getattr(self.backend,"origin","test_fixture")
        if source==base:
            return True
        # A bound official DSH owner may additionally produce only its
        # specifically registered, read-only verified local-weather responses.
        # Never grant this exception to arbitrary fake/unbound backends.
        from app.r268_native_speech_backend import NativeSpeechBackend
        return (type(self.backend) is NativeSpeechBackend and
                base=="official_dsh_verified" and
                getattr(getattr(self.backend,"native",None),"bound",False) is True and
                source in self.backend.verified_local_origins)

    def _arm_actual_reply(self, target, playback, result):
        from app.r268_native_speech_backend import NativeSpeechBackend
        if type(self.backend) is not NativeSpeechBackend:
            return False
        from app.r499_reply_speech_comparison import bind_device_playback
        return bind_device_playback(
            self.backend.native,target,playback.playback_id,playback.frames,
            result.answer_origin,result.spoken_text_length)

    def _complete_actual_reply(self, target, playback):
        from app.r268_native_speech_backend import NativeSpeechBackend
        if type(self.backend) is not NativeSpeechBackend:
            return False
        from app.r499_reply_speech_comparison import confirm_device_playback
        return confirm_device_playback(
            self.backend.native,target,playback.playback_id,playback.frames)

    def _project_device_playback(self, *, started: bool):
        from app.r268_native_speech_backend import NativeSpeechBackend
        from app.native_dsh_companion_session import NativeDshCompanionSession
        from app.native_companion_projection import NativeCompanionProjector
        if not isinstance(self.backend, NativeSpeechBackend):return False
        native=self.backend.native
        if not isinstance(native, NativeDshCompanionSession) or not native.bound:return False
        projector=native.projector
        if not isinstance(projector, NativeCompanionProjector) or projector.turn_id is not None:return False
        try:
            projector.device_playback(started=started,verified=True)
            projector.write()
            return True
        except (OSError,ValueError):
            self._mark("native_playback_projection_failed")
            return False

    def _project_playback_interrupted(self):
        from app.r268_native_speech_backend import NativeSpeechBackend
        from app.native_dsh_companion_session import NativeDshCompanionSession
        from app.native_companion_projection import NativeCompanionProjector
        if type(self.backend) is not NativeSpeechBackend:return False
        native=self.backend.native
        if type(native) is not NativeDshCompanionSession or not native.bound:return False
        projector=native.projector
        if not isinstance(projector,NativeCompanionProjector) or projector.turn_id is not None:return False
        try:
            projector.state['voice_playback_verified']=False
            projector.record_step('error','语音传输已中断，未确认完整播放')
            projector.write()
            return True
        except (OSError,ValueError):
            self._mark('native_playback_projection_failed')
            return False

    def _set_ui_phase(self, phase: str):
        if phase!=self.ui_phase:
            self.ui_phase=phase
            self.ui_phase_changed_at_unix=time.time()

    def _mark(self, stage: str, **metrics):
        try:
            if self._diagnostics:
                self._diagnostics(stage, **metrics)
        except Exception:
            pass  # Never make diagnostics part of DSH, speaker or auth path.

    async def authorize(self, connection, request):
        return await self.auth.authorize(connection,request)

    async def handler(self, ws):
        device=ws.request.headers.get("Device-Id")
        # The reused official DSH Session is a single conversation owner,
        # even if a future configuration pairs more than one ESP device.
        pending=[t for t in self.backend_jobs.values() if not t.done()]
        if (device not in self.auth.device_tokens or self.active or self.handshaking or pending):
            await ws.close(code=1008,reason="unauthorized_or_duplicate_or_busy_device")
            return
        # An attacker or a second radio reconnect can hold the hello for
        # seconds. Claim the one allowed official DSH session synchronously,
        # before yielding to any await; release it on every failure path.
        self.handshaking.add(device)
        self._set_ui_phase('connecting')
        incremental_supported=False
        peer_window_frames=LEGACY_WINDOW_FRAMES
        peer_no_speech_terminal=False
        peer_local_origins=False
        try:
            first=await asyncio.wait_for(ws.recv(),timeout=6)
            hello=payload(first) if isinstance(first,str) else {}
            if hello.get("type")=="prewake_hello":
                # R439: read user's durable setting on each authenticated
                # prewake session. ON works even if the process started OFF;
                # OFF blocks new microphone uplinks without restarting DSH.
                from app.r439_persistent_prewake import decision
                persistent = decision()
                if persistent is False:
                    await ws.close(code=1008,reason="prewake_user_disabled")
                    return
                if persistent is True and self.prewake_service is None:
                    from app.r434_mac_prewake import R434MacPrewake
                    self.prewake_service=R434MacPrewake()
                if self.prewake_service is None:
                    await ws.close(code=1008,reason="prewake_disabled")
                    return
                self.handshaking.discard(device)
                self.active.add(device)
                self._set_ui_phase('prewake_streaming')
                try:
                    await self.prewake_service.handle(ws,device,hello)
                finally:
                    self.active.discard(device)
                    self._set_ui_phase('disconnected')
                return
            if (hello.get("type")!="hello" or hello.get("v")!=2 or
                hello.get("device_id")!=device or
                hello.get("client_id")!=ws.request.headers.get("Client-Id") or
                hello.get("audio_params")!=AUDIO_SPEC or
                hello.get("source")!="onboard_mic"):
                await ws.close(code=1008,reason="invalid_pcm_device_hello")
                return
            # R441: advertise a larger PCM receive ring only on the new
            # physical APP. An old R436 without this signed hello capability
            # keeps its original 8-frame backpressure; never overrun its ring.
            requested_window=hello.get("playback_window_frames",LEGACY_WINDOW_FRAMES)
            if type(requested_window) is not int or requested_window not in (
                    LEGACY_WINDOW_FRAMES,WINDOW_FRAMES):
                await ws.close(code=1008,reason="invalid_playback_window")
                return
            peer_window_frames=requested_window
            candidate_no_speech=hello.get("supports_no_speech_terminal",False)
            if type(candidate_no_speech) is not bool:
                await ws.close(code=1008,reason="invalid_no_speech_capability")
                return
            peer_no_speech_terminal=candidate_no_speech
            candidate_local_origins=hello.get("supports_verified_local_origins",False)
            if type(candidate_local_origins) is not bool:
                await ws.close(code=1008,reason="invalid_local_origin_capability")
                return
            peer_local_origins=candidate_local_origins
            # Explicit opt-in from the physical board. R296/earlier devices
            # remain on the original fully-buffered frame-count contract.
            incremental_supported=(self.incremental_enabled and
                                  hello.get("supports_incremental_audio") is True and
                                  callable(getattr(self.backend,"process_stream",None)))
        except (ValueError,TypeError,asyncio.TimeoutError,ConnectionClosed):
            await ws.close(code=1008,reason="invalid_hello")
            return
        finally:
            self.handshaking.discard(device)
        self.active.add(device)
        self._set_ui_phase('idle')
        session=secrets.token_urlsafe(18)
        phase="idle";turn_id=None;stream_id=0
        chunks=[];capture_origin=None;playback=None
        processing=None;cancelled=set()
        send_lock=asyncio.Lock()
        window_lock=asyncio.Lock()
        async def send(typ,**fields):
            async with send_lock:
                await ws.send(json.dumps({"type":typ,"session_id":session,**fields},
                                         separators=(",",":"),ensure_ascii=False))
        async def error(code):
            await send("error",code=code)
        async def send_window():
            nonlocal playback
            async with window_lock:
                active=playback
                if active is None:return
                while active.next_index<active.frames and (
                    active.next_index-active.acked < peer_window_frames):
                    if active is not playback:return  # Cancelled between sends.
                    i=active.next_index
                    part=active.pcm[i*DOWN_BYTES:(i+1)*DOWN_BYTES]
                    payload_bytes=part.ljust(DOWN_BYTES,b"\0")
                    async with send_lock:
                        await ws.send(pack_frame(SPEAKER_DOWNLINK,active.stream_id,i,payload_bytes))
                    active.next_index+=1
                    active.max_frames_inflight=max(
                        active.max_frames_inflight,active.next_index-active.acked)
                # Never send the dynamic EOS before the last phrase has been
                # synthesized, verified and its frames fully submitted.
                if (active is playback and active.producer_finished and
                    active.next_index==active.frames and not active.eos_sent):
                    active.eos_sent=True
                    await send("audio_eos",turn_id=turn_id,playback_id=active.playback_id,
                               frames=active.frames,
                               valid_samples_last_frame=(
                                   (len(active.pcm)//2-1)% (DOWN_BYTES//2)+1),
                               source_pcm_samples=len(active.pcm)//2)

        async def run_answer(audio:bytes, origin:str, target:str):
            nonlocal phase,playback,processing
            self._mark("backend_started",input_pcm_bytes=len(audio))
            # Keep an authenticated WSS session responsive while actual local
            # ASR/DSH/Qwen TTS runs in a worker. No transcript/PCM in ping.
            # ESP accepts state frames while in stage 11; a 2-second cadence
            # avoids a silent read window on some ESP TLS transports.
            async def pending_state_pulse():
                try:
                    while True:
                        await asyncio.sleep(2)
                        if (producer_finished or phase not in ("processing","streaming")
                            or target!=turn_id or target in cancelled):
                            return
                        await send("state",state=("processing" if phase=="processing"
                                                  else "voice_generating"),turn_id=target)
                        self._mark("processing_ping_sent")
                except (ConnectionClosed, OSError):
                    return
            producer_finished=False
            pulse=asyncio.create_task(pending_state_pulse())
            try:
                # Every authenticated DSH turn has exactly one thread owner.
                # A streaming board gets bounded phrase PCM while the same
                # worker synthesizes later phrases; older boards take v2.
                streaming=incremental_supported
                stop_source=threading.Event()
                loop=asyncio.get_running_loop()
                pcm_queue=asyncio.Queue(maxsize=4)
                # Per-turn immutable-before-first-PCM provenance. The
                # authenticated owner remains official DSH; a tool source
                # must be separately labeled before any audio_offer.
                selected_source={"value":getattr(self.backend,"origin","test_fixture")}
                selected_voice={"value":R487_WIRE_PROFILE}
                def on_voice_profile(profile):
                    if profile not in ALLOWED_SYNTH_VOICES:
                        raise LanGateError("untrusted_streamed_voice_profile")
                    # A declared voice may change only before the audio offer
                    # (R505 first-phrase failure can fall back to D10).
                    if playback is not None:
                        raise LanGateError("voice_profile_change_after_pcm_offer")
                    selected_voice["value"]=profile
                def on_origin(src):
                    if not self._trusted_reply_origin(src):
                        raise LanGateError("untrusted_local_answer_origin")
                    selected_source["value"]=src
                if streaming:
                    def on_pcm(piece):
                        if stop_source.is_set():
                            raise LanGateError("streaming_consumer_cancelled")
                        if not isinstance(piece,bytes) or not piece or len(piece)%2:
                            raise LanGateError("invalid_streamed_d10_piece")
                        # A bounded cross-thread queue enforces backpressure.
                        future=asyncio.run_coroutine_threadsafe(pcm_queue.put(piece),loop)
                        while True:
                            try:
                                future.result(timeout=.25)
                                break
                            except concurrent.futures.TimeoutError:
                                if stop_source.is_set():
                                    future.cancel()
                                    raise LanGateError("streaming_consumer_cancelled")
                    stream_kwargs={"origin":origin,"turn_id":target,"on_pcm":on_pcm}
                    if "on_voice_profile" in inspect.signature(
                            self.backend.process_stream).parameters:
                        stream_kwargs["on_voice_profile"]=on_voice_profile
                    # Existing fake/legacy streaming backends still support
                    # their original 1-argument on_pcm contract.
                    if "on_origin" in inspect.signature(
                            self.backend.process_stream).parameters:
                        stream_kwargs["on_origin"]=on_origin
                    if "allow_verified_local_origin" in inspect.signature(
                            self.backend.process_stream).parameters:
                        stream_kwargs["allow_verified_local_origin"]=peer_local_origins
                    if "cancel_requested" in inspect.signature(
                            self.backend.process_stream).parameters:
                        stream_kwargs["cancel_requested"]=stop_source.is_set
                    worker=asyncio.create_task(asyncio.to_thread(
                        self.backend.process_stream,audio,**stream_kwargs))
                else:
                    backend_kwargs={"origin":origin,"turn_id":target}
                    if "allow_verified_local_origin" in inspect.signature(
                            self.backend.process).parameters:
                        backend_kwargs["allow_verified_local_origin"]=peer_local_origins
                    if "cancel_requested" in inspect.signature(
                            self.backend.process).parameters:
                        backend_kwargs["cancel_requested"]=stop_source.is_set
                    worker=asyncio.create_task(asyncio.to_thread(
                        self.backend.process,audio,**backend_kwargs))
                self.backend_jobs[device]=worker
                def settled(task):
                    if self.backend_jobs.get(device) is task:
                        self.backend_jobs.pop(device,None)
                    if target in cancelled:
                        self._project_playback_interrupted()
                    try:task.exception()
                    except asyncio.CancelledError:pass
                worker.add_done_callback(settled)
                if streaming:
                    total_bytes=0
                    while not (worker.done() and pcm_queue.empty()):
                        if target in cancelled or target!=turn_id:
                            raise LanGateError("stream_cancelled")
                        try:
                            piece=await asyncio.wait_for(pcm_queue.get(),timeout=.2)
                        except asyncio.TimeoutError:
                            continue
                        total_bytes+=len(piece)
                        if total_bytes>MAX_PCM_SECONDS*DOWN_HZ*2:
                            raise LanGateError("too_long_streamed_tts")
                        if playback is None:
                            expected=selected_source["value"]
                            if not self._trusted_reply_origin(expected):
                                raise LanGateError("untrusted_audio_offer_origin")
                            playback=Playback(piece,len(piece)//DOWN_BYTES,
                                secrets.randbits(64) or 1,secrets.token_urlsafe(12),
                                expected,producer_finished=False)
                            phase="streaming"
                            self._set_ui_phase('audio_ready')
                            await send("state",state="voice_generating",turn_id=target)
                            await send("audio_offer",turn_id=target,
                                playback_id=playback.playback_id,
                                stream_id=f"{playback.stream_id:016x}",frames=0,
                                incremental=True,hz=DOWN_HZ,frame_ms=FRAME_MS,
                                voice_profile_id=R487_WIRE_PROFILE,
                                synthesis_voice_profile_id=selected_voice["value"],
                                answer_origin=expected)
                            self._mark("audio_offer_sent",audio_frames=0,
                                       incremental=1,first_pcm_bytes=len(piece))
                        else:
                            playback.pcm+=piece
                            playback.frames=len(playback.pcm)//DOWN_BYTES
                        await send_window()
                    result=await asyncio.shield(worker)
                    if not getattr(result,"buffered",False):
                        # Never accept a half-produced answer as a finished stream.
                        if (not playback or playback.pcm!=result.pcm or
                            len(playback.pcm)!=total_bytes):
                            raise LanGateError("incremental_pcm_final_mismatch")
                        if (result.answer_origin!=selected_source["value"] or
                            not self._trusted_reply_origin(result.answer_origin) or
                            result.voice_profile_id not in ALLOWED_SYNTH_VOICES or
                            result.voice_profile_id!=selected_voice["value"]):
                            raise LanGateError("untrusted_streamed_answer")
                        playback.producer_finished=True
                        playback.frames=math.ceil(len(playback.pcm)/DOWN_BYTES)
                        playback.comparison_armed=self._arm_actual_reply(target,playback,result)
                        producer_finished=True
                        self._mark("pcm_ready",pcm_bytes=len(playback.pcm),
                                   audio_frames=playback.frames,incremental=1)
                        await send_window()
                        self.total_real_turns+=int(result.answer_origin=="official_dsh_verified")
                        return
                    if playback is not None or total_bytes:
                        raise LanGateError("buffered_reply_emitted_early_pcm")
                    if (result.answer_origin!=selected_source["value"] or
                        result.voice_profile_id!=selected_voice["value"]):
                        raise LanGateError("untrusted_buffered_answer")
                else:
                    result=await asyncio.shield(worker)
                if target in cancelled or phase!="processing" or target!=turn_id:
                    return
                pcm=result.pcm
                if not isinstance(pcm,bytes) or not pcm or len(pcm)%2:
                    raise LanGateError("invalid_tts_pcm")
                if len(pcm)>MAX_PCM_SECONDS*DOWN_HZ*2:
                    raise LanGateError("too_long_tts")
                # A test backend must never be advertised as an official DSH answer.
                expected=result.answer_origin
                if not self._trusted_reply_origin(expected):
                    raise LanGateError("untrusted_answer_origin")
                if result.voice_profile_id not in ALLOWED_SYNTH_VOICES:
                    raise LanGateError("untrusted_synthesis_voice_profile")
                frames=math.ceil(len(pcm)/DOWN_BYTES)
                self._mark("pcm_ready",pcm_bytes=len(pcm),audio_frames=frames)
                playback=Playback(pcm,frames,secrets.randbits(64) or 1,
                                  secrets.token_urlsafe(12),expected)
                playback.comparison_armed=self._arm_actual_reply(target,playback,result)
                phase="streaming"
                self._set_ui_phase('audio_ready')
                await send("state",state="voice_generating",turn_id=target)
                await send("audio_offer",turn_id=target,playback_id=playback.playback_id,
                           stream_id=f"{playback.stream_id:016x}",frames=frames,
                           hz=DOWN_HZ,frame_ms=FRAME_MS,
                           voice_profile_id=R487_WIRE_PROFILE,
                           synthesis_voice_profile_id=result.voice_profile_id,
                           answer_origin=result.answer_origin)
                self._mark("audio_offer_sent",audio_frames=frames,
                           candidate_voice=int(result.voice_profile_id!=R487_WIRE_PROFILE))
                await send_window()
                self._mark("window_sent",frames_sent=playback.next_index)
                self.total_real_turns+=int(expected=="official_dsh_verified")
            except (Exception,) as exc:
                from app.stt_local import NoSpeechDetected
                if (peer_no_speech_terminal and
                        isinstance(exc,NoSpeechDetected) and origin=="wake"
                        and phase=="processing" and playback is None
                        and target==turn_id and target not in cancelled):
                    # Only actual local Whisper VAD's no-speech outcome.
                    # No paid DSH turn, no fabricated audio. R461 board
                    # validates this same-session, same-turn terminal marker.
                    self._mark("r461_no_speech_returned",no_speech=1)
                    phase="idle"
                    self._set_ui_phase("idle")
                    await send("no_speech",turn_id=target,reason="vad_no_speech")
                else:
                    self._mark("backend_failed",error_kind=type(exc).__name__,
                               error_code=getattr(exc,"code",""))
                    if phase in ("processing","streaming") and target==turn_id and target not in cancelled:
                        phase="idle"
                        self._set_ui_phase('error')
                        self._project_playback_interrupted()
                        await error("backend_"+type(exc).__name__)
            finally:
                # A cancelled queue consumer must not block the thread and
                # monopolize the official DSH session forever.
                if 'stop_source' in locals():stop_source.set()
                producer_finished=True
                pulse.cancel()
                processing=None

        try:
            await send("hello_ack",v=2,protocol="dafeiyu-r268-pcm16-v2",
                       session_verified=(getattr(self.backend,"origin",None)=="official_dsh_verified"),device_id=device,
                       backend=getattr(self.backend,"origin","test_fixture"),
                       transport="wifi_pcm16",uplink_hz=UP_HZ,downlink_hz=DOWN_HZ,
                       frame_ms=FRAME_MS,window_frames=peer_window_frames)
            self._mark("wss_hello_verified")
            async for raw in ws:
                try:
                    if isinstance(raw,bytes):
                        if phase!="listening" or turn_id is None:
                            raise LanGateError("audio_outside_listening")
                        stream,index,pcm=unpack_frame(raw,MIC_UPLINK)
                        if stream!=stream_id or index!=len(chunks):
                            raise LanGateError("stale_or_out_of_order_mic")
                        if len(pcm)!=UP_BYTES or len(chunks)>=MAX_MIC_FRAMES:
                            raise LanGateError("invalid_pcm_frame_or_limit")
                        chunks.append(pcm)
                        continue
                    msg=payload(raw)
                    if msg.get("session_id")!=session:
                        raise LanGateError("session_mismatch")
                    typ=msg.get("type")
                    if typ=="heartbeat":
                        await send("heartbeat_ack",state=phase)
                    elif typ=="start":
                        candidate=msg.get("turn_id")
                        source=msg.get("origin")
                        pending=self.backend_jobs.get(device)
                        if phase!="idle" or processing or (pending and not pending.done()) or not isinstance(candidate,str) or (
                            re.fullmatch(r"[A-Za-z0-9_-]{8,64}",candidate) is None) or (
                            source not in ("wake","touch")):
                            raise LanGateError("invalid_or_busy_start")
                        # With prewake explicitly enabled, an authenticated
                        # microphone KWS hit is required for *every* wake turn.
                        # The ticket is single-use, device-bound and expires;
                        # touch capture retains the original behavior.
                        if source=="wake" and self.prewake_service is not None:
                            if not self.prewake_service.consume_ticket(
                                    device,msg.get("wake_ticket")):
                                raise LanGateError("missing_or_replayed_prewake_ticket")
                        # Existing CompanionGateway anti-replay protects reconnects.
                        self.auth.reserve_turn(candidate)
                        turn_id=candidate;capture_origin=source
                        stream_id=secrets.randbits(64) or 1;chunks=[]
                        phase="listening";playback=None
                        self._set_ui_phase('recording')
                        await send("state",state="listening",turn_id=turn_id,
                                   capture_stream_id=f"{stream_id:016x}")
                        self._mark("recording_started")
                    elif typ=="finish":
                        if phase!="listening" or msg.get("turn_id")!=turn_id or not chunks:
                            raise LanGateError("invalid_finish")
                        if len(chunks)*FRAME_MS>20000:
                            raise LanGateError("capture_duration_exceeded")
                        input_frames=len(chunks)
                        complete=b"".join(chunks);chunks=[]
                        self._mark("capture_submitted",input_frames=input_frames,
                                   input_pcm_bytes=len(complete))
                        phase="processing"
                        self._set_ui_phase('processing')
                        await send("state",state="transcribing",turn_id=turn_id)
                        processing=asyncio.create_task(run_answer(complete,capture_origin,turn_id))
                    elif typ=="playback_started":
                        if (phase!="streaming" or not playback or
                            msg.get("turn_id")!=turn_id or
                            msg.get("playback_id")!=playback.playback_id or playback.started):
                            raise LanGateError("invalid_playback_started")
                        # Legacy R511 sends playback_started after opening
                        # the codec, BEFORE its first physical write. Do not
                        # turn on Mac speaking lips on this premature event.
                        # The first authenticated audio_progress proves one
                        # complete 60ms PCM write; R550 board firmware will
                        # also defer its local speaking phase until then.
                        playback.started=True
                        playback.started_at_mono=time.monotonic()
                        playback.last_ack_mono=playback.started_at_mono
                        self._set_ui_phase('speaking')
                        await send("state",state="speaking",turn_id=turn_id)
                        self._mark("device_playback_started")
                    elif typ=="audio_progress":
                        if (phase!="streaming" or not playback or not playback.started or
                            msg.get("playback_id")!=playback.playback_id or
                            msg.get("turn_id")!=turn_id):
                            raise LanGateError("invalid_progress")
                        played=msg.get("played_frames")
                        if (type(played) is not int or
                            played<=playback.acked or played>playback.next_index):
                            raise LanGateError("invalid_progress_count")
                        now=time.monotonic()
                        if playback.last_ack_mono:
                            elapsed_ms=max(0,int((now-playback.last_ack_mono)*1000))
                            playback.max_ack_gap_ms=max(
                                playback.max_ack_gap_ms,elapsed_ms)
                            if elapsed_ms>=250:
                                playback.slow_ack_gaps+=1
                        playback.last_ack_mono=now
                        playback.ack_count+=1
                        playback.acked=played
                        if not playback.first_pcm_confirmed:
                            playback.first_pcm_confirmed=True
                            playback.first_ack_delay_ms=max(
                                0,int((now-playback.started_at_mono)*1000))
                            self._project_device_playback(started=True)
                            self._mark("r550_first_codec_pcm_confirmed",
                                       delay_ms=playback.first_ack_delay_ms)
                        await send_window()
                    elif typ=="playback_finished":
                        if (phase!="streaming" or not playback or
                            msg.get("playback_id")!=playback.playback_id or
                            msg.get("turn_id")!=turn_id or not playback.started or
                            msg.get("played_frames")!=playback.frames or
                            playback.acked!=playback.frames):
                            raise LanGateError("incomplete_physical_playback_receipt")
                        await send("playback_report",turn_id=turn_id,
                                   playback_id=playback.playback_id,
                                   reported_by="paired_esp32",
                                   actual_speaker_playback_human_verified=False)
                        self._mark("audio_playback_health",
                                   max_ack_gap_ms=playback.max_ack_gap_ms,
                                   slow_ack_gaps=playback.slow_ack_gaps,
                                   ack_count=playback.ack_count,
                                   max_frames_inflight=playback.max_frames_inflight,
                                   first_ack_delay_ms=playback.first_ack_delay_ms,
                                   playback_elapsed_ms=max(0,int(
                                       (time.monotonic()-playback.started_at_mono)*1000)),
                                   playback_completed=1,
                                   frames_expected=playback.frames,
                                   frames_acked=playback.acked,
                                   frames_submitted=playback.next_index)
                        self._project_device_playback(started=False)
                        self._mark("device_playback_finished",frames_played=playback.frames)
                        if playback.comparison_armed:
                            if self._complete_actual_reply(turn_id,playback):
                                self._mark("r502_device_pcm_completed",frames=playback.frames)
                        phase="idle";turn_id=None;playback=None
                        self._set_ui_phase('idle')
                    elif typ=="cancel":
                        if turn_id is None or msg.get("turn_id")!=turn_id or phase=="idle":
                            raise LanGateError("invalid_cancel")
                        cancelled.add(turn_id);phase="idle";turn_id=None
                        self._set_ui_phase('idle')
                        chunks=[];playback=None
                        self._project_playback_interrupted()
                        await send("cancel_ack",state="idle",reason="playback_cancelled",
                                   upstream_model_call_may_have_completed=True)
                    else:
                        raise LanGateError("unknown_control")
                except (LanGateError,AudioFrameError,ValueError,TypeError) as exc:
                    self._mark("gateway_protocol_error",error_kind=type(exc).__name__)
                    self._set_ui_phase('error')
                    await error(type(exc).__name__+":"+str(exc)[:66])
        except ConnectionClosed:
            pass
        finally:
            close_code=getattr(ws,"close_code",None)
            if playback is not None and playback.started and playback.started_at_mono:
                self._mark("audio_playback_health",
                           max_ack_gap_ms=playback.max_ack_gap_ms,
                           slow_ack_gaps=playback.slow_ack_gaps,
                           ack_count=playback.ack_count,
                           max_frames_inflight=playback.max_frames_inflight,
                           first_ack_delay_ms=playback.first_ack_delay_ms,
                           playback_elapsed_ms=max(0,int(
                               (time.monotonic()-playback.started_at_mono)*1000)),
                           playback_completed=0,
                           frames_expected=playback.frames,
                           frames_acked=playback.acked,
                           frames_submitted=playback.next_index)
            backend_pending=int(any(not job.done() for job in
                                    self.backend_jobs.values()))
            self._mark("wss_closed",close_code=close_code,
                       pending_backend=backend_pending)
            if turn_id is not None and phase in ("processing","streaming"):
                cancelled.add(turn_id)
                self._project_playback_interrupted()
            chunks.clear();playback=None
            if processing is not None:processing.cancel()
            self.active.discard(device)
            self._set_ui_phase('disconnected')
