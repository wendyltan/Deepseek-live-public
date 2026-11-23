"""Read-only Mac-local calendar answers for authenticated onboard voice STT.

No model, internet, device RTC assumptions, timezone inferred from IP, or
side effects. Called after verified physical microphone/ASR, not prewake.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import re

ORIGIN="verified_mac_local_datetime"
_DAYS=("星期一","星期二","星期三","星期四","星期五","星期六","星期日")
_CLOCK=frozenset(("几点","几点钟","几点钟了","在几点钟","在几点钟了","几点了","现在几点","现在几点了","现在是什么时间","现在时间",
                  "现在的时间","现在几点钟","现在几点钟了","现在是几点","现在是几点了",
                  "现在几点啊","现在几点啦","现在几点呀","现在几点了啊",
                  "现在是几点啊","现在是几点了啊",
                  "在几点了啊","在几点了","系统时间","现在系统时间","现在的系统时间",
                  "当前系统时间","系统现在几点","系统现在几点了","现在系统几点了",
                  "现在的系统时间是多少","现在系统时间是多少","系统时间是多少",
                  "告诉我系统时间","查询系统时间","报一下系统时间","报个系统时间"))
_WEEK=frozenset(("今天星期几","今天是星期几","今天周几","今天是周几",
                 "今天礼拜几","今天是礼拜几"))
_DATE=frozenset(("今天几号","今天是几号","今天几月几号","今天几月几日",
                 "今天是几月几号","今天是几月几日","今天日期",
                 "今天是什么日期","今天是什么日子"))
_FULL=frozenset(("今天几月几号星期几","今天几月几日星期几",
                 "今天是几月几号星期几","今天是几月几日星期几",
                 "今天日期和星期几"))
_PREFIX=("你好大肥鱼","大肥鱼","请问","请告诉我","告诉我","帮我看看")
_SUFFIX=("啊","呀","呢","啦","喔","吗")


@dataclass(frozen=True)
class LocalTimeReply:
    text:str
    origin:str=ORIGIN

def local_datetime_reply(transcript:str, *, now:datetime|None=None)->LocalTimeReply|None:
    if not isinstance(transcript,str) or not 1<=len(transcript)<=90:return None
    utterance=re.sub(r"[\s，。！？，?!,.：:]+","",transcript)
    for _ in range(2):
        for prefix in _PREFIX:
            if utterance.startswith(prefix):
                utterance=utterance[len(prefix):]
                break
        else:break
    # Exact, bounded colloquial variants. Never strip words like "明天",
    # "东京", "不是" or tool-execution requests into a clock query.
    for suffix in _SUFFIX:
        if utterance.endswith(suffix) and len(utterance)>len(suffix):
            utterance=utterance[:-len(suffix)]
            break
    # Accept a repeated clock question only when both halves are clock queries.
    before, separator, after = utterance.partition("告诉我")
    if separator and after in _CLOCK:
        head = before[:-1] if before.endswith(_SUFFIX) else before
        if head in _CLOCK:
            utterance = head
    if utterance not in _CLOCK|_WEEK|_DATE|_FULL:return None
    current=now or datetime.now().astimezone()
    if current.tzinfo is None:
        # Callers may inject a naive test clock; normal runtime uses the
        # Mac system timezone with an aware datetime.
        current=current.astimezone()
    if utterance in _CLOCK:
        text=f"现在是{current.hour}点{current.minute:02d}分。"
    elif utterance in _WEEK:
        text=f"今天{_DAYS[current.weekday()]}。"
    elif utterance in _DATE:
        text=f"今天是{current.month}月{current.day}日。"
    else:
        text=f"今天是{current.month}月{current.day}日，{_DAYS[current.weekday()]}。"
    return LocalTimeReply(text)
