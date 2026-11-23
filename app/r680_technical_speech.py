"""R680: pronounce verified DSH dates, file sizes and measured quantities.

Speech-only text transformation, never write back into the model's final
answer. Explicit date/time spans outrank generic numeric ranges. Exact values
remain visible in Mac history; lossy file-size speech is labelled 'approximately'.
"""
from __future__ import annotations
import re
from app.r458_voice_text import _zh_integer,_spoken_number

_DIGITS="零一二三四五六七八九"
_NUM=r"(?<![A-Za-z0-9_.-])(\d{1,7}(?:\.\d{1,3})?)(?![A-Za-z0-9_.-])"
_DATE=re.compile(r"(?<![0-9./-])((?:19|20)\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?(?![\d/.-])")
_SIZE=re.compile(r"(?<![\d,.])(\d{1,3}(?:,\d{3})+|\d{4,9})\s*字节(?:\s*[（(]\s*约\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB)\s*[)）])?",re.I)
_G=r"(?<![A-Za-z0-9_])([0-9]{1,5}(?:\.[0-9]{1,2})?)\s*g(?![A-Za-z])"

def _yr(text):
    return "".join(_DIGITS[int(c)] for c in text)

def _number(token):
    if token.startswith("0") and len(token)>1 and "." not in token:
        return "".join(_DIGITS[int(c)] for c in token)
    return _spoken_number(token)

def normalize_technical_speech(text:str)->tuple[str,dict[str,int]]:
    if not isinstance(text,str) or not 1<=len(text)<=8000:
        raise ValueError("r680_invalid_voice_text")
    tally={"datetime":0,"bytes":0,"units":0,"ranges":0}
    def date(match):
        year,month,day,hour,minute,seconds=match.groups()
        mm=int(month);dd=int(day)
        if not 1<=mm<=12 or not 1<=dd<=31:return match.group(0)
        if hour and (int(hour)>23 or int(minute)>59 or
                     (seconds and int(seconds)>59)):
            return match.group(0)
        tally["datetime"]+=1
        result=(f"{_yr(year)}年{_zh_integer(mm)}月{_zh_integer(dd)}日")
        if hour is not None:
            result+=f"，{_zh_integer(int(hour))}点{_zh_integer(int(minute))}分"
            if seconds is not None:
                result+=f"{_zh_integer(int(seconds))}秒"
        return result
    text=_DATE.sub(date,text)
    def size(match):
        raw,approx,unit=match.groups()
        try:n=int(raw.replace(",",""))
        except ValueError:return match.group(0)
        if n<1024 or n>2_000_000_000:return match.group(0)
        tally["bytes"]+=1
        if approx and unit:
            label={"KB":"千字节","MB":"兆字节","GB":"吉字节"}[unit.upper()]
            return "约"+_number(approx)+label
        # Decimal kilobytes; a deliberately *approximate* oral version
        # leaves the exact byte count available in the Mac record.
        return "约"+_number(str(round(n/1000,1)))+"千字节"
    text=_SIZE.sub(size,text)
    # Spoken quantity ranges must be transformed as a WHOLE; otherwise
    # "30–40g" incorrectly becomes "30–四十克".
    def unit_range(match):
        first,second,unit=match.groups()
        tally["ranges"]+=1
        if re.fullmatch(r"g\s*/\s*s",unit,re.I):
            return "每秒"+_number(first)+"到"+_number(second)+"克"
        aliases={"g":"克","kg":"千克","mm":"毫米","bar":"巴","℃":"摄氏度"}
        suffix=aliases.get(unit.lower(),unit)
        return _number(first)+"到"+_number(second)+suffix
    text=re.sub(
        r"(?<![A-Za-z0-9_.-])([0-9]{1,5}(?:\.[0-9]{1,2})?)"
        r"\s*(?:到|[–—~～-])\s*([0-9]{1,5}(?:\.[0-9]{1,2})?)"
        r"\s*(g\s*/\s*s|kg|mm|bar|g|克|℃|秒|分钟|小时|天)(?![A-Za-z])",
        unit_range,text,flags=re.I)
    # common duration span in tutorials, distinct from 22:16 wall clock
    # already normalized in _DATE above.
    def duration(match):
        a,b,c,d=map(int,match.groups())
        if max(a,c)>59 or max(b,d)>59:return match.group(0)
        tally["ranges"]+=1
        def t(m,s):
            if m==0:return _zh_integer(s)+"秒"
            return _zh_integer(m)+"分"+(
                _zh_integer(s)+"秒" if s else "钟")
        return t(a,b)+"到"+t(c,d)
    text=re.sub(r"(?<!\d)(\d{1,2}):(\d{2})\s*[～~—–-]\s*(\d{1,2}):(\d{2})(?!\d)",
                duration,text)
    text=re.sub(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)",
                lambda m:(
                    _zh_integer(int(m[1]))+"分"+
                    (_zh_integer(int(m[2]))+"秒" if int(m[2]) else "钟"))
                if int(m[1])<=59 and int(m[2])<=59 else m[0],text)
    def per_second(m):
        tally["units"]+=1
        return "每秒"+_number(m[1])+"克"
    text=re.sub(r"(?<![0-9])([0-9]{1,4})\s*[–—~-]\s*([0-9]{1,4})\s*g/s",
                lambda m:"每秒"+_number(m[1])+"到"+_number(m[2])+"克",
                text,flags=re.I)
    text=re.sub(_G+r"\s*/\s*s\b",per_second,text,flags=re.I)
    def grams(m):
        tally["units"]+=1
        return _number(m[1])+"克"
    text=re.sub(_G,grams,text,flags=re.I)
    def temperature(m):
        tally["units"]+=1
        return _number(m[1])+"摄氏度"
    text=re.sub(r"(?<!\d)(\d{1,3})(?:\s*)℃",temperature,text)
    # Additional established engineering units used in verified procedural
    # source rows. Do not change file extensions or arbitrary identifiers.
    units={"kg":"千克","mm":"毫米","bar":"巴"}
    text=re.sub(
        r"(?<![0-9A-Za-z_.\/-])([0-9]{1,5}(?:\.[0-9]{1,2})?)"
        r"\s*(kg|mm|bar)(?![A-Za-z])",
        lambda m:_number(m[1])+units[m[2].lower()],text,flags=re.I)
    text=text.replace("±","正负")
    # Units that already have Chinese suffixes can be safely read as
    # Chinese cardinals without modifying version numbers or file names.
    text=re.sub(r"(?<![\dA-Za-z._/-])(\d{1,5})\s*(秒|分钟|小时|天|下|克|千克|毫米|摄氏度)",
                lambda m:_number(m[1])+m[2],text)
    # Remove the whitespace left by literal unit replacement ("称 15g 豆").
    text=re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])","",text)
    return text,tally
