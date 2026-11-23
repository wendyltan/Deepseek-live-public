"""Shorten long parallel factual lists without losing the named items.

No LLM, no payments, no generic truncation, and no special-cased planets.
Only clear "item, main trait: elaboration" formats qualify.
"""
from __future__ import annotations
import re

_PARTS = re.compile(r"[。！？!?；;\n]+")
_ITEM = re.compile(
    r"^\s*(?:[（(]?[一二三四五六七八九十0-9]{1,2}[、.)）]\s*)?"
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9·]{1,7})"
    r"[，,:：]\s*(.{2,})$"
)
_UNSAFE = ("警告", "风险", "禁止", "禁忌", "必须", "不要", "操作步骤", "注意事项", "审批")
_EXCLUDE = {"不过", "但是", "如果", "因为", "所以", "例如", "同时", "此外",
            "总之", "最后", "然后", "首先", "其次", "建议", "注意", "提示"}


def parallel_fact_voice(spoken: str, *, limit: int = 132) -> tuple[str, int] | None:
    """Return (fact-preserving spoken paragraph, items) or None.

    Abort unless >=6 and <=12 separate clearly named entries each have an
    explicit short fact in the verified text, and only intro/outro are skipped.
    No numeric/qualifier invention; source substrings are only shortened.
    """
    if not isinstance(spoken, str) or not 145 <= len(spoken) <= 4000:
        return None
    if any(w in spoken for w in _UNSAFE):
        return None
    parts = [x.strip() for x in _PARTS.split(spoken) if x.strip()]
    facts = []
    skipped = []
    for pos, text in enumerate(parts):
        match = _ITEM.match(text)
        if match is None or match.group(1) in _EXCLUDE:
            skipped.append(pos)
            continue
        name, detail = match.groups()
        if any(join in name for join in ("和", "与", "或", "以及", "其他")):
            return None
        feature = re.split(r"[，,:：]", detail, maxsplit=1)[0].strip(" ，：:、")
        if not 2 <= len(feature) <= 24 or len(name) < 2:
            return None
        facts.append((pos, name, feature))
    if not 6 <= len(facts) <= 12 or len(skipped) > 2:
        return None
    if len({name for _,name,_ in facts}) != len(facts):
        return None
    # Any omitted prose must be a brief introduction or closing aside, never
    # an unexplained missing fact from the middle of the answer.
    if any(facts[0][0] < i < facts[-1][0] for i in skipped):
        return None
    # Keep a short *existing* introduction, not a newly generated claim.
    prefix = (parts[0] if skipped and skipped[0] == 0 and
              len(parts[0]) <= 36 and parts[0].endswith(("：", ":"))
              else "从近到远，" if "从近到远" in spoken[:55] else "")
    compact = prefix + "；".join(name+"，"+feature for _,name,feature in facts)+"。"
    if not 65 <= len(compact) <= limit or len(compact)*5 >= len(spoken)*4:
        return None
    if any(name not in spoken or feature not in spoken for _,name,feature in facts):
        return None
    return compact, len(facts)

def parallel_item_names(spoken: str) -> tuple[str, ...]:
    """Verified source labels for multi-item Flash summary coverage checks.

    Requiring 6+ contiguous explicit entries prevents false coverage guards
    on arbitrary prose. A model is never retried on validation failure.
    """
    if not isinstance(spoken,str) or not 145<=len(spoken)<=4000:
        return ()
    parts=[x.strip() for x in _PARTS.split(spoken) if x.strip()]
    found=[];skipped=[]
    for i,part in enumerate(parts):
        m=_ITEM.match(part)
        if m is None or m.group(1) in _EXCLUDE or any(
                word in m.group(1) for word in ("和","与","以及","其他")):
            skipped.append(i)
        else:
            found.append((i,m.group(1)))
    if (not 6<=len(found)<=12 or len(skipped)>2 or
        len({name for _,name in found})!=len(found) or
        any(found[0][0]<i<found[-1][0] for i in skipped)):
        return ()
    return tuple(name for _,name in found)
