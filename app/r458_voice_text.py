"""R458 Wi-Fi-only content-bearing spoken rendering.

One authoritative DSH reply is preserved unchanged in native Mac history.
Converts Markdown tables to actual row facts, retains complete clauses and
key conclusions under a bounded 320-character spoken budget, and normalizes
simple formulas before Qwen. No second model, no network, no forced 'Mac查看'.
"""
from __future__ import annotations
import re
from app.voice_spoken_text import prepare_spoken_text
from app.r266_structured_voice import numbered_steps

BUDGET=320
_BACKTICKS=re.compile(r"(?ms)^\s*```.*?^\s*```\s*$")
_TABLE_SEPARATOR=re.compile(r"^\s*\|?[\s:—\-+|]+\|?\s*$")
_WORDS="零一二三四五六七八九"
def _zh_integer(num:str)->str:
    try:n=int(num)
    except ValueError:return num
    if n<0 or n>99999:return num
    if n==0:return "零"
    units=(10000,1000,100,10,1)
    words=("万","千","百","十","")
    out="";remaining=n;zero=False
    for power,unit in zip(units,words):
        digit=remaining//power
        remaining%=power
        if digit:
            if zero and out:out+="零"
            zero=False
            if not (power==10 and digit==1 and not out):
                out+=_WORDS[digit]
            out+=unit
        elif out and remaining:
            zero=True
    return out
def _spoken_number(token:str)->str:
    """Exact decimal pronunciation, without changing mathematical value."""
    if "." not in token:return _zh_integer(token)
    whole,frac=token.split(".",1)
    if not frac or not whole:return token
    if len(whole)>5 or len(frac)>6:return token
    return _zh_integer(whole)+"点"+"".join(_WORDS[int(d)] for d in frac)

def normalize_formula_reading(text:str)->str:
    """Read arithmetic, powers and percentages without numeric reinterpretation.

    e.g. 175% and 1.75% MUST stay distinct. Do not invent results,
    simplify fractions, or rewrite dates/URLs/technical identifiers.
    """
    if not isinstance(text,str):raise ValueError("spoken_math_requires_text")
    def convert_fraction(m):
        left,right=m.groups()
        if (left.startswith("0") and len(left)>1 or
                right.startswith("0") and len(right)>1):
            return m.group(0)
        prev=text[max(0,m.start()-8):m.start()]
        joiner="比" if re.search("比例|比分|配比|比值",prev) else "除以"
        return _zh_integer(left)+joiner+_zh_integer(right)
    text=re.sub(r"(?<![\dA-Za-z./])([0-9]{1,5})\s*/\s*([0-9]{1,5})(?![\dA-Za-z/])",
                convert_fraction,text)
    # No token replacement inside URLs or bare file paths. Only mathematical
    # operators whose pronunciation is unambiguous.
    text=text.replace("≈","约等于").replace("≃","约等于").replace("≒","约等于")
    text=text.replace("≤","小于或等于").replace("≥","大于或等于")
    def power(m):
        base,degree=m.groups()
        name="平方" if degree=="2" else "立方" if degree=="3" else _zh_integer(degree)+"次方"
        return base+"的"+name
    text=re.sub(r"(?<![0-9A-Za-z_./])([a-zA-Z]|[1-9][0-9]{0,3})\^([2-9])(?![0-9A-Za-z_/])",power,text)
    # Put percent BEFORE decimals, so 1.75% becomes 百分之一点七五
    # while 175% becomes 百分之一百七十五 (not 1.75%).
    def percent(m):
        return "百分之"+_spoken_number(m.group(1))
    text=re.sub(r"(?<![0-9A-Za-z_./])([0-9]{1,5}(?:\.[0-9]{1,6})?)\s*%(?![0-9A-Za-z_])",percent,text)
    # Decimal numbers in ordinary mathematical prose; remain exact.
    text=re.sub(r"(?<![0-9A-Za-z_./])([0-9]{1,5}\.[0-9]{1,6})(?![0-9A-Za-z_/])",
                lambda m:_spoken_number(m.group(1)),text)
    return text

def _line_facts(markdown:str)->str:
    lines=markdown.splitlines()
    out=[];headers=None;in_table=False
    for line in lines:
        s=line.strip()
        if not s:continue
        if s.startswith("|​"):s=s.replace("​","")
        if s.count("|")>=2:
            cells=[re.sub(r"[*_`]", "",v).strip() for v in s.strip("|").split("|")]
            if all(re.fullmatch(r"[:+\-\s]+",v or "-") for v in cells):continue
            if headers is None:
                headers=cells;in_table=True;continue
            # Keep all rows before applying the shared spoken budget.
            value="，".join(
                ((head+"是"+item) if head and len(head)<=8 and head not in item
                 else item)
                for head,item in zip(headers,cells) if item)
            if value:out.append(value.rstrip("。；")+"。")
            continue
        if in_table:headers=None;in_table=False
        if _TABLE_SEPARATOR.fullmatch(s):continue
        out.append(line)
    return "\n".join(out)

def _clauses(text:str)->list[str]:
    return [x.strip(" ，；;") for x in re.split(r"(?<=[。！？；])|(?<=\n)",text)
            if x.strip(" ，；;")]

