"""R537: protect semantic transitions in extractive R503 spoken scripts.

The local oral compiler intentionally samples facts from widely separated
source sections. A punctuation-centered 2-way split can put the end of one
topic and the start of an unrelated source section INSIDE the same TTS clone,
where the TTS engine may ignore the period. Use verified source provenance
to choose a *true topic boundary* while preserving every spoken character.

No paid model, no invented topic transitions, no source/voice changes.
"""
from __future__ import annotations


_STRONG = "。！？!?；;"


def normalized_source(source_text: str) -> str:
    if not isinstance(source_text, str) or not source_text or len(source_text)>12000:
        return ""
    from app.r458_voice_text import _line_facts, normalize_formula_reading
    from app.voice_spoken_text import prepare_spoken_text
    try:
        return normalize_formula_reading(prepare_spoken_text(_line_facts(source_text)))
    except (ValueError,RuntimeError,TypeError):
        return ""


def source_discontinuity(spoken: str, cut: int, normalized: str) -> int:
    """Return unique character gap between phrases copied from verified source.

    A large positive gap means many source details were skipped between two
    adjacent spoken sentences; it is stronger evidence for a topic boundary
    than punctuation alone. Fails closed when either text is non-verbatim.
    """
    if (not isinstance(spoken,str) or not isinstance(normalized,str)
        or not 14<=cut<=len(spoken)-14 or spoken[cut-1] not in _STRONG):
        return 0
    before=max((i+1 for i in range(cut-1) if spoken[i] in _STRONG),default=0)
    after=min((i+1 for i in range(cut,len(spoken)) if spoken[i] in _STRONG),
              default=len(spoken))
    left=spoken[before:cut].strip()
    right=spoken[cut:after].strip()
    if len(left)<13 or len(right)<13:
        return 0
    left_key=left[-min(17,len(left)):]
    right_key=right[:min(17,len(right))]
    if normalized.count(left_key)!=1 or normalized.count(right_key)!=1:
        return 0
    l=normalized.find(left_key)
    r=normalized.find(right_key)
    return max(0,r-(l+len(left_key)))


def best_source_aware_cut(spoken: str, candidates: list[int], source_text: str | None,
                          *, min_gap:int=100) -> int | None:
    if not candidates or not source_text:return None
    src=normalized_source(source_text)
    if not src:return None
    scored=[(source_discontinuity(spoken,pos,src),pos) for pos in candidates]
    strongest=max((gap for gap,_ in scored),default=0)
    if strongest<min_gap:return None
    return min((pos for gap,pos in scored if gap==strongest),
               key=lambda pos:(abs(pos-len(spoken)//2),pos))


def semantic_interphrase_padding(*, previous_tail_ms:int,
                                  next_lead_ms:int,
                                  topic_gap:int,
                                  target_ms:int=380) -> bytes:
    """Only add zero-valued PCM at an independently proved topic jump.

    The two Qwen requests can each omit a human pause. Need ~0.38s of
    combined silence, not an unconditional 0.38s delay after natural pauses.
    Never trim, alter voiced samples, or add latency to a continuous topic.
    """
    if (min(previous_tail_ms,next_lead_ms,topic_gap)<0 or
        max(previous_tail_ms,next_lead_ms)>120_000 or target_ms<250 or target_ms>500):
        raise ValueError("r537_invalid_boundary_metrics")
    if topic_gap<100:return b""
    missing=max(0,target_ms-previous_tail_ms-next_lead_ms)
    missing=min(320,missing)
    # Mono PCM16LE 24kHz: exactly 48 zero bytes per 1 ms.
    return bytes(missing*48)
