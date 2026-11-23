"""Bounded deterministic state-to-animation plan (not a live DSH event source).

Only an authenticated existing DSH/ESP32 event adapter is allowed to pass state.
The scheduler never decides that an LLM/tool/approval succeeded on its own.
"""
from __future__ import annotations
import json
import random
from pathlib import Path

DEFAULT = Path(__file__).with_name("selected_motion_profile.json")
SUPPORTED = {"idle", "listening", "transcribing", "thinking", "tool_pending",
             "approval_pending", "voice_generating", "speaking", "error"}

class MotionPlanError(ValueError):
    pass

class SelectedMotionDirector:
    def __init__(self, profile: dict | None = None, seed: int = 100):
        self.profile = profile if profile is not None else json.loads(DEFAULT.read_text())
        self.cues = self.profile["stateMachine"]
        self.selected = {x["name"] for x in self.profile["selected"]}
        self.rand = random.Random(seed)
        self.phase = "idle"
        self.last_interaction = 0.0
        self.last_idle_show = 0.0
        self.last_bonus = 0.0
        self.next_idle_delay = self._idle_delay()
        self.current = self._ensure(self.cues["quietLoop"])
        self.once = False
        self.last_trigger = "boot"

    def _ensure(self, name: str) -> str:
        if name not in self.selected:
            raise MotionPlanError("nonselected_animation_forbidden")
        return name

    def _idle_delay(self):
        return self.cues["intervalSeconds"] + self.rand.randint(
            -self.cues["jitterSeconds"], self.cues["jitterSeconds"])

    def _choose(self, candidates):
        if not candidates:
            return self._ensure(self.cues["quietLoop"])
        options = [self._ensure(x) for x in candidates]
        if len(options) > 1 and self.current in options:
            alternatives = [x for x in options if x != self.current]
            if alternatives:
                options = alternatives
        return self.rand.choice(options)

    def on_state(self, phase: str, now: float, *, verified: bool = False,
                 event: str | None = None) -> str:
        if phase not in SUPPORTED or not isinstance(now, (float, int)) or now < 0:
            raise MotionPlanError("invalid_phase_or_clock")
        if phase != "idle" and verified is not True:
            raise MotionPlanError("state_not_confirmed_by_trusted_bridge")
        self.phase = phase
        self.last_trigger = event or phase
        if phase == "idle":
            self.last_interaction = float(now)
            self.last_idle_show = float(now)
            self.next_idle_delay = self._idle_delay()
            self.current = self._ensure(self.cues["quietLoop"])
            self.once = False
            return self.current
        self.last_interaction = float(now)
        self.once = False
        if event=="tool_verified" and verified is True:
            # Real official tool receipt may arrive together with the model's
            # voice_generating phase. Surface the checked result instead of
            # reducing it to idle; no inferred / text-only success.
            self.current=self._ensure(self.cues["workEventCues"]["tool_verified"])
            return self.current
        if phase=="approval_pending":
            # A pause for native human approval is not a completed tool.
            self.current=self._ensure("深度思考碎碎念")
            return self.current
        if phase == "speaking":
            # No speaking asset was placed in 'work' by the user. Preserve
            # the quiet visual and use actual verified amplitude for future mouth overlay.
            self.current = self._ensure(self.cues["quietLoop"])
            return self.current
        if phase in ("listening","transcribing","voice_generating","approval_pending"):
            self.current = self._ensure(self.cues["quietLoop"])
            return self.current
        work_key = event if event in self.cues["workEventCues"] else phase
        desired = self.cues["workEventCues"].get(work_key)
        if phase == "error":
            desired = self.cues["workEventCues"].get("turn_failed")
        self.current = self._ensure(desired or self.cues["quietLoop"])
        return self.current

    def on_verified_event(self, event: str, now: float) -> str:
        if event not in self.cues["workEventCues"]:
            raise MotionPlanError("unmapped_work_event")
        if event == "turn_succeeded" and self.phase not in ("thinking","tool_pending","voice_generating"):
            raise MotionPlanError("success_cue_requires_verified_turn")
        return self.on_state(self.phase, now, verified=True, event=event)

    def on_interaction(self, event: str, now: float, *, verified: bool = False) -> str:
        if event not in self.cues["interactionEventCues"]:
            raise MotionPlanError("unmapped_touch_event")
        if verified is not True:
            raise MotionPlanError("event_not_confirmed")
        if self.phase != "idle":
            return self.current
        self.last_interaction = float(now)
        self.current = self._ensure(self.cues["interactionEventCues"][event])
        self.once = True
        return self.current

    def on_animation_end(self) -> str:
        if self.once:
            self.once = False
            self.current = self._ensure(self.cues["quietLoop"])
        return self.current

    def tick(self, now: float) -> str:
        if self.phase != "idle":
            return self.current
        idle_elapsed = now - self.last_interaction
        if idle_elapsed < 0:
            raise MotionPlanError("clock_moved_backward")
        if idle_elapsed >= self.cues["longQuietSeconds"]:
            self.current = self._ensure(self.cues["longQuietMotion"])
            self.once = False
            return self.current
        if self.once:
            return self.current
        if now - self.last_idle_show < self.next_idle_delay:
            return self.current
        self.last_idle_show = float(now)
        self.next_idle_delay = self._idle_delay()
        pool = list(self.cues["ordinaryIdlePool"])
        # Strict low frequency for bonus: at most one after 15 min since previous,
        # only if long quiet mode isn't active; explicit interaction can trigger it.
        # 'bonus' never gets silently forced into normal idle.
        self.current = self._choose(pool)
        self.once = self.current != self.cues["quietLoop"]
        return self.current

    def as_status(self):
        return {"phase":self.phase, "animation":self.current,
                "once":self.once,"source":"approved_selected_motion_profile",
                "selected_count": len(self.selected),
                "verified":self.phase=="idle" or self.last_trigger!="boot"}
