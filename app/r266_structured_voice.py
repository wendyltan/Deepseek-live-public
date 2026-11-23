"""R266: preserve every numbered step in long *spoken* replies.

Pure local formatting, no API, no microphone, no original DSH/history edit.
Avoid a title/first-three-steps digest when the verified answer has 4+ steps.
"""
from __future__ import annotations

import re

_CHINESE = {v: i for i, v in enumerate("一二三四五六七八九", 1)}
_CHINESE["十"] = 10
_ENDING = "以上为各步要点，完整解释请看Mac。"
_MAX_STEPS = 12
_PATTERNS = (
    re.compile(r"^(?:第)?([1-9]\d?)(?:[.．、)）:]|步(?:骤)?[、:：]?)\s*"),
    re.compile(r"^第([一二三四五六七八九十])步(?:骤)?[、:：]?\s*"),
    re.compile(r"^步骤\s*([一二三四五六七八九十]|[1-9]\d?)\s*[:：.、]?\s*"),
    re.compile(r"^([一二三四五六七八九十])[、.．)）]\s*"),
)

def _clean(raw: str) -> str:
    s = re.sub(r"^\s*#{1,6}\s*", "", raw.strip())
    s = re.sub(r"^\s*[-*+]\s+", "", s)
    s = re.sub(r"\[([^]]+)\]\(https?://[^\s)]+\)", r"\1", s)
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"[\\`*_~]", "", s)
    return re.sub(r"\s+", " ", s).strip(" ，、。；:：")

def _step_head(raw: str):
    stripped = re.sub(r"^\s*#{1,6}\s*", "", raw.strip())
    stripped = stripped.strip("* ")
    for pattern in _PATTERNS:
        match = pattern.match(stripped)
        if match:
            label = match.group(1)
            number = int(label) if label.isdigit() else _CHINESE[label]
            if 1 <= number <= _MAX_STEPS:
                return number, _clean(stripped[match.end():])
    return None

def numbered_steps(markdown: str) -> list[tuple[int, str]]:
    """Read only real numbered sections, keeping their supporting body text."""
    if not isinstance(markdown, str):
        return []
    groups: list[list] = []
    inside_code = False
    for raw in markdown.splitlines():
        if raw.lstrip().startswith("```"):
            inside_code = not inside_code
            continue
        if inside_code or not raw.strip() or raw.count("|") >= 2:
            continue
        head = _step_head(raw)
        if head:
            number, title = head
            groups.append([number, [title] if title else []])
        elif groups:
            body = _clean(raw)
            if len(body) >= 3 and re.search(r"[\u4e00-\u9fff]", body):
                groups[-1][1].append(body)
    # Only sequential full outlines enter structured mode: no accidental
    # interpretation of isolated versions/dates as procedural steps.
    seen: dict[int, str] = {}
    for number, parts in groups:
        if number not in seen:
            seen[number] = "。".join(x for x in parts if x).strip("。")
    if len(seen) < 4 or sorted(seen) != list(range(1, len(seen) + 1)):
        return []
    return [(n, seen[n]) for n in range(1, len(seen) + 1)]

def _excerpt(value: str, budget: int) -> str:
    clean = re.sub(r"\s+", "", value).strip("。；， ")
    if len(clean) <= budget:
        return clean
    for marker in ("。", "；", "，"):
        cut = clean.rfind(marker, max(12, budget // 2), budget + 1)
        if cut >= max(12, budget // 2):
            return clean[:cut].rstrip("。；， ")
    return clean[:budget].rstrip("。；， ")

def structured_spoken_digest(markdown: str, *, minimum_count: int = 4) -> str | None:
    steps = numbered_steps(markdown)
    if len(steps) < minimum_count:
        return None
    # 7 steps -> approx 450 Chinese characters (vs R265's 240 char cap).
    # Keep under the continuous PCM2 180-second hard limit in typical speech.
    cap = min(560, max(330, 65 * len(steps) + 20))
    per = max(22, (cap - len(_ENDING)) // len(steps) - 6)
    spoken = "".join(
        f"第{number}步，{_excerpt(body, per)}。"
        for number, body in steps
    ) + _ENDING
    assert len(spoken) <= cap
    assert all(f"第{n}步" in spoken for n, _ in steps)
    return spoken
