"""P2.0-C asset-free visual-state adapter, usable by Mac and future CoreS3.

'playback_confirmed' must originate from actual player/hardware acknowledgement,
not text generation, tts_ready, network audio receipt or user intent.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

PROFILE_PATH = Path(__file__).with_name("companion_visual_profile.json")


@dataclass(frozen=True)
class VisualCue:
    v: int
    state: str
    face: str | None
    pose: str
    mouth: float
    yaw: float
    pitch: float
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    eye_open: float = 1.0
    indicator: str | None = None
    sway: float = 0.0

    def compact(self) -> dict:
        """Device-oriented compact structured cue, asset data not transmitted."""
        return asdict(self)


def load_visual_profile(path: Path = PROFILE_PATH) -> dict:
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("schema") != 1 or not profile.get("states"):
        raise ValueError("invalid visual profile")
    return profile


def cue_for_state(
    state: str, *, playback_confirmed: bool = False, level: float = 0.0,
    reaction: str | None = None, profile: dict | None = None,
) -> VisualCue:
    """Return deterministic intent; no unrequested hardware side effects."""
    data = profile if profile is not None else load_visual_profile()
    if state not in data["states"]:
        raise ValueError("unknown companion state")
    if type(playback_confirmed) is not bool:
        raise ValueError("playback must be a confirmed boolean")
    if type(level) not in (float, int) or not math.isfinite(level) or not 0 <= level <= 1:
        raise ValueError("invalid playback level")
    item = data["states"][state]
    if reaction is not None:
        if state not in ("idle", "speaking") or reaction not in data.get("special", {}):
            raise ValueError("reaction not allowed in current state")
        item = data["special"][reaction]
    # No lips on audio_test frames, network receipt or incomplete TTS.
    mouth = round(float(level), 3) if state == "speaking" and playback_confirmed else 0.0
    return VisualCue(v=1, state=state, face=item["face"], pose=item["pose"],
                     mouth=mouth, yaw=item.get("yaw", 0), pitch=item.get("pitch", 0),
                     gaze_x=item.get("gaze_x", 0.0), gaze_y=item.get("gaze_y", 0.0),
                     eye_open=item.get("eye_open", 1.0),
                     indicator=item.get("indicator"), sway=item.get("sway", 0.0))
