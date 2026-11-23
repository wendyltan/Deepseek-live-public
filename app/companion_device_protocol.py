"""Experimental ESP32 v2 wire contract over the existing CompanionGateway.

Only the server may generate state/Opus playback offers. The offline fixture is
never a Harness, a real speech engine, or proof of acoustic playback.
No background microphone, paid API, remote tool execution, or open LAN binding.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from array import array

from websockets.exceptions import ConnectionClosed
from app.companion_events import CompanionState, CompanionEventError
from app.companion_ws import MAX_FRAMES, payload
from app.opus_codec import OpusCodec, OpusError, UPSTREAM_RATE, DOWNSTREAM_RATE, upsample_16k_to_24k
from app.device_audio_frame import (AudioFrameError, MIC_UPLINK, SPEAKER_DOWNLINK,
                                    pack_frame, unpack_frame)

SAMPLE_FRAME_MS = 60
MAX_PLAYBACK_PACKETS = 8  # small bounded test fixture, not a production TTS budget


async def handle_device_v2(gateway, ws):
    """Authenticated *offline-lab* device session sharing the existing guard."""
    state = CompanionState()
    mic_frames = []
    turn = None
    playback_id = None
    playback_count = 0
    playback_started = False
    capture_stream = None
    session = secrets.token_urlsafe(18)
    device = None
    owned = False
    decoder = None
    encoder = None

    async def send(kind: str, **fields):
        await ws.send(json.dumps({"type": kind, "session_id": session, **fields},
                                 ensure_ascii=False, separators=(",", ":")))

    async def report_state():
        await send("state", state=state.state, turn_id=state.turn_id,
                   seq=state.last_seq, audio_level=state.audio_level,
                   capture_stream_id=f"{capture_stream:016x}" if state.state == "listening" else None,
                   playback_reported=playback_started)

    async def report_error(code: str):
        # Stable machine-readable codes, no audio, tokens, user-controlled text or stack traces.
        await send("error", code=code)

    def accept(event, seq=None, **extras):
        # Caller is the trusted Gateway lifecycle, never JSON from a device.
        return state.accept({"v": 1, "event": event, "turn_id": turn,
                             "seq": state.last_seq + 1 if seq is None else seq, **extras})

    try:
        first = await asyncio.wait_for(ws.recv(), 5)
        hello = payload(first) if isinstance(first, str) else {}
        device = ws.request.headers.get("Device-Id")
        client = ws.request.headers.get("Client-Id")
        requested = hello.get("audio_params")
        if (hello.get("type") != "hello" or type(hello.get("v")) is not int
            or hello["v"] != 2 or hello.get("device_id") != device
            or hello.get("client_id") != client
            or not isinstance(requested, dict)
            or requested != {"format": "opus", "uplink_hz": 16000,
                             "downlink_hz": 24000, "channels": 1, "frame_ms": 60}):
            await ws.close(code=1008, reason="unsupported device hello")
            return
        if device in gateway.active_devices:
            await ws.close(code=1008, reason="device already connected")
            return
        gateway.active_devices.add(device)
        owned = True
        decoder = OpusCodec(UPSTREAM_RATE, "decode")
        encoder = OpusCodec(DOWNSTREAM_RATE, "encode")
        await send("hello_ack", v=2, protocol="dafeiyu-device-lab-v1",
                   device_id=device, state="idle", opus=True, mcp=False,
                   backend="offline-fixture" if gateway.offline_fixture else "not_connected",
                   actual_speaker_playback=False)

        async for data in ws:
            try:
                if isinstance(data, bytes):
                    if state.state != "listening" or not turn:
                        await report_error("audio_outside_capture")
                        continue
                    if len(mic_frames) >= MAX_FRAMES:
                        await report_error("audio_frame_limit")
                        continue
                    try:
                        stream_id, index, compressed = unpack_frame(data, MIC_UPLINK)
                    except AudioFrameError:
                        await report_error("invalid_audio_frame")
                        continue
                    if stream_id != capture_stream or index != len(mic_frames):
                        await report_error("stale_or_out_of_order_audio")
                        continue
                    mic_frames.append(decoder.decode(compressed))
                    continue

                msg = payload(data)
                if msg.get("session_id") != session:
                    await report_error("session_mismatch")
                    continue
                kind = msg.get("type")
                if kind == "heartbeat":
                    await send("heartbeat_ack", state=state.state, turn_id=state.turn_id)
                elif kind == "start":
                    candidate = msg.get("turn_id")
                    if state.state != "idle":
                        await report_error("busy")
                        continue
                    if isinstance(candidate, str) and candidate in gateway.seen_ids:
                        await report_error("turn_replay")
                        continue
                    # Validation belongs to the shared verified CompanionState, not a second reducer.
                    state.accept({"v": 1, "event": "mic_started", "turn_id": candidate, "seq": 1})
                    gateway.reserve_turn(candidate)
                    turn = candidate
                    mic_frames.clear()
                    capture_stream = secrets.randbits(64) or 1
                    playback_id, playback_count, playback_started = None, 0, False
                    await report_state()
                elif kind == "finish":
                    if (msg.get("turn_id") != turn or state.state != "listening"
                        or not mic_frames):
                        await report_error("invalid_finish")
                        continue
                    accept("mic_stopped")
                    capture_stream = None
                    await report_state()  # transcribing; not fake 'speaking'
                    await send("audio_rx", turn_id=turn, frames=len(mic_frames),
                               sample_rate=16000, actual_mic=False)
                    if not gateway.offline_fixture:
                        # Future official DSH integration must own all subsequent events.
                        continue
                    accept("stt_completed")
                    await report_state()
                    accept("llm_completed")
                    await report_state()
                    accept("tts_ready")
                    await report_state()  # voice_generating, no mouth
                    if gateway.offline_pcm_frames is not None:
                        # Real local model data, but entirely a virtual-device lab.
                        # Mic uplink is still synthetic; it never goes to paid DSH.
                        encoded = [encoder.encode(array("h",pcm)) for pcm in gateway.offline_pcm_frames]
                        fixture_source = "local-qwen-fixture"
                    else:
                        samples = mic_frames[:MAX_PLAYBACK_PACKETS]
                        encoded = [encoder.encode(upsample_16k_to_24k(pcm)) for pcm in samples]
                        fixture_source = "offline-fixture"
                    mic_frames.clear()
                    playback_id = secrets.token_urlsafe(12)
                    playback_count = len(encoded)
                    playback_stream = secrets.randbits(64) or 1
                    await send("audio_offer", turn_id=turn, playback_id=playback_id,
                               stream_id=f"{playback_stream:016x}",
                               frames=playback_count, hz=24000, frame_ms=60,
                               source=fixture_source, actual_speaker_playback=False)
                    for index, packet in enumerate(encoded):
                        await ws.send(pack_frame(SPEAKER_DOWNLINK, playback_stream, index, packet))
                    eos_fields = {}
                    if gateway.offline_pcm_frames is not None:
                        eos_fields = {
                            "valid_samples_last_frame": gateway.offline_valid_last_samples,
                            "source_pcm_samples": (playback_count-1)*1440+
                                                  gateway.offline_valid_last_samples,
                        }
                    await send("audio_eos", turn_id=turn, playback_id=playback_id,
                               frames=playback_count, **eos_fields)
                elif kind == "playback_started":
                    if (msg.get("turn_id") != turn or msg.get("playback_id") != playback_id
                        or not playback_id or playback_started
                        or type(msg.get("decoded_frames")) is not int
                        or msg["decoded_frames"] != playback_count):
                        await report_error("invalid_playback_start")
                        continue
                    # Trust boundary: only explicit device report after decoding starts mouth.
                    # NOT proof of DAC hardware output; simulator only decodes in RAM.
                    accept("playback_started")
                    playback_started = True
                    await report_state()
                elif kind == "audio_level":
                    if (msg.get("turn_id") != turn or msg.get("playback_id") != playback_id
                        or not playback_started):
                        await report_error("invalid_audio_level")
                        continue
                    accept("audio_level", level=msg.get("level"))
                    await report_state()
                elif kind == "playback_finished":
                    if (msg.get("turn_id") != turn or msg.get("playback_id") != playback_id
                        or not playback_started or
                        type(msg.get("played_frames")) is not int
                        or msg["played_frames"] != playback_count):
                        await report_error("invalid_playback_end")
                        continue
                    accept("playback_finished")
                    await send("playback_report", turn_id=turn, playback_id=playback_id,
                               reported_by="virtual_device", actual_speaker_playback=False)
                    turn, playback_id, playback_count, playback_started = None, None, 0, False
                    await report_state()
                elif kind == "cancel":
                    if msg.get("turn_id") != turn or state.state == "idle" or turn is None:
                        await report_error("invalid_cancel")
                        continue
                    accept("turn_cancelled")
                    old_turn = turn
                    mic_frames.clear()
                    turn, playback_id, playback_count, playback_started = None, None, 0, False
                    capture_stream = None
                    await send("cancel_ack", turn_id=old_turn, state="idle")
                    await report_state()
                else:
                    await report_error("unknown_control")
            except (ValueError, TypeError, OpusError, CompanionEventError):
                await report_error("invalid_control_or_opus")
    except (ConnectionClosed, asyncio.TimeoutError, ValueError):
        pass
    finally:
        if decoder is not None:
            decoder.close()
        if encoder is not None:
            encoder.close()
        mic_frames.clear()
        state.disconnected()
        if owned:
            gateway.active_devices.discard(device)
