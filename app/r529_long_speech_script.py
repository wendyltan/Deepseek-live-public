"""Source-grounded oral scripts for *varied* verified DSH long answers.

One locally deterministic, no-cost last-stage compiler after optional Flash
summarization. Supports enumerations, sequential instructions, and ordinary
explanations/comparisons; never adds facts or paraphrases unsupported numbers.
A failed coverage check leaves the existing verified spoken text unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from app.r528_parallel_fact_voice import parallel_fact_voice

_BREAK = re.compile(r"(?<=[。！？!?；;])|(?<=\n)")
_STEP = re.compile(r"(?=第[一二三四五六七八九十0-9]{1,2}步[，:：]|(?<!\w)[1-9][.、)]\s*)")
_CONCLUSION = ("总结", "因此", "所以", "关键", "结论", "注意", "建议", "最后", "总之", "但", "不过", "风险", "前提")
_CAUSAL = ("因为", "原因", "导致", "主要", "通过", "区别", "从而", "使得", "由于", "低于", "取决于", "产生", "引起", "是由")
_CONTRAST = ("但是", "不过", "然而", "否则", "除非", "尽管", "前提", "但仍", "仍然", "风险", "警告", "禁止")
_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")
_WHOLE = re.compile(r"[。！？!?；;]$")
_TEMP = re.compile(r"\s+")


@dataclass(frozen=True)
class OralScript:
    text: str
    kind: str
    source_chars: int
    factual_items: int


def _units(spoken: str) -> list[str]:
    return [_TEMP.sub(" ", s).strip() for s in _BREAK.split(spoken)
            if _TEMP.sub(" ", s).strip()]


def _one_clause(sentence: str, cap: int) -> str:
    """Shorten only at natural comma, only when the omitted tail is not a warning."""
    sentence = sentence.strip()
    # A Markdown heading such as "该不该用" or "它主要做两件事："
    # is not an independent spoken sentence, even if it has punctuation.
    if len(sentence)<14 or sentence.endswith(("：",":")):
        return ""
    if len(sentence) <= cap:
        return sentence if _WHOLE.search(sentence) else sentence+"。"
    if any(key in sentence for key in _CONTRAST):
        return ""
    boundary = max((i for i,c in enumerate(sentence[:cap])
                    if c in "，；；、" and i >= max(14,cap//2)),default=-1)
    if boundary < 0: return ""
    val = sentence[:boundary].rstrip("，；、 ")
    return val+"。" if len(val)>=14 else ""


def _steps(spoken: str, budget: int) -> OralScript | None:
    parts = _STEP.split(spoken)
    steps = [p.strip() for p in parts if re.match(
        r"^(?:第[一二三四五六七八九十0-9]{1,2}步|[1-9][.、)])",p.strip())]
    if not 3 <= len(steps) <= 8: return None
    if any(w in spoken for w in ("警告", "禁止", "紧急")):return None
    intro = parts[0].strip() if parts else ""
    if len(intro)>62: intro = _one_clause(intro,48)
    content=[]
    closing=""
    for step in steps:
        label = re.match(r"^(?:第[一二三四五六七八九十0-9]{1,2}步[，:：]|[1-9][.、)]\s*)",step)
        if not label:return None
        detail=step[label.end():].strip()
        if not detail:return None
        # The final step may be followed by an independent conclusion;
        # never silently absorb or discard that closing warning.
        match_tail=re.search(r"(?<=。)(?:总结|最后|注意|因此)[，:：]",detail)
        if match_tail:
            closing=detail[match_tail.start():]
            detail=detail[:match_tail.start()]
        clue = _one_clause(detail, max(30,min(48, (budget-10)//len(steps))))
        if not clue:return None
        content.append(label.group(0).rstrip("，：: ")+"，"+clue.rstrip("。")+"。")
    core="".join(content)
    # Steps and the final warning outrank introductory scene-setting.
    if closing and len(core)+len(closing)>budget:
        return None
    script=(intro if intro and len(intro)+len(core)+len(closing)<=budget else "") + core + closing
    if 80 <= len(script) <= budget and len(script)<len(spoken)*.96:
        return OralScript(script,"steps",len(spoken),len(steps))
    return None


def _prose(spoken: str, budget: int) -> OralScript | None:
    units=[unit for unit in _units(spoken)
           if len(unit.strip(" #*：:；;、"))>=14 and
           not unit.rstrip().endswith(("：",":"))]
    if len(units)<4: return None
    # Repeated boilerplate is not a long-form explanation. Do not pretend
    # to have summarized it by selecting three identical repetitions.
    if len(set(units)) * 5 < len(units) * 3:
        return None
    # For narrative, preserve claim + middle reasoning + concluding caveat.
    chosen=[]
    first=_one_clause(units[0],65)
    if not first:return None
    chosen.append((0,first))
    # Last statement is necessary to avoid the historical first-paragraph-only summary.
    # A final "three examples" sentence must not be cut after example two.
    # Prefer the actual source's nearby explicit conclusion when available.
    closing_index=len(units)-1
    for i in range(len(units)-1,max(0,len(units)-7),-1):
        if any(units[i].lstrip(" #*").startswith(p) for p in
               ("一句话", "总之", "综上", "最终结论", "总结", "最后结论")):
            closing_index=i
            break
    last=_one_clause(units[closing_index],60)
    if not last:return None
    candidates=[]
    for i,part in enumerate(units[1:closing_index],1):
        snippet=_one_clause(part,65)
        if not snippet:continue
        weight=sum(1 for x in _CAUSAL if x in part)
        weight+=2 if any(x in part for x in ("原因", "关键", "区别", "具体", "主要", "当", "会在", "会使", "就会")) else 0
        weight+=max(0,2-abs(i-len(units)//2))
        candidates.append((weight,i,snippet))
    # Protect coverage across the source: one fact from the earlier middle
    # and one from the later middle, so a two-sided comparison cannot become
    # opening paragraph + only one side + conclusion.
    if not candidates:return None
    candidates.sort(key=lambda row:(-row[0],abs(row[1]-len(units)//2)))
    selected=[]
    # A caveat stating that one method cannot replace another is a
    # high-priority conclusion, not incidental middle-detail decoration.
    # Keep its *existing* sentence rather than inventing a new comparison.
    essential=next((r for r in candidates if any(x in r[2] for x in
                    ("替代不了","不能代替","不能替代","无法替代","不等于"))),None)
    if essential is not None:
        if len(first)+len(last)+len(essential[2])>budget:
            return None
        selected.append(essential)
    # Earlier/later *thirds* protect both sides of a comparison. A single
    # middle-only selection may accidentally describe one option's weakness
    # and the other option's strength, biasing the advice.
    for region in (lambda i:i<=max(2,(len(units)-1)//3),
                   lambda i:i>=max(3,2*(len(units)-1)//3)):
        available=[row for row in candidates if region(row[1]) and
                   not any(row[1]==already[1] for already in selected)]
        choice=next((row for row in available
                     if len(first)+len(last)+sum(len(x[2]) for x in selected)+
                        len(row[2])<=budget),None)
        if choice is not None:selected.append(choice)
    if not selected:return None
    chosen.extend((i,text) for _,i,text in selected)
    chosen.append((closing_index,last))
    used={0,closing_index}|{i for _,i,_ in selected}
    # If room remains, retain another important middle sentence.
    for _,i,sentence in candidates:
        if i in used or len(chosen)>=5:continue
        if sum(len(text) for _,text in chosen)+len(sentence)<=budget:
            chosen.append((i,sentence));break
    chosen.sort()
    script="".join(x for _,x in chosen)
    if not 85<=len(script)<=budget or len(script)>len(spoken)*.75:
        return None
    # Numeric claims only copied from source; shortening cannot fabricate them.
    if set(_DIGITS.findall(script)) - set(_DIGITS.findall(spoken)):
        return None
    return OralScript(script,"explanation",len(spoken),len(chosen))


def compile_oral_script(spoken: str, *, target_chars: int = 172) -> OralScript | None:
    """A no-new-cost, variety-aware *optional* oral script.

    The verified DSH original is never changed; no additional model request.
    This is a conservative fallback when an eligible long spoken text would
    otherwise trigger expensive, late or fragmented R503 generation.
    """
    if not isinstance(spoken,str) or len(spoken)<175 or len(spoken)>4000:
        return None
    if not 130<=target_chars<=210:
        raise ValueError("invalid_oral_script_budget")
    # Do not condense legal/medical safety advice, negation-sensitive warnings,
    # credentials or time-sensitive approvals with a cheap extractive parser.
    if any(w in spoken for w in ("警告", "禁止", "保密", "账号", "密码", "急救", "就医", "处方", "过敏",
                               "审批", "许可", "授权", "不能保证")):
        return None
    facts=parallel_fact_voice(spoken,limit=target_chars)
    if facts is not None:
        script,count=facts
        return OralScript(script,"enumeration",len(spoken),count)
    steps=_steps(spoken,target_chars)
    if steps:return steps
    return _prose(spoken,target_chars)


def compile_verified_source(source: str, baseline_spoken: str, *,
                            model_compacted: bool = False) -> OralScript | None:
    """Prefer the *full* verified source over an earlier 320-char digest.

    The source is already chosen by the official DSH/optional approved Flash
    workflow. Never re-run a model to improve this deterministic fallback.
    """
    if not isinstance(source,str) or not isinstance(baseline_spoken,str):
        return None
    # A prior human/model short script should stay untouched unless it still
    # exceeds the TTS budget and the original offers meaningful structure.
    if len(baseline_spoken) <= 175 or (
            model_compacted and len(baseline_spoken) <= 210):
        return None
    if 175 <= len(source) <= 4000:
        from app.voice_spoken_text import prepare_spoken_text
        from app.r458_voice_text import _line_facts, normalize_formula_reading
        try:
            source_spoken=normalize_formula_reading(prepare_spoken_text(_line_facts(source)))
        except (ValueError,RuntimeError):
            source_spoken=""
        if len(source_spoken)>=175:
            compiled=compile_oral_script(source_spoken)
            if compiled is not None:
                return compiled
    return compile_oral_script(baseline_spoken)
