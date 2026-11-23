"""R305: consent-aware memory receipts for authenticated battery Wi-Fi speech.

Only after the existing WSS identity gate, physical microphone, VAD and
verified local STT. Never learns from DSH completions, tool output or untrusted
network text. Reuses the USB-era narrow safe facts and owner-private files.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

from app import r38_memory_loop as vault
from app import voice_memory_candidates as review
from app.r141_explicit_voice_memory import explicit_target, is_explicit_memory_command, store_explicit_fact


@dataclass(frozen=True)
class MemoryReceipt:
    status: str
    category: str | None = None
    hint: str = ""


# Telling the verified DSH conversation about the *actual local result*
# prevents "已经记住" from referring to a fabricated memory write.
_HINTS = {
    "saved": "【本机可信记忆回执】本轮明确称呼或喜好已核实保存到Mac统一长期记忆。请勿说它仍需审核。",
    "already_saved": "【本机可信记忆回执】本轮明确称呼或喜好此前已保存，私有库核验记录仍存在。",
    "review_pending": "【本机可信记忆回执】只产生候选，未经用户审核未写长期记忆。正常回答本轮问题即可；不必每轮提醒，审核由Mac记忆列表进行。",
    "not_supported": "【本机可信记忆回执】本轮没有可安全整理的候选；请勿承诺已保存，用户仍可在Mac手动输入记忆。",
    "disabled": "【本机可信记忆回执】目前记忆模式未授权从实体语音保存。请勿声称已写入；可在Mac记忆设置中启用。",
    "failed": "【本机可信记忆回执】本轮保存或加入审核队列未通过校验。请明确告知尚未写入，稍后在Mac查看。",
}


def _mode(config:Path)->str:
    # Reject untrusted/malformed, symlinked or broadly-readable configuration.
    if not vault._safe(config,512):
        return "off"
    try:
        data=json.loads(config.read_text(encoding="utf-8"))
    except (OSError,UnicodeError,ValueError,TypeError):
        return "off"
    if data=={"schema":1,"mode":"auto"}:return "auto"
    if data=={"schema":1,"mode":"review"}:return "review"
    return "off"


def _receipt(status:str,category:str|None=None)->MemoryReceipt:
    return MemoryReceipt(status,category,_HINTS.get(status,""))


def apply_verified_wifi_memory(transcript:str,*,verified_stt:bool=False,
                               config:Path=vault.CONFIG,
                               auto_store:Path=vault.AUTOSTORE,
                               review_queue:Path=review.QUEUE)->MemoryReceipt:
    if verified_stt is not True or not isinstance(transcript,str) or len(transcript)>600:
        return MemoryReceipt("unverified")
    requested=is_explicit_memory_command(transcript)
    fact=explicit_target(transcript,verified_stt=True) if requested else vault.extract(transcript)
    mode=_mode(config)
    if mode=="off":
        return _receipt("disabled") if requested else MemoryReceipt("none")
    if mode=="review":
        # A broad, compact proposal can originate from ordinary verified
        # dialogue; E1b remains human-controlled. No answer text is learned.
        offered=review.offer_candidate(
            transcript,verified_stt=True,config=config,queue=review_queue)
        if offered:
            return _receipt("review_pending",fact["category"] if fact else None)
        if requested and review.extract_candidate(transcript):
            return _receipt("review_pending",fact["category"] if fact else None) if (
                review.pending_count(review_queue)>0) else _receipt("failed")
        return _receipt("not_supported") if requested else MemoryReceipt("none")
    if fact is None:
        return _receipt("not_supported") if requested else MemoryReceipt("none")
    category=fact["category"]
    if mode=="auto" and auto_store==vault.AUTOSTORE and config==vault.CONFIG:
        # After the explicit, verified R308 migration, production writes MUST
        # hit only canonical E1b. Legacy JSON stays frozen as rollback evidence.
        from app.r308_unified_memory import enabled,remember_verified
        if enabled():
            status=remember_verified(fact)
            return _receipt(status,category)
    try:
        old=vault.read_store(auto_store)
        if any(x["category"]==category and x["value"]==fact["value"] for x in old):
            return _receipt("already_saved",category)
        if requested:
            saved=store_explicit_fact(fact,verified_stt=True,store=auto_store)
        else:
            saved=vault.auto_remember(transcript,verified_stt=True,
                                     config=config,store=auto_store)
        if saved and any(
            x["category"]==category and x["value"]==fact["value"]
            for x in vault.read_store(auto_store)
        ):
            return _receipt("saved",category)
    except (OSError,KeyError,ValueError,TypeError):
        pass
    return _receipt("failed",category)
