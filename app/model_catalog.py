"""DeepSeek model discovery and local model-switch commands.

GET /models is a metadata lookup (no chat completion). Never print credentials.
Command parser is deliberately reusable for later STT transcription.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request

MODEL_ENDPOINT = "https://api.deepseek.com/models"
_catalog_lock = threading.RLock()
_catalog = {"fingerprint": "", "expires": 0., "items": []}


class DiscoveryError(RuntimeError):
    pass


def get_models(key: str, *, refresh: bool = False) -> list[dict]:
    if not key:
        raise DiscoveryError("未配置 DeepSeek API 密钥")
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()
    with _catalog_lock:
        if not refresh and _catalog["fingerprint"] == fingerprint and time.monotonic() < _catalog["expires"]:
            return [dict(x) for x in _catalog["items"]]
    request = urllib.request.Request(
        MODEL_ENDPOINT,
        method="GET",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise DiscoveryError("模型列表接口返回 HTTP " + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DiscoveryError("暂时无法从 DeepSeek 获取模型列表，请稍后刷新") from None
    except (ValueError, TypeError):
        raise DiscoveryError("DeepSeek 模型列表返回格式异常") from None

    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise DiscoveryError("DeepSeek 模型列表缺少 data 字段")
    items = []
    seen = set()
    for item in data["data"]:
        if not isinstance(item, dict):
            continue
        ident = item.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{2,80}", ident):
            continue
        # Text chat is the first P1 feature. Do not expose image-only models as chat choices.
        modalities = item.get("input_modalities", ["text"])
        if isinstance(modalities, list) and modalities and "text" not in modalities:
            continue
        if ident in seen:
            continue
        seen.add(ident)
        title = item.get("name")
        items.append({"id": ident, "name": (title if isinstance(title, str) and title else ident)[:90]})
    if not items:
        raise DiscoveryError("DeepSeek 当前未返回可用于文字对话的模型")
    items.sort(key=lambda x: (0 if x["id"] == "deepseek-flash" else 1, x["id"]))
    with _catalog_lock:
        _catalog.update(fingerprint=fingerprint, expires=time.monotonic() + 300, items=items)
    return [dict(x) for x in items]


def select_default_model(models: list[dict]) -> str:
    names = [m["id"] for m in models]
    return "deepseek-flash" if "deepseek-flash" in names else names[0]


# Clear imperative only: if speech recognition adds a polite preface or
# "模型/版本", still handle it locally. Questions *about* changing models
# are ordinary chat and must not unexpectedly flip the selected model.
_COMMAND = re.compile(
    r"^(?:大肥鱼[，,！!。\s]*)?"
    r"(?:(?:你能不能|能不能|可不可以|你能|你可以|你帮我|你给我|我想|我要|现在|麻烦你|麻烦|请你|请|帮我|给我)\s*)*"
    r"(?:把(?:当前)?模型\s*)?"
    r"(?:切换模型回|换模型回|切换到|切换为|切换成|切换回|切到|切回|换到|换成|换回|改到|改成|改用|切换模型|换模型)\s*[:：]?\s*"
    r"(.+?)\s*(?:好不好|好吗|可以吗|行吗|吧|呀|啊|嘛|呢)?[。！!？?]*\s*$",
    flags=re.IGNORECASE,
)

# A second-stage speech-robust router. An explicit switching request must
# never become a paid ordinary chat that merely *claims* to have switched.
# Only invoke when a user is clearly asking for a state change, not discussing
# how switching works; if the destination is ambiguous, return clarification.
_MODEL_SWITCH_INTENT = re.compile(
    r"(?:切换|切到|切回|换到|换回|换成|改用|改成|调到|调成|换模型|换个模型|把模型|换一下模型|换一个模型)"
)
_MODEL_SWITCH_INFO = re.compile(r"(?:怎么|如何|教程|解释|为什么|怎样|假如|如果|教我|(?:有什么|有啥)(?:影响|区别|变化))")
_TARGET_PRO = re.compile(r"(?:deepseek[-_.\s]*v?4?[-_.\s]*pro|(?<![A-Za-z])pro(?![A-Za-z])|普罗|普洛|专业版|专业模型|专业模式|坡肉)", re.I)
_TARGET_FLASH = re.compile(r"(?:deepseek[-_.\s]*v?4(?:\.1)?[-_.\s]*flash|(?<![A-Za-z])flash(?![A-Za-z])|弗拉希|弗拉什|弗拉士|快速模型|快速版|闪电模型|闪电版)", re.I)


def _spoken_model_intent(message: str, models: list[dict]) -> dict | None:
    raw = message.strip()
    if len(raw) > 95 or not _MODEL_SWITCH_INTENT.search(raw) or _MODEL_SWITCH_INFO.search(raw):
        return None
    matched = []
    if _TARGET_PRO.search(raw):
        matched.append("deepseek-v4-pro")
    if _TARGET_FLASH.search(raw):
        matched.append("deepseek-flash")
    # Unknown, missing or overlapping model names must not trigger a guess.
    allowed = {model["id"]: model for model in models}
    if len(matched) == 1 and matched[0] in allowed:
        m = allowed[matched[0]]
        return {"type":"model_switch","model":m["id"],"name":m["name"]}
    return {"type":"model_switch_clarify",
            "message":"我听到了切换模型的要求，但没确定目标。请明确说“切换到 Pro”或“切换到 Flash”，也可以直接点左侧模型列表。当前模型没有改变。"}


def parse_model_command(message: str, models: list[dict]) -> dict | None:
    """Returns None for ordinary chat, or a structured successful/error command.

    A backend-confirmed command is never sent to paid completion. This same
    function accepts voice STT text when P1 microphone input is later enabled.
    """
    if not isinstance(message, str) or len(message) > 100:
        return None
    match = _COMMAND.fullmatch(message.strip())
    if not match:
        return _spoken_model_intent(message, models)
    raw = match.group(1).strip().strip("。！!.？，, ").lower()
    # Only trailing polite particles / generic model nouns may be removed;
    # never guess a model from arbitrary surrounding dialogue.
    raw = re.sub(r"(?:好不好|可以吗|行吗|好吗|模型|版本|那个模型|那个版本|吧|呀|啊|嘛|呢|吗)+$", "", raw).strip()
    compact = re.sub(r"[\s_.-]+", "", raw)
    aliases = {
        "flash": "deepseek-flash",
        "v41flash": "deepseek-flash",
        "v4flash": "deepseek-flash",
        "快速": "deepseek-flash",
        "快速模型": "deepseek-flash",
        "闪电": "deepseek-flash",
        "闪电模型": "deepseek-flash",
        "闪电版": "deepseek-flash",
        "pro": "deepseek-v4-pro",
        "v4pro": "deepseek-v4-pro",
        "普罗": "deepseek-v4-pro",
        "普洛": "deepseek-v4-pro",
        "专业版": "deepseek-v4-pro",
        "专业模型": "deepseek-v4-pro",
        "flash版本": "deepseek-flash",
        "弗拉什": "deepseek-flash",
        "弗拉希": "deepseek-flash",
        "弗拉士": "deepseek-flash",
    }
    allowed = {m["id"]: m for m in models}
    for item in models:
        if raw in (item["id"].lower(), item["name"].lower()):
            return {"type": "model_switch", "model": item["id"], "name": item["name"]}
    desired = aliases.get(compact)
    if desired in allowed:
        return {"type": "model_switch", "model": desired, "name": allowed[desired]["name"]}
    available = "、".join(item["name"] for item in models)
    return {"type": "model_switch_error", "message": "没有找到这个模型。当前可切换：" + available}
