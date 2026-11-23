"""Optional Wi-Fi long-answer speech summarizer, isolated from T1/firmware.

Only an already-verified official DSH reply and a user-enabled speech-only
Flash setting may enter one fixed scoped text-only model call. The original
answer remains unchanged in Mac conversation history. Short, local and fake
responses never pay or create a second session.
"""
from __future__ import annotations

import re


def _section_coverage(original: str, candidate: str) -> bool:
    """Conservatively require unique factual phrases from middle and ending.

    Spoken-only Flash may paraphrase, so a false negative means a safe,
    verified local full-document selection. This does not mutate the answer
    in the official DSH conversation or cause a second paid summary request.
    """
    text=re.sub(r"\s+", "", original)
    spoken=re.sub(r"\s+", "", candidate)
    from app.r528_parallel_fact_voice import parallel_item_names
    named_facts=parallel_item_names(original)
    if named_facts and not all(name in spoken for name in named_facts):
        # A model summary that lost one out of eight named items cannot be
        # accepted merely because it mentioned opening, middle and ending.
        return False
    # Wi-Fi summarization can trigger at 321 chars. The old 360-char
    # exemption let a 321–359-char opening-only summary bypass coverage.
    if len(text)<=320:
        return True
    third=len(text)//3
    a,mid,end=text[:third],text[third:2*third],text[2*third:]
    def covered(section,other):
        grams={section[i:i+5] for i in range(max(0,len(section)-4))
               if section[i:i+5] not in other
               and any("\u4e00"<=c<="\u9fff" for c in section[i:i+5])}
        return not grams or any(g in spoken for g in grams)
    # R511: the real 497-character fogging reply lost its causal opening.
    # A spoken summary must carry opening, mid-answer and closing facts;
    # otherwise use a deterministic full-document factual fallback.
    return (covered(a,mid+end) and
            covered(mid,a+end) and
            covered(end,a+mid))


def spoken_source_for_wifi(reply, transcript, *, origin, native, mark=None):
    if origin!="official_dsh_verified" or not isinstance(reply,str):
        return reply
    from app.voice_preprocessor import settings
    opts=settings()
    if opts.get("enabled") is not True:
        return reply
    if len(reply)<=max(320,opts.get("min_chars",220)):
        return reply
    from app.dsh_p1_adapter import DshP1Adapter,SpeechOnlyDshP1Adapter
    original_adapter=getattr(native,"adapter",None)
    # Do not activate on fake agents, reentrant adapters, local clock/weather
    # or a second untrusted transport: all must retain old deterministic path.
    if type(original_adapter) is not DshP1Adapter:
        return reply
    # R530: a verified 6-12-item enumeration with every item retained
    # verbatim needs no extra paid/slow Flash summary at all. The generic
    # R529 compiler is local and refuses unsafe or unstructured sources.
    from app.r529_long_speech_script import compile_verified_source
    local=compile_verified_source(reply,reply)
    if local is not None and local.kind=="enumeration" and local.factual_items>=6:
        if mark is not None:
            mark("r484_wifi_spoken_summary",state="local_structured",
                 original_chars=len(reply),spoken_chars=len(local.text))
        return local.text
    from app.voice_preprocessor import spoken_only
    signals=[]
    def log(message):
        # Never put the prompt, recognized words, reply or credential in
        # progress traces. Message is a machine-labelled local event only.
        if message.startswith("R212_PREPROCESS "):
            word=message.split()[1] if len(message.split())>1 else "UNKNOWN"
            if word in ("APPLIED","LOCAL_DIGEST","FALLBACK"):
                signals.append(word)
    try:
        scoped=SpeechOnlyDshP1Adapter(
            original_adapter.url,original_adapter.token,timeout=16)
        shortened=spoken_only(reply,transcript,adapter=scoped,timeout_s=12,output=log)
    except (ValueError,OSError,RuntimeError):
        if mark is not None:mark("r484_wifi_spoken_summary",state="fallback")
        return reply
    state=signals[-1] if signals else "not_applied"
    # If the scoped summarizer was unavailable/timeout, use the improved
    # Wi-Fi across-document factual selector instead of r260's older
    # first-18-sentences local digest and forced 'see Mac' footer.
    if state!="APPLIED":
        if mark is not None:mark("r484_wifi_spoken_summary",state="fallback")
        return reply
    if not isinstance(shortened,str) or not shortened.strip() or len(shortened)>=len(reply):
        if mark is not None:mark("r484_wifi_spoken_summary",state="invalid")
        return reply
    if not _section_coverage(reply,shortened):
        # A formally APPLIED model result can still lose most listed items.
        # For a verified full enumeration, downstream R529 must see the
        # *whole* answer; the old 320-char selection could drop named facts.
        from app.r528_parallel_fact_voice import parallel_item_names
        if parallel_item_names(reply):
            if mark is not None:mark("r484_wifi_spoken_summary",state="coverage_fallback",
                                      original_chars=len(reply),spoken_chars=len(reply))
            return reply
        # Other unsupported layouts keep the existing no-extra-cost fallback.
        from app.r458_voice_text import voice_ready_reply
        across,_=voice_ready_reply(reply)
        if mark is not None:mark("r484_wifi_spoken_summary",state="coverage_fallback",
                                  original_chars=len(reply),spoken_chars=len(across))
        return across
    if mark is not None:mark("r484_wifi_spoken_summary",state="applied",
                             original_chars=len(reply),spoken_chars=len(shortened))
    return shortened
