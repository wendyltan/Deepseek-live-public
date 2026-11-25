"""Wi-Fi-only D10 utterance plan: fewer separate clone restarts than R252.

Never changes the USB R252 planner, the D10 reference/seed, audio frames,
speaker codec, original punctuation or 320-char full-text disclosure policy.
"""
from __future__ import annotations
from app.r141_voice_phrase_boundaries import natural_segments

WIFI_FIRST_LIMIT = 66
WIFI_FOLLOWUP_LIMIT = 145
MIN_FINAL_CHARS = 40
_STRONG_BREAKS = "。！？!?；;\\n"
_SOFT_BREAKS = "，,：:、"


def _rebalance_short_tail(text: str, count: int):
    """R502: keep phrase count but avoid a separately cloned 1–39-char tail.

    First phrase remains <=110 chars. Follow-ups <=145. Prefer sentence
    boundaries; if impossible, an equal-length soft cut preserves text
    without creating extra clone restarts.
    """
    if count<2 or count>5:
        return ()
    remaining=text
    parts=[]
    for i in range(count-1):
        future=count-i-1
        limit=WIFI_FIRST_LIMIT if i==0 else WIFI_FOLLOWUP_LIMIT
        target=(len(remaining)+future)//(future+1)
        lo=max(32,target-30,len(remaining)-future*WIFI_FOLLOWUP_LIMIT)
        hi=min(limit,target+30,len(remaining)-future*MIN_FINAL_CHARS)
        if lo>hi:
            return ()
        candidates=[j for j in range(lo,hi+1)
                    if remaining[j-1] in _STRONG_BREAKS]
        if not candidates:
            candidates=[j for j in range(lo,hi+1)
                        if remaining[j-1] in _SOFT_BREAKS]
        index=min(candidates,key=lambda j:abs(j-target)) if candidates else max(lo,min(hi,target))
        parts.append(remaining[:index]);remaining=remaining[index:]
    parts.append(remaining)
    if (any(not p.strip() for p in parts) or
        len(parts[0])>WIFI_FIRST_LIMIT or
        any(len(p)>WIFI_FOLLOWUP_LIMIT for p in parts[1:]) or
        len(parts[-1].strip())<MIN_FINAL_CHARS or
        "".join(parts)!=text):
        return ()
    return tuple(parts)


def wifi_voice_phrases(spoken: str) -> tuple[str,...]:
    if not isinstance(spoken,str) or not spoken.strip() or len(spoken)>8000:
        raise ValueError("r336_invalid_spoken_text")
    if len(spoken)<=WIFI_FIRST_LIMIT:
        return (spoken,)
    # Preserve first-voice latency at <=110 characters. Following phrases
    # can use up to 145; fewer independent clone restarts for common answers.
    first=natural_segments(spoken,limit=WIFI_FIRST_LIMIT)[0]
    rest=spoken[len(first):]
    phrases=(first,)+tuple(natural_segments(rest,limit=WIFI_FOLLOWUP_LIMIT)
                          if rest else ())
    # R502: the previously accepted R477 255-char text was cut 106/129/20.
    # Those three *independent* voice-clone restarts create an unstable 20-
    # char emotional tail. Rebalance only where a short tail exists, and keep
    # exactly the same number of calls; no cost/latency amplification.
    if len(phrases)>1 and len(phrases[-1].strip())<MIN_FINAL_CHARS:
        candidate=_rebalance_short_tail(spoken,len(phrases))
        if candidate:phrases=candidate
    if not phrases or "".join(phrases)!=spoken or any(
        len(p)>(WIFI_FIRST_LIMIT if i==0 else WIFI_FOLLOWUP_LIMIT)
        or not p.strip() for i,p in enumerate(phrases)
    ):
        raise ValueError("r458_plan_not_lossless")
    return tuple(phrases)


def wifi_buffered_r503_phrases(
        spoken: str, *, base_phrases: tuple[str, ...] | None = None
) -> tuple[str, ...]:
    """Save a clone restart only when *complete buffering* makes it safe.

    The 66-character leading chunk was for first-audio streaming. R524
    buffers every R503 phrase, so a two-phrase natural punctuation split
    can reduce first-sound wait without changing the text/voice/final PCM.
    Keep original cuts if reducing calls would cut an unfinished word.
    """
    if len(spoken) <= 110 and spoken.strip():
        return (spoken,)
    base = base_phrases if base_phrases is not None else wifi_voice_phrases(spoken)
    if ("".join(base) != spoken or len(base) < 3 or
            not 110 <= len(spoken) <= 255):
        return base
    lo = max(45, len(spoken) - WIFI_FOLLOWUP_LIMIT)
    hi = min(110, len(spoken) - MIN_FINAL_CHARS)
    if lo > hi:
        return base
    for breaks in (_STRONG_BREAKS, _SOFT_BREAKS):
        eligible = [i for i in range(lo, hi + 1) if spoken[i - 1] in breaks]
        if eligible:
            cut = max(eligible)
            proposal = (spoken[:cut], spoken[cut:])
            if (len(proposal[0]) <= 110 and
                    len(proposal[1]) <= WIFI_FOLLOWUP_LIMIT and
                    len(proposal[1].strip()) >= MIN_FINAL_CHARS and
                    all(part.strip() for part in proposal)):
                return proposal
    return base


def wifi_oral_script_phrases(
        spoken: str, *, source_text: str | None = None) -> tuple[str, ...]:
    """R529: balanced, punctuation-aligned R503 input after oral compilation.

    R524 still buffers all chunks before offering any audio to ESP32.
    Avoids old 66+145 split or a separate 15-character clone tail.
    """
    if not isinstance(spoken,str) or not 1 <= len(spoken) <= 210:
        raise ValueError("r529_script_invalid")
    if len(spoken) <= 110:
        return (spoken,)
    low=max(42,len(spoken)-110)
    high=min(110,len(spoken)-42)
    if low>high:
        return wifi_voice_phrases(spoken)
    candidates=[i for i in range(low,high+1) if spoken[i-1] in _STRONG_BREAKS]
    if not candidates:
        candidates=[i for i in range(low,high+1) if spoken[i-1] in _SOFT_BREAKS]
    if not candidates:
        return wifi_voice_phrases(spoken)
    # R537: the extractive compiler can concatenate sentences from far-apart
    # original sections. Split at that REAL topic jump if it still preserves
    # exactly two <110-char phrases; plain nearest-half often puts the jump
    # INSIDE one TTS clone, where punctuation does not reliably cause silence.
    from app.r537_semantic_tts_boundaries import best_source_aware_cut
    semantic=best_source_aware_cut(spoken,candidates,source_text)
    cut=semantic if semantic is not None else min(
        candidates,key=lambda i:(abs(i-len(spoken)//2),i))
    result=(spoken[:cut],spoken[cut:])
    if any(not s.strip() or len(s)>110 or len(s)<40 for s in result):
        return wifi_voice_phrases(spoken)
    assert "".join(result)==spoken
    return result
