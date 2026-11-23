"""Pure, safe preset voice intentions for the Deepseek-live companion.

No ASR, no model calls, no operating-system side effects. All commands require
a confirmed STT result and a matching, live, bounded voice session. Actions
with side effects return *no success speech* until the caller supplies a real
device/DSH receipt. Non-preset utterances are marked delegation, not preset.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Literal

ALIAS = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9]{1,12}$")
PREFIX = re.compile(r"[，,。.!！?？\s]+")
NICKNAME = re.compile(r"^(?:以后|从今往后|今后)?(?:请)?叫我(?P<name>[\u4e00-\u9fffA-Za-z0-9]{1,12})$")
WAKE = frozenset((
    "大肥鱼", "你好大肥鱼", "嗨大肥鱼", "大肥鱼在吗", "大肥鱼你在吗",
    "deepseek大肥鱼", "你好deepseek", "你好deepseek大肥鱼",
))
# The Chinese ASR frequently substitutes an identically pronounced character.
# Apply this tiny, full-utterance alias map ONLY to the local wake command,
# never to chat body, saved preferences, tool names or broad keyword matching.
# Avoid Levenshtein fuzzy matching: an arbitrary phrase must not wake/execute.
_WHALE_SOUND = frozenset(("大肥鱼", "大飞鱼", "大菲鱼", "大非鱼", "大肥余", "大飞余"))
_WAKE_START = frozenset(("", "你好", "嗨", "嘿", "哈喽"))
_WAKE_END = frozenset(("", "你好", "在吗"))
_WAKE_PHONETIC = frozenset(
    prefix + fish + suffix for prefix in _WAKE_START for fish in _WHALE_SOUND
    for suffix in _WAKE_END if prefix == "" or suffix == ""
)
# Prefix-only variants are common; partial words aren't accepted. Chinese
# punctuation is already stripped by normalize(), not the raw user transcript.

CANCEL = frozenset(("取消", "算了", "不用了", "不确认", "否", "不改了"))
CONFIRM = frozenset(("确认", "确定", "是的", "好", "就这样", "对"))
STATUS = frozenset(("你在做什么", "你现在在干什么", "当前在做什么", "当前状态", "你在忙什么"))
QUIET = frozenset(("安静一点", "声音小一点", "调低音量", "小点声", "音量小一点", "大肥鱼声音小一点", "大肥鱼音量小一点"))
LOUDER = frozenset(("声音大一点", "调高音量", "大点声", "音量大一点", "大肥鱼声音大一点", "大肥鱼音量大一点"))
STOP = frozenset(("停止说话", "闭嘴", "别说了", "先别说了"))
CLOCK = frozenset(("现在几点", "现在几点了", "几点了", "报个时"))
IDENTITY = frozenset(("你是谁", "你叫什么", "你叫什么名字", "你是大肥鱼吗"))
HELP = frozenset(("帮助", "你会做什么", "你能做什么", "能帮我什么", "你会什么", "大肥鱼你会什么"))
PERSONA = frozenset(("今天心情怎么样", "你今天开心吗", "心情怎么样"))
PRESET_WORDING = {
    "wake": "大肥鱼在呢！有什么事呀？",
    "identity": "我是大肥鱼！会认真帮你做事，也会偶尔摸个小鱼～",
    "help": "可以叫我大肥鱼、问时间和状态、调音量，或者让我记住你喜欢的称呼。更复杂的事，要交给实时模型啦！",
    "persona": "精神满满！说吧，今天想让本鱼帮你干点什么？",
    "cancel_pending": "好呀，那先不改啦。",
}
PENDING_SECONDS = 20.0


@dataclass(frozen=True)
class PresetResult:
    intent: str
    source: Literal["preset", "delegation"] = "preset"
    reply: str | None = None
    needs_confirmation: bool = False
    proposed_key: str | None = None
    proposed_value: str | None = None
    action: str | None = None
    live_model_needed: bool = False


def normalize(text: str) -> str:
    if not isinstance(text, str) or len(text) > 128:
        raise ValueError("transcript_invalid")
    return PREFIX.sub("", text).strip()  # Preserve Wendy / nickname letter case


def classify(text: str, *, verified_stt: bool,
             existing_pending: bool = False) -> PresetResult:
    """Stateless intent only. Never claims a device/clock/tool operation happened."""
    if verified_stt is not True:
        raise ValueError("unverified_audio_transcript")
    s = normalize(text)
    if not s:
        return PresetResult("empty")
    folded = s.casefold()
    if existing_pending and folded in CONFIRM:
        return PresetResult("confirm_pending", action="confirm_pending")
    if existing_pending and folded in CANCEL:
        return PresetResult("cancel_pending", reply=PRESET_WORDING["cancel_pending"],
                            action="cancel_pending")
    if folded in CONFIRM:
        return PresetResult("nothing_to_confirm", reply="咦，现在没有需要确认的设置哦。")
    if folded in WAKE or folded in _WAKE_PHONETIC:
        return PresetResult("wake", reply=PRESET_WORDING["wake"], action="wake")
    if folded in IDENTITY:
        return PresetResult("identity", reply=PRESET_WORDING["identity"])
    if folded in HELP:
        return PresetResult("help", reply=PRESET_WORDING["help"])
    if folded in PERSONA:
        return PresetResult("persona", reply=PRESET_WORDING["persona"])
    if folded in STOP:
        return PresetResult("stop_speaking", action="interrupt_playback")
    if folded in STATUS:
        return PresetResult("status", action="query_verified_state")
    if folded in QUIET:
        return PresetResult("volume_down", action="volume_down")
    if folded in LOUDER:
        return PresetResult("volume_up", action="volume_up")
    if folded in CLOCK:
        return PresetResult("clock", action="mac_local_clock")
    match = NICKNAME.fullmatch(s)
    if match and ALIAS.fullmatch(match.group("name")):
        name = match.group("name")
        return PresetResult("set_user_name", reply=f"以后叫你{name}，可以吗？",
                            needs_confirmation=True,
                            proposed_key="user_name", proposed_value=name)
    if s.startswith(("以后你叫", "今后你叫")):
        name = s.split("叫", 1)[1]
        if ALIAS.fullmatch(name):
            return PresetResult("set_whale_name",
                                reply=f"给本鱼取名叫{name}？可以呀，要确认吗？",
                                needs_confirmation=True,
                                proposed_key="whale_name", proposed_value=name)
    if folded in CANCEL:
        # A voice cancel must be sent to the *current* session, only if its
        # task is verified. Never announce cancellation without a receipt.
        return PresetResult("cancel_request", action="cancel_verified_task")
    # Weather, music, timers, reminders, appliance controls and free chatting
    # must use actual available tools/permissions or the real model.
    return PresetResult("pass_to_model", source="delegation", live_model_needed=True)


def confirmed_action_reply(result: PresetResult, *,
                           executed: bool,
                           actual_volume: int | None = None,
                           when: datetime | None = None,
                           verified_phase: str | None = None) -> str:
    """Only render dynamic/local-action speech *after* a trustworthy receipt."""
    if executed is not True:
        return "唔，这件事还没有完成。我会如实告诉你，不能装作成功啦。"
    if result.action == "volume_up":
        if type(actual_volume) is not int or not 0 <= actual_volume <= 100:
            raise ValueError("volume_receipt_required")
        return "好啦，音量已经调高一档～"
    if result.action == "volume_down":
        if type(actual_volume) is not int or not 0 <= actual_volume <= 100:
            raise ValueError("volume_receipt_required")
        return "好啦，我小声一点点～"
    if result.action == "mac_local_clock":
        if not isinstance(when, datetime) or when.tzinfo is None:
            raise ValueError("verified_local_clock_required")
        return f"现在是{when.hour}点{when.minute:02d}分哦。"
    if result.action == "query_verified_state":
        if verified_phase not in {"idle", "listening", "transcribing", "thinking",
                                  "tool_pending", "approval_pending",
                                  "voice_generating", "speaking", "error"}:
            raise ValueError("actual_phase_receipt_required")
        words = {
            "idle": "正待机呢，随时听候差遣！",
            "listening": "我在认真听你说话呢。",
            "transcribing": "正在努力听清刚刚那句话。",
            "thinking": "我正在认真想你的问题。",
            "tool_pending": "正在执行任务，等原生工具回执呢。",
            "approval_pending": "有个操作正在等你亲自批准。",
            "voice_generating": "我正在准备把回答念出来。",
            "speaking": "我正在说话哦。",
            "error": "刚才遇到了一点问题，正在等你确认下一步。",
        }
        return words[verified_phase]
    if result.action == "cancel_verified_task":
        return "好，刚刚那项任务已取消。"
    if result.action == "interrupt_playback":
        # A mute/stop should usually be silent to avoid further interruption.
        return ""
    raise ValueError("result_is_not_dynamic_action")


class PresetVoiceSession:
    def __init__(self, session_id: str, store,
                 monotonic: Callable[[], float] = time.monotonic):
        if not isinstance(session_id, str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{8,64}", session_id
        ):
            raise ValueError("session_id_invalid")
        self.session_id = session_id
        self.store = store
        self.monotonic = monotonic
        self.pending: tuple[str, str] | None = None
        self.pending_since: float | None = None

    def handle(self, text: str, *, session_id: str,
               verified_stt: bool) -> PresetResult:
        if session_id != self.session_id:
            raise ValueError("cross_session_preset_command")
        if verified_stt is not True:
            raise ValueError("unverified_audio_transcript")
        now = self.monotonic()
        expired = False
        if self.pending is not None and self.pending_since is not None:
            if now < self.pending_since or now - self.pending_since > PENDING_SECONDS:
                expired = True
                self.pending = None
                self.pending_since = None
        if expired and normalize(text).casefold() in CONFIRM:
            return PresetResult("confirmation_expired",
                                reply="刚才的确认已经过期啦；想改称呼，再告诉我一次就好。")
        result = classify(text, verified_stt=verified_stt,
                          existing_pending=self.pending is not None)
        if result.intent == "confirm_pending":
            if self.pending is None:
                raise ValueError("pending_command_missing")
            key, value = self.pending
            self.store.put_explicit(key, value, confirmed=True)
            self.pending = None
            self.pending_since = None
            spoken = (
                f"记住啦，以后就叫你{value}！"
                if key == "user_name"
                else f"好耶，那本鱼以后就叫{value}啦！"
            )
            return replace(result, reply=spoken)
        if result.intent == "cancel_pending":
            self.pending = None
            self.pending_since = None
        elif result.needs_confirmation:
            self.pending = (result.proposed_key, result.proposed_value)
            self.pending_since = now
        elif result.intent != "empty" and self.pending is not None:
            self.pending = None
            self.pending_since = None
        return result
