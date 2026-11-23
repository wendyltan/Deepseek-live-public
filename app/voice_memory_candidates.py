"""Review-first, local candidate suggestions from verified ESP32 speech.

Only short, durable first-person facts and preferences are proposed. Nothing is
silently promoted into E1b: the existing Mac per-fact approval is mandatory.
No DSH answer, tool result, mic recording or full raw chat is persisted here.
"""
from __future__ import annotations
import json
import os
import re
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path.home() / "Library/Application Support/Deepseek-live/companion-native"
CONFIG = ROOT / "memory-candidate-mode.json"
QUEUE = ROOT / "voice-memory-candidates.json"
MAX_QUEUE = 24
MAX_BYTES = 32768
TTL = 14 * 86400
MAX_SUGGESTION = 200

# Sensitive information is never turned into an automatic suggestion.
BANNED = (
    "密码", "账号", "银行卡", "身份证", "住址", "家庭住址", "详细地址",
    "电话号码", "手机号", "验证码", "密钥", "口令", "token", "api key",
    "疾病", "病史", "诊断", "用药", "处方", "怀孕", "备孕",
    "宗教", "政治立场", "党派", "性取向", "性行为", "工资", "收入",
    "存款", "贷款", "欠款", "银行", "医保", "社保", "护照",
)
PERSONAL = re.compile(r"^(?:大肥鱼[，, ]?)?(?:我(?:的名字)?叫|请叫我)([\u4e00-\u9fffA-Za-z0-9]{2,16})[。！!]*$")
LIKES = re.compile(r"^(?:大肥鱼[，, ]?)?我(?:很|特别|比较)?喜欢([\u4e00-\u9fffA-Za-z0-9、 ]{2,32})[。！!]*$")
PERSISTENT = re.compile(
    r"(?:^|[，。；!?！？]\s*)(我(?:平时|通常|经常|一直|习惯|最近|目前|这段时间|"
    r"正在|现在|打算|准备|计划|希望|偏好|倾向于|更喜欢|不喜欢|比较喜欢|"
    r"平常|一般|常常|每天|每周|养了|家有|在学|想学|在做|想做|"
    r"正在用|目前用|用的是|的爱好是|的目标是|的猫叫|的狗叫|的宠物叫)"
    r"[^。！？!?]{3,195})"
)
EXPLICIT = re.compile(
    r"^(?:(?:嘿[，, ]*)?大肥鱼[，, ]*)?(?:请|麻烦你)?(?:帮我)?"
    r"(?:记住|记下|保存)(?:一下|这个)?[：:，, ]*(.{3,200})[。！! ]*$"
)
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
LONG_NUMBERS = re.compile(r"(?<!\d)\d{7,}(?!\d)")
QUESTION = re.compile(r"(?:吗|呢|是不是|如何|为什么|怎么办|有没有|能不能|可不可以)[？?]?$")
GENERIC = ("你好", "再见", "谢谢", "早上好", "晚上好", "你在吗", "我在呢")


def _clean(text):
    return re.sub(r"\s+", " ", text.strip(" ，。！？!?:：;；\n\r\t"))


def _safe_suggestion(s):
    if not s or len(s) < 5 or len(s) > MAX_SUGGESTION:
        return False
    low = s.casefold()
    if any(word in low for word in BANNED) or EMAIL.search(s) or LONG_NUMBERS.search(s):
        return False
    if "http://" in low or "https://" in low or "\\" in s:
        return False
    if QUESTION.search(s) or s in GENERIC:
        return False
    if any(x in s for x in ("帮我执行", "替我删除", "现在转账")):
        return False
    return True


def extract_candidate(transcript):
    """Produce an editable, bounded first-person summary; no model or remote call."""
    if not isinstance(transcript, str) or not 5 <= len(transcript) <= 600:
        return None
    text = _clean(transcript)
    # Keep old exact name/likes extraction for compatibility and clarity.
    for exp, prefix in ((PERSONAL, "我的名字叫"), (LIKES, "我喜欢")):
        found = exp.fullmatch(text)
        if found:
            candidate = prefix + found[1].strip()
            return candidate if _safe_suggestion(candidate) else None
    from app.r141_explicit_voice_memory import explicit_target
    from app.r38_memory_loop import extract as extract_narrow
    fact = explicit_target(text, verified_stt=True) or extract_narrow(text)
    if fact is not None:
        candidate = {"name": "我的名字叫", "likes": "我喜欢",
                     "dislikes": "我不喜欢"}[fact["category"]] + fact["value"]
        return candidate if _safe_suggestion(candidate) else None
    # Explicit consent to remember can propose broader facts even without the
    # narrow factual grammar. Its contents still require human review.
    command = EXPLICIT.fullmatch(text)
    if command:
        snippet = _clean(command[1])
        if snippet.startswith(("我", "我的")) and _safe_suggestion(snippet):
            return snippet
    # Everyday speech: pick a self-contained, durable clause even when the
    # overall turn is a question or contains unrelated content.
    for match in PERSISTENT.finditer(text):
        clause = _clean(re.split(r"[，；](?:不过|但是|可是|然后|另外|所以|今天|现在想问|我想问)", match[1], maxsplit=1)[0])
        if len(clause) > MAX_SUGGESTION:
            clause = clause[:MAX_SUGGESTION].rstrip("，； ")
        if _safe_suggestion(clause):
            return clause
    # Family / pet / tools: bounded descriptive statements.
    for start in ("我家有", "我养了", "我的宠物叫", "我的猫叫", "我的狗叫", "我用的是", "我在用", "我的目标是"):
        i = text.find(start)
        if i >= 0 and (i == 0 or text[i - 1] in "，。； "):
            clause = _clean(re.split(r"[。！？!?]", text[i:], maxsplit=1)[0])
            if _safe_suggestion(clause):
                return clause
    return None


