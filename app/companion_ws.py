"""Authenticated localhost WS/real Opus loopback, separate from P1 :8765.

P2.0-B is intentionally a transport/audio engineering test: NO STT, LLM,
OmniVoice, speaker output or payment. 'audio_test_*' never means speaking.
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import re
from collections import deque

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from app.companion_events import CompanionEventError, CompanionState
from app.opus_codec import OpusCodec, OpusError, UPSTREAM_RATE, DOWNSTREAM_RATE, upsample_16k_to_24k

HOST = "127.0.0.1"
DEFAULT_PORT = 8877
MAX_FRAMES = 100
_DEVICE_ID = re.compile(r"[a-zA-Z0-9_-]{8,64}\Z")


def payload(text):
    if len(text) > 4096:
        raise ValueError("oversized control message")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("expected JSON object")
    return obj


class CompanionGateway:
    def __init__(self, token: str, *, device_tokens=None, offline_fixture=False,
                 offline_pcm_frames=None, offline_valid_last_samples=None):
        if len(token) < 24:
            raise ValueError("device token needs at least 24 characters")
        if device_tokens is not None and (not device_tokens or any(
                not isinstance(key, str) or not _DEVICE_ID.fullmatch(key)
                or not isinstance(value, str) or len(value) < 24
                for key, value in device_tokens.items())
                or len(set(device_tokens.values())) != len(device_tokens)):
            raise ValueError("device credentials require bounded ids and 24+ character tokens")
        if offline_pcm_frames is not None:
            # Lab fixture only. Never a production speech backend or second Agent.
            if not offline_fixture or device_tokens is None or not isinstance(offline_pcm_frames,tuple):
                raise ValueError("real PCM fixture requires isolated authenticated device lab")
            if not 1 <= len(offline_pcm_frames) <= 120 or any(
                    not isinstance(frame,tuple) or len(frame)!=1440 or any(
                        type(sample) is not int or not -32768 <= sample <= 32767
                        for sample in frame)
                    for frame in offline_pcm_frames):
                raise ValueError("bounded 24 kHz 60ms mono signed PCM fixture required")
        if offline_pcm_frames is None:
            if offline_valid_last_samples is not None:
                raise ValueError("tail samples without an injected PCM clip")
        elif (type(offline_valid_last_samples) is not int
              or not 1 <= offline_valid_last_samples <= 1440):
            raise ValueError("offline PCM fixture needs exact last-frame sample count")
        self.token = token
        self.device_tokens = dict(device_tokens) if device_tokens is not None else None
        self.offline_fixture = offline_fixture
        self.offline_pcm_frames = offline_pcm_frames
        self.offline_valid_last_samples = offline_valid_last_samples
        self.active_devices = set()
        self.seen_ids = set()
        self.turn_history = deque(maxlen=128)

    async def authorize(self, connection, request):
        if request.path != "/device":
            return connection.respond(404, "Not found\n")
        if self.device_tokens is not None:
            # Reject duplicate identity/auth headers instead of trusting a proxy's last value.
            if any(len(request.headers.get_all(k)) != 1 for k in
                   ("Authorization", "Device-Id", "Client-Id")):
                return connection.respond(401, "Unauthorized\n")
            device = request.headers["Device-Id"]
            client = request.headers["Client-Id"]
            provided = request.headers["Authorization"]
            if (not _DEVICE_ID.fullmatch(device)
                or not _DEVICE_ID.fullmatch(client)
                or device not in self.device_tokens):
                return connection.respond(401, "Unauthorized\\n")
            wanted = "Bearer " + self.device_tokens[device]
        else:
            provided = request.headers.get("Authorization", "")
            wanted = "Bearer " + self.token
        if not hmac.compare_digest(provided, wanted):
            return connection.respond(401, "Unauthorized\n")
        return None

    def reserve_turn(self, turn_id):
        if turn_id in self.seen_ids:
            raise CompanionEventError("recent turn ID cannot be replayed")
        if len(self.turn_history) >= self.turn_history.maxlen:
            old = self.turn_history.popleft()
            self.seen_ids.discard(old)
        self.turn_history.append(turn_id)
        self.seen_ids.add(turn_id)

    async def handler(self, ws):
        if self.device_tokens is not None:
            from app.companion_device_protocol import handle_device_v2
            await handle_device_v2(self, ws)
            return
        state = CompanionState()
        frames = []
        turn = None
        decoder = OpusCodec(UPSTREAM_RATE, "decode")
        encoder = OpusCodec(DOWNSTREAM_RATE, "encode")
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=5)
            try:
                hello = payload(first) if isinstance(first, str) else {}
            except (ValueError, TypeError):
                hello = {}
            if hello.get("type") != "hello" or hello.get("v") != 1 or hello.get("device") != "esp32-sim":
                await ws.close(code=1008, reason="bad hello")
                return
            await ws.send(json.dumps({"type": "hello_ack", "v": 1, "protocol": "p2-loopback-v1",
                                      "uplink_hz": 16000, "downlink_hz": 24000,
                                      "frame_ms": 60, "mcp": False}))
            async for message in ws:
                try:
                    if isinstance(message, bytes):
                        if state.state != "listening" or not turn:
                            raise ValueError("Opus received outside microphone capture")
                        if len(frames) >= MAX_FRAMES:
                            raise ValueError("audio frame limit exceeded")
                        frames.append(decoder.decode(message))
                        continue
                    msg = payload(message)
                    typ = msg.get("type")
                    if typ == "heartbeat":
                        await ws.send(json.dumps({"type": "heartbeat_ack"}))
                    elif typ == "start":
                        candidate = msg.get("turn_id")
                        # Check cross-connection replay before mutating the state machine.
                        if isinstance(candidate, str) and candidate in self.seen_ids:
                            raise CompanionEventError("recent turn ID cannot be replayed")
                        state.accept({"v": 1, "event": "mic_started", "turn_id": candidate, "seq": 1})
                        self.reserve_turn(candidate)
                        turn, frames = candidate, []
                        await ws.send(json.dumps({"type": "state", "state": "listening", "turn_id": turn}))
                    elif typ == "finish":
                        if not frames or msg.get("turn_id") != turn:
                            raise ValueError("no recorded Opus frames for turn")
                        state.accept({"v": 1, "event": "mic_stopped", "turn_id": turn, "seq": 2})
                        await ws.send(json.dumps({"type": "audio_rx", "turn_id": turn,
                                                  "frames": len(frames), "samples": 960 * len(frames)}))
                        await ws.send(json.dumps({"type": "audio_test_start", "turn_id": turn,
                                                  "kind": "decoded-reencoded-loopback",
                                                  "hz": DOWNSTREAM_RATE, "frame_ms": 60,
                                                  "frames": len(frames)}))
                        # Real libopus decode from uplink and encode at downlink rate.
                        for pcm in frames:
                            await ws.send(encoder.encode(upsample_16k_to_24k(pcm)))
                        await ws.send(json.dumps({"type": "audio_test_done", "turn_id": turn,
                                                  "frames": len(frames),
                                                  "actual_speaker_playback": False}))
                        frames = []
                    elif typ == "cancel":
                        if msg.get("turn_id") != turn or turn is None:
                            raise ValueError("no matching active turn")
                        state.accept({"v": 1, "event": "turn_cancelled", "turn_id": turn,
                                      "seq": state.last_seq + 1})
                        await ws.send(json.dumps({"type": "cancel_ack", "turn_id": turn, "state": "idle"}))
                        frames, turn = [], None
                    else:
                        raise ValueError("unknown control message")
                except (ValueError, TypeError, OpusError, CompanionEventError) as exc:
                    # Do not echo user audio, tokens or any transcript.
                    await ws.send(json.dumps({"type": "error", "reason": str(exc)[:100]}))
        except (ConnectionClosed, asyncio.TimeoutError):
            pass
        finally:
            decoder.close()
            encoder.close()
            state.disconnected()
            frames.clear()


def main():
    parser = argparse.ArgumentParser(description="Loopback-only ESP32 WebSocket/Opus test Gateway")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    secret = os.environ.get("DEEPSEEK_COMPANION_TOKEN", "")
    if len(secret) < 24:
        parser.error("set DEEPSEEK_COMPANION_TOKEN (24+ characters); do not pass it on the CLI")
    gateway = CompanionGateway(secret)

    async def run():
        async with serve(gateway.handler, HOST, args.port,
                         process_request=gateway.authorize,
                         max_size=8192, max_queue=8, compression=None,
                         ping_interval=10, ping_timeout=5) as server:
            print(f"P2.0-B loopback listening on ws://{HOST}:{args.port}/device (no DeepSeek calls)")
            await server.serve_forever()
    asyncio.run(run())


if __name__ == "__main__":
    main()
