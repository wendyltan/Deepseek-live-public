"""R252: natural, lossless short Qwen voice requests to limit late-utterance drift.

No TTS call, reference-voice change, media storage, or provider request.
Preserves spoken answer byte-for-byte and lets legacy long-mode handle
exceptionally large replies rather than silently truncating text.
"""
from __future__ import annotations
from dataclasses import dataclass
from app.r141_voice_phrase_boundaries import natural_segments
from app.r255_natural_prosody_plan import prosodic_phrases

SHORT_REPLY_LIMIT = 60
GUARD_PHRASE_LIMIT = 55
MAX_GUARD_PHRASES = 16

@dataclass(frozen=True)
class VoicePhrasePlan:
    phrases: tuple[str, ...]
    guarded: bool


def stable_voice_plan(spoken_text: str) -> VoicePhrasePlan:
    if not isinstance(spoken_text, str) or not spoken_text.strip() or len(spoken_text) > 8000:
        raise ValueError('r252_invalid_spoken_reply')
    if len(spoken_text.strip()) <= SHORT_REPLY_LIMIT:
        return VoicePhrasePlan((spoken_text,),False)
    phrases=prosodic_phrases(spoken_text,limit=GUARD_PHRASE_LIMIT)
    if (2 <= len(phrases) <= MAX_GUARD_PHRASES and
        all(part.strip() and len(part)<=GUARD_PHRASE_LIMIT for part in phrases)):
        assert ''.join(phrases)==spoken_text
        return VoicePhrasePlan(tuple(phrases),True)
    # The existing <=150-char, <=16-segment path still handles very long
    # replies. Do not drop content just to force a smaller TTS chunk.
    return VoicePhrasePlan(tuple(natural_segments(spoken_text,limit=145)),False)
