"""Transport-independent ESP32 whale companion event guard (P2.0-A).

This is a deterministic offline contract, not a WebSocket server, Opus decoder,
or proof of actual media playback. The gateway must authenticate the device
before calling accept(), and must derive events from confirmed real actions.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

PROTOCOL_VERSION = 1
_TURN = re.compile(r"[a-zA-Z0-9_-]{8,64}\Z")
_TRANSITIONS = {
    "mic_stopped": ("listening", "transcribing"),
    "stt_completed": ("transcribing", "thinking"),
    "tool_started": ("thinking", "tool_pending"),
    "tool_finished": ("tool_pending", "thinking"),
    "llm_completed": ("thinking", "voice_generating"),
}


class CompanionEventError(ValueError):
    """Reject stale, malformed, or impossible companion events."""


@dataclass
class CompanionState:
    state: str = "idle"
    turn_id: str | None = None
    recent_closed_turns: deque[str] = field(default_factory=lambda: deque(maxlen=64), repr=False)
    last_seq: int = 0
    audio_level: float = 0.0
    audio_ready: bool = False
    approval_return: str | None = None

    def disconnected(self) -> None:
        """Stop animation and disallow stale replay until explicitly reconnected."""
        self._close_turn()
        self.state = "disconnected"

    def connected(self) -> None:
        if self.state != "disconnected":
            raise CompanionEventError("device is already connected")
        self.state = "idle"

    def _close_turn(self) -> None:
        if self.turn_id is not None:
            self.recent_closed_turns.append(self.turn_id)
        self.turn_id = None
        self.last_seq = 0
        self.audio_level = 0.0
        self.audio_ready = False
        self.approval_return = None

    def accept(self, payload: dict) -> str:
        """Apply one authenticated, ordered event; return updated display state."""
        if not isinstance(payload, dict):
            raise CompanionEventError("event must be an object")
        if type(payload.get("v")) is not int or payload["v"] != PROTOCOL_VERSION:
            raise CompanionEventError("unsupported event version")
        event, turn_id, seq = payload.get("event"), payload.get("turn_id"), payload.get("seq")
        if not isinstance(event, str) or len(event) > 40:
            raise CompanionEventError("invalid event name")
        if not isinstance(turn_id, str) or not _TURN.fullmatch(turn_id):
            raise CompanionEventError("invalid turn ID")
        if type(seq) is not int or not (1 <= seq <= 1_000_000_000):
            raise CompanionEventError("invalid sequence")
        if self.state == "disconnected":
            raise CompanionEventError("device is disconnected")
        if event in ("mic_started", "text_turn_started"):
            if self.state != "idle" or turn_id in self.recent_closed_turns:
                raise CompanionEventError("new turn is not allowed")
            self.turn_id, self.last_seq = turn_id, seq
            self.audio_ready = False
            self.audio_level = 0.0
            self.state = "listening" if event == "mic_started" else "thinking"
            return self.state
        if turn_id != self.turn_id or seq <= self.last_seq:
            raise CompanionEventError("wrong turn or stale sequence")
        next_state = _TRANSITIONS.get(event)
        if next_state is not None:
            if self.state != next_state[0]:
                raise CompanionEventError("impossible state transition")
            self.state = next_state[1]
            if event == "llm_completed":
                self.audio_ready = False
        elif event == "approval_asked":
            if self.state not in ("thinking", "tool_pending"):
                raise CompanionEventError("approval requires active thinking or tool")
            self.approval_return = self.state
            self.state = "approval_pending"
        elif event == "approval_decided":
            if self.state != "approval_pending" or self.approval_return is None:
                raise CompanionEventError("no pending approval to resume")
            self.state = self.approval_return
            self.approval_return = None
        elif event == "tts_ready":
            if self.state != "voice_generating":
                raise CompanionEventError("voice is not pending")
            self.audio_ready = True
        elif event == "playback_started":
            if self.state != "voice_generating" or not self.audio_ready:
                raise CompanionEventError("cannot speak before verified playback")
            self.state = "speaking"
        elif event == "audio_level":
            level = payload.get("level")
            if (self.state != "speaking" or type(level) not in (int, float)
                    or not (0.0 <= level <= 1.0)):
                raise CompanionEventError("audio level needs active playback and 0..1 value")
            self.audio_level = float(level)
        elif event in ("playback_finished", "playback_interrupted"):
            if self.state != "speaking" and not (
                event == "playback_interrupted" and self.state == "voice_generating"
            ):
                raise CompanionEventError("no playback to finish")
            self._close_turn()
            self.state = "idle"
        elif event == "turn_cancelled":
            if self.state not in ("listening", "transcribing", "thinking", "tool_pending", "approval_pending", "voice_generating", "speaking", "error"):
                raise CompanionEventError("no active turn to cancel")
            self._close_turn()
            self.state = "idle"
        elif event == "turn_failed":
            if self.state not in ("listening", "transcribing", "thinking", "tool_pending", "approval_pending", "voice_generating", "speaking"):
                raise CompanionEventError("no active turn to fail")
            self.audio_level = 0.0
            self.audio_ready = False
            self.approval_return = None
            self.state = "error"
        elif event == "error_acknowledged":
            if self.state != "error":
                raise CompanionEventError("no error to clear")
            self._close_turn()
            self.state = "idle"
        else:
            raise CompanionEventError("unknown event")
        self.last_seq = seq if self.turn_id is not None else 0
        return self.state
