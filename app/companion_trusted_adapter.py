"""Trusted Mac-side projection: authenticated DSH facts + local player → device cues.

Offline, opt-in integration library only. No HTTP listener, model calls,
credential access, device broadcasting or microphone activation. The Bridge
owns DSH identity/outcomes; CompanionState owns valid device transitions.
Caller must fetch facts through its authenticated loopback Bridge client
and invoke audio hooks only from trusted worker/player acknowledgements.
"""
from __future__ import annotations

from copy import deepcopy
import re

from app.companion_events import CompanionEventError, CompanionState
from app.companion_visuals import cue_for_state

_SESSION = re.compile(r"[a-zA-Z0-9_-]{8,128}\Z")
_PHASES = frozenset(("thinking", "working", "approval_pending",
                     "cancel_requested", "settling", "settled"))
_OUTCOMES = frozenset(("answered", "tool_verified", "failed", "cancelled"))


class StaleCompanionFacts(CompanionEventError):
    """A once-valid response overtaken by a newer Bridge revision."""


class TrustedCompanionAdapter:
    """Project safe facts onto the existing transport-independent state guard."""

    def __init__(self):
        self.device = CompanionState()
        self.session_id: str | None = None
        self.last_revision = -1
        self.last_tools = 0
        self.active = False

    @property
    def state(self) -> str:
        return self.device.state

    def cue(self) -> dict:
        """Same bounded visual schema for Mac Cubism mapping and ESP32."""
        return cue_for_state(self.state, playback_confirmed=self.state == "speaking",
                             level=self.device.audio_level).compact()

    def _emit(self, event: str, **payload) -> dict:
        packet = dict(v=1, event=event, turn_id=self.device.turn_id,
                      seq=self.device.last_seq + 1, **payload)
        state = self.device.accept(packet)
        return {**packet, "state": state, "visual": self.cue()}

    def _begin(self, event: str, *, turn_id: str, session_id: str) -> list[dict]:
        if self.active or self.state != "idle":
            raise CompanionEventError("another companion turn is active")
        if not isinstance(session_id, str) or not _SESSION.fullmatch(session_id):
            raise CompanionEventError("invalid bound DSH session")
        # Validate the start in the authoritative guard before binding owner.
        packet = dict(v=1, event=event, turn_id=turn_id, seq=1)
        self.device.accept(packet)
        self.session_id = session_id
        self.last_revision = -1
        self.last_tools = 0
        self.active = True
        return [{**packet, "state": self.state, "visual": self.cue()}]

    def begin_text_turn(self, *, turn_id: str, session_id: str) -> list[dict]:
        return self._begin("text_turn_started", turn_id=turn_id, session_id=session_id)

    def begin_mic_turn(self, *, turn_id: str, session_id: str) -> list[dict]:
        return self._begin("mic_started", turn_id=turn_id, session_id=session_id)

    def _require_active(self):
        if not self.active or self.state == "disconnected":
            raise CompanionEventError("no active trusted companion turn")

    def capture_stopped(self) -> list[dict]:
        """Only the trusted recorder calls this on actual capture termination."""
        self._require_active()
        return [self._emit("mic_stopped")]

    def transcription_completed(self) -> list[dict]:
        """Only the trusted STT worker calls this on actual successful decoding."""
        self._require_active()
        return [self._emit("stt_completed")]

    def _validate_facts(self, item: dict) -> None:
        self._require_active()
        if not isinstance(item, dict) or type(item.get("protocolVersion")) is not int or item["protocolVersion"] != 1:
            raise CompanionEventError("invalid facts protocol")
        if item.get("turn_id") != self.device.turn_id or item.get("session_id") != self.session_id:
            raise CompanionEventError("DSH fact owner mismatch")
        rev = item.get("revision")
        if type(rev) is not int or not self.last_revision < rev <= 1_000_000_000:
            raise StaleCompanionFacts("stale or invalid DSH facts revision")
        count, approval, failed, ready = (item.get(k) for k in (
            "tool_active_count", "approval_pending", "tool_failed", "assistant_ready_for_tts"))
        outcome, phase = item.get("outcome"), item.get("task_phase")
        if (type(count) is not int or not 0 <= count <= 1_000_000 or
                any(type(x) is not bool for x in (approval, failed, ready)) or
                (outcome is not None and (not isinstance(outcome, str) or
                                          outcome not in _OUTCOMES)) or
                not isinstance(phase, str) or phase not in _PHASES):
            raise CompanionEventError("invalid companion fact fields")
        if approval and (phase != "approval_pending" or outcome is not None):
            raise CompanionEventError("invalid pending approval facts")
        if phase == "approval_pending" and not approval:
            raise CompanionEventError("missing pending approval")
        if outcome is not None:
            if (phase != "settled" or approval or
                    ready != (outcome in ("answered", "tool_verified")) or
                    (outcome in ("answered", "tool_verified") and (count != 0 or failed))):
                raise CompanionEventError("invalid settled facts")
        elif ready or phase == "settled":
            raise CompanionEventError("unsettled text cannot be ready")
        if count and not approval and phase not in ("working", "cancel_requested", "settled"):
            raise CompanionEventError("active tools require working phase")

    def apply_facts(self, facts: dict) -> list[dict]:
        """Handle a versioned, authenticated snapshot; ignore no stale event."""
        self._validate_facts(facts)
        if self.state in ("listening", "transcribing"):
            raise CompanionEventError("DSH facts cannot skip confirmed STT completion")
        if self.state in ("voice_generating", "speaking") and facts["outcome"] is None:
            raise CompanionEventError("settled turn cannot return to tool execution")
        # Stage all device transitions on a copy; invalid/incomplete snapshots
        # cannot partially mutate visible state or monotonic revision.
        trial = deepcopy(self.device)
        original = self.device
        result = []
        count = facts["tool_active_count"]
        approval = facts["approval_pending"]
        outcome = facts["outcome"]
        try:
            self.device = trial
            # Transition out of approval before work count is reduced.
            if self.state == "approval_pending" and not approval and outcome not in ("failed", "cancelled"):
                result.append(self._emit("approval_decided"))
            if not outcome:
                if self.last_tools == 0 and count and self.state == "thinking":
                    result.append(self._emit("tool_started"))
                elif count == 0 and self.state == "tool_pending":
                    # An approval can complete a tool while the UI waits;
                    # the prior snapshot's count is then already zero.
                    result.append(self._emit("tool_finished"))
                if approval and self.state != "approval_pending":
                    result.append(self._emit("approval_asked"))
            elif outcome in ("failed", "cancelled"):
                if outcome == "failed" and self.state == "error":
                    pass  # A later fact revision may repeat a settled failure.
                else:
                    result.append(self._emit("turn_failed" if outcome == "failed" else "turn_cancelled"))
            elif outcome in ("answered", "tool_verified") and self.state == "thinking":
                result.append(self._emit("llm_completed"))
            elif outcome in ("answered", "tool_verified") and self.state == "tool_pending":
                # One poll may miss the last tool result; never infer tool
                # *success* from count alone, only Bridge's final outcome.
                result.append(self._emit("tool_finished"))
                result.append(self._emit("llm_completed"))
            elif outcome in ("answered", "tool_verified") and self.state not in (
                "voice_generating", "speaking"):
                raise CompanionEventError("cannot start TTS in this state")
        except Exception:
            self.device = original
            raise
        self.last_revision = facts["revision"]
        self.last_tools = count
        if self.state == "idle":
            self.active = False
        return result

    def audio_prepared(self) -> list[dict]:
        """Call after the local TTS worker confirms playable audio exists."""
        self._require_active()
        return [self._emit("tts_ready")]

    def player_started(self) -> list[dict]:
        """Call only from the trusted actual audio player's started callback."""
        self._require_active()
        return [self._emit("playback_started")]

    def player_level(self, level: float) -> list[dict]:
        """Call only on level measurements during actual playback."""
        self._require_active()
        return [self._emit("audio_level", level=level)]

    def player_finished(self) -> list[dict]:
        """Call only from the trusted playback completion callback."""
        self._require_active()
        result = [self._emit("playback_finished")]
        self.active = False
        return result

    def player_interrupted(self) -> list[dict]:
        self._require_active()
        result = [self._emit("playback_interrupted")]
        self.active = False
        return result

    def acknowledge_error(self) -> list[dict]:
        self._require_active()
        result = [self._emit("error_acknowledged")]
        self.active = False
        return result

    def disconnected(self) -> dict:
        """Fail closed on device/bridge transport loss, never revive old turn."""
        self.device.disconnected()
        self.active = False
        return {"state": "disconnected", "visual": self.cue()}

    def connected(self) -> dict:
        self.device.connected()
        return {"state": "idle", "visual": self.cue()}