def voice_ready_reply(markdown:str,*,limit:int=BUDGET)->tuple[str,bool]:
    """Return spoken-only version + whether deterministic shortening happened."""
    if not isinstance(markdown,str) or not markdown.strip():
        raise ValueError("empty_verified_dsh_reply")
    if not 120<=limit<=600:raise ValueError("unsafe_wifi_speech_budget")
    clean=_BACKTICKS.sub("",markdown)
    converted=_line_facts(clean)
    if not converted.strip():
        return "这份回答主要是代码，语音暂时不能准确朗读代码内容。",True
    normalized=prepare_spoken_text(converted)
    normalized=normalize_formula_reading(normalized)
    if not normalized.strip():
        raise ValueError("empty_wifi_spoken_facts")
    if len(normalized)<=limit:return normalized,False
    # A verified 4-12-step answer must retain every *step*, not just
    # the first 320 characters or the old forced Mac disclosure.
    steps=numbered_steps(markdown)
    if steps:
        # R511: give the cause, the actions and the conclusion separate space.
        # R510 selected only the numbered tail of a 497-char explanation,
        # dropping "why the window fogs". This is a local factual extract,
        # not a claim of model-quality abstract summarization.
        paragraphs=[p.strip() for p in re.split(r"\n\s*\n",markdown) if p.strip()]
        def complete_clause(text:str,cap:int)->str:
            text=normalize_formula_reading(prepare_spoken_text(text))
            if len(text)<=cap:return text
            # Prefer an actual clause boundary, not an arbitrary mid-word cut.
            bounds=[i+1 for i,ch in enumerate(text[:cap]) if ch in "。！？；，"]
            valid=[i for i in bounds if i>=max(12,cap//3)]
            return text[:max(valid)].rstrip("，；") if valid else ""
        beginning=paragraphs[0] if paragraphs else ""
        last=paragraphs[-1] if paragraphs else ""
        intro=complete_clause(beginning,min(95,limit//3))
        if len(intro)<13:intro=""
        tail=""
        if last!=beginning and not re.match(r"^\d+[.、)]",last):
            last_lines=re.split(r"(?<=[。！？])",last)
            tail=complete_clause(next((s for s in reversed(last_lines)
                                       if len(s.strip())>=15),last),min(85,limit//3))
            if len(tail)<12:tail=""
        # Never swallow an explicit conclusion by a per-step allocation.
        reserve=limit-len(intro)-len(tail)-len(steps)*5
        if reserve<len(steps)*12:
            tail="";reserve=limit-len(intro)-len(steps)*5
        if reserve<len(steps)*12:
            intro="";reserve=limit-len(steps)*5
        cap=max(12,reserve//len(steps))
        utterances=[]
        # Natural short voice plans must not sound like a copy-pasted checklist.
        # Preserve all source actions, order and facts. Keep explicit labels
        # for longer 6+ step tutorials whose numbering matters.
        conversational=bool(intro and len(steps)<=5)
        transitions=("先","再","接着","然后","另外")
        for index,(number,body) in enumerate(steps):
            clean=normalize_formula_reading(prepare_spoken_text(body))
            excerpt=complete_clause(clean,cap)
            if not excerpt:
                excerpt=clean[:cap].rstrip("，；：、 ")
            excerpt=excerpt.rstrip('。；，')
            if conversational:
                utterances.append(f"{transitions[index]}{excerpt}；")
            else:
                utterances.append(f"第{number}步，{excerpt}。")
        if conversational:
            actions="建议这样处理："+''.join(utterances).rstrip('。；，')+"。"
            summary="".join(([intro] if intro else [])+[actions]+([tail] if tail else []))
        else:
            summary="".join(([intro] if intro else [])+utterances+([tail] if tail else []))
        if len(summary)<=limit:return summary,True
    parts=_clauses(normalized.replace("；","；\n"))
    # R484: choose source facts from the opening, middle and ending,
    # not only the first clauses. Keep facts exact when Flash is unavailable.
    def short_clause(part,cap):
        if len(part)<=cap:return part
        choices=[part.rfind(sign,max(20,cap//2),cap)
                 for sign in ("，","；","。","！","？")]
        cut=max(choices)
        return part[:cut+1] if cut>=max(20,cap//2) else ""
    chosen=[];seen=set();space=limit
    if len(parts)>=5:
        mid=len(parts)//2
        quota=max(42,min(95,limit//3-10))
        for idx in (0,mid,len(parts)-1):
            snippet=short_clause(parts[idx],quota)
            if snippet and snippet not in seen and len(snippet)<=space:
                chosen.append(snippet);seen.add(snippet);space-=len(snippet)
    key_terms=("结论","因此","所以","关键","注意","风险","建议","最后","总之","原因")
    ordered=[p for p in parts if any(w in p for w in key_terms)]+parts
    for part in ordered:
        if part in seen:continue
        snippet=short_clause(part,space)
        if not snippet or snippet in seen:continue
        chosen.append(snippet);seen.add(snippet);space-=len(snippet)
        if space<16:break
    # Selection priority must not become narration order.
    chosen.sort(key=normalized.find)
    if not chosen:
        # Last resort: paragraph punctuation boundary, no artificial
        # "complete text is on Mac" sentence or fictitious full answer.
        segments=[s.strip() for s in re.split(r"[，、；]",normalized) if s.strip()]
        chosen=[]
        for part in segments:
            if len(part)+1>space:continue
            chosen.append(part+"，");space-=len(part)+1
            if space<12:break
    if not chosen:
        return normalized[:limit].rstrip("，；")+"。",True
    out="".join(chosen).rstrip("，；")
    if not out.endswith(("。","！","？")):out+="。"
    return out[:limit],True