def _private_file(p, maximum):
    try:
        st = p.lstat()
        return (p.is_file() and not p.is_symlink() and st.st_uid == os.getuid()
                and 0 < st.st_size <= maximum and (st.st_mode & 0o077) == 0)
    except OSError:
        return False


def _similar(a, b):
    def relevant(s):
        s = re.sub(r"^我(?:平时|经常|最近|现在|目前|正在|计划|希望|喜欢|不喜欢)", "", s)
        return set(s[i:i + 2] for i in range(max(0, len(s) - 1)))
    aa, bb = relevant(a), relevant(b)
    if not aa or not bb:
        return False
    return len(aa & bb) / max(1, min(len(aa), len(bb))) >= .55


def offer_candidate(transcript, *, verified_stt=False, config=CONFIG, queue=QUEUE,
                    now=time.time, identifier=lambda: uuid4().hex):
    if verified_stt is not True:
        return False
    suggestion = extract_candidate(transcript)
    if not suggestion or not _private_file(config, 512):
        return False
    try:
        if json.loads(config.read_text()) != {"schema": 1, "mode": "review"}:
            return False
        if queue.exists() and not _private_file(queue, MAX_BYTES):
            return False
        before = json.loads(queue.read_text()) if queue.exists() else {"schema": 1, "items": []}
        if before.get("schema") != 1 or not isinstance(before.get("items"), list):
            return False
        current = [x for x in before["items"]
                   if isinstance(x, dict) and set(x) == {"id", "text", "created_at"}
                   and isinstance(x.get("id"), str) and re.fullmatch(r"[a-f0-9]{32}", x["id"])
                   and isinstance(x.get("text"), str) and 0 < len(x["text"]) <= MAX_SUGGESTION
                   and isinstance(x.get("created_at"), int) and 0 <= now() - x["created_at"] <= TTL]
        if any(x["text"] == suggestion for x in current):
            return False
        # Combine overlapping durable statements into one proposal while
        # retaining the old ID, making one coherent human approval action.
        for x in reversed(current[-8:]):
            if _similar(x["text"], suggestion):
                if suggestion not in x["text"]:
                    joined = x["text"] + "；" + suggestion
                    if len(joined) <= MAX_SUGGESTION:
                        x["text"] = joined
                    elif len(suggestion) > len(x["text"]):
                        x["text"] = suggestion
                    else:
                        return False
                    break
                return False
        else:
            current.append({"id": identifier(), "text": suggestion, "created_at": int(now())})
        current = current[-MAX_QUEUE:]
        raw = json.dumps({"schema": 1, "items": current},
                         ensure_ascii=False, separators=(",", ":")).encode()
        if len(raw) > MAX_BYTES:
            return False
        queue.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (queue.parent.is_symlink() or queue.parent.stat().st_mode & 0o077
                or queue.parent.stat().st_uid != os.getuid()):
            return False
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=queue.parent, prefix=".memory-proposal-",
                                             delete=False) as handle:
                temp = Path(handle.name)
                os.fchmod(handle.fileno(), 0o600)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, queue)
        finally:
            if temp:
                temp.unlink(missing_ok=True)
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def pending_count(queue=QUEUE, now=time.time):
    """Privacy-limited counter for badges; never returns proposal text."""
    if not _private_file(queue, MAX_BYTES):
        return 0
    try:
        data = json.loads(queue.read_text())
        if data.get("schema") != 1 or not isinstance(data.get("items"), list):
            return 0
        return sum(isinstance(v, dict) and isinstance(v.get("created_at"), int)
                   and 0 <= now() - v["created_at"] <= TTL
                   for v in data["items"][:MAX_QUEUE])
    except (OSError, ValueError, TypeError):
        return 0
