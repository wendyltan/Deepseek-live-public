"""Read-only, bounded weather nowcast for an explicitly configured location.

This is not a DSH tool and does not bypass native web_fetch policy.
It only responds for one validated location; other cities stay in DSH.
Open-Meteo model forecast, CC BY 4.0 attribution in spoken result.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
import json
import math
import re

LOCATION=os.environ.get("DAFEIYU_WEATHER_LOCATION","").strip()
LATITUDE=float(os.environ.get("DAFEIYU_WEATHER_LATITUDE","0"))
LONGITUDE=float(os.environ.get("DAFEIYU_WEATHER_LONGITUDE","0"))
TIMEZONE=ZoneInfo(os.environ.get("DAFEIYU_WEATHER_TIMEZONE","Asia/Shanghai"))
WEATHER_API="https://api.open-meteo.com/v1/forecast"
CONDITION={
    0:"晴",1:"大部晴朗",2:"多云间晴",3:"阴",
    45:"有雾",48:"有雾凇",51:"小毛毛雨",53:"毛毛雨",55:"较强毛毛雨",
    56:"冻毛毛雨",57:"强冻毛毛雨",
    61:"小雨",63:"中雨",65:"大雨",66:"冻雨",67:"较强冻雨",
    71:"小雪",73:"中雪",75:"大雪",77:"雪粒",
    80:"阵雨",81:"较强阵雨",82:"强阵雨",
    85:"阵雪",86:"较强阵雪",95:"雷阵雨",96:"雷暴伴冰雹",99:"强雷暴伴冰雹",
}
class WeatherUnavailable(RuntimeError):pass

def accepts(transcript):
    if not isinstance(transcript,str) or len(transcript)>180:return False
    if not re.search(r"天气|气温|温度|下雨|降水",transcript):return False
    if not LOCATION or not (LOCATION in transcript or any(a in transcript for a in os.environ.get("DAFEIYU_WEATHER_ALIASES","").split(",") if a)):return False
    # Do not send a request if user seems to ask for a remote day/range.
    if re.search(r"明天|后天|下周|下个月|去年|历史|去年今天",transcript):return False
    return True

def _number(value,lo,hi):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise WeatherUnavailable("weather_numeric_invalid")
    if not lo<=value<=hi:raise WeatherUnavailable("weather_numeric_out_of_range")
    return value

def _parse(data,now):
    if not isinstance(data,dict) or data.get("timezone")!=TIMEZONE.key:
        raise WeatherUnavailable("weather_timezone_unverified")
    current=data.get("current")
    daily=data.get("daily")
    if not isinstance(current,dict) or not isinstance(daily,dict):
        raise WeatherUnavailable("weather_missing_blocks")
    try:current_time=datetime.fromisoformat(current["time"]).replace(tzinfo=TIMEZONE)
    except (ValueError,TypeError,KeyError) as exc:raise WeatherUnavailable("weather_time_invalid") from exc
    now=now.astimezone(TIMEZONE)
    if current_time.date()!=now.date() or not timedelta(minutes=-30)<=now-current_time<=timedelta(hours=3):
        raise WeatherUnavailable("weather_time_stale")
    today=daily.get("time")
    if not isinstance(today,list) or not today or today[0]!=str(now.date()):
        raise WeatherUnavailable("weather_daily_date_mismatch")
    condition=CONDITION.get(current.get("weather_code"))
    if condition is None:raise WeatherUnavailable("weather_code_unknown")
    temp=_number(current.get("temperature_2m"),-70,60)
    wind=_number(current.get("wind_speed_10m"),0,200)
    def first(key,lo,hi):
        value=daily.get(key)
        if not isinstance(value,list) or not value:
            raise WeatherUnavailable("weather_daily_missing_"+key)
        return _number(value[0],lo,hi)
    hi=first("temperature_2m_max",-70,60)
    low=first("temperature_2m_min",-70,60)
    risk=first("precipitation_probability_max",0,100)
    if low>hi:raise WeatherUnavailable("weather_range_invalid")
    return (f"根据 Open-Meteo 天气模型，{LOCATION}今天{now.month}月{now.day}日，"
            f"目前{condition}，约{temp:g}摄氏度，风速约{wind:g}公里每小时。"
            f"今天预计{low:g}至{hi:g}度，最高降水概率约{risk:g}%。"
            "这是天气预报数据，实际情况可能不同。")

def current_chikan_weather(transcript,*,opener=None,clock=None):
    if not accepts(transcript):return None
    params=urlencode({
        "latitude":LATITUDE,"longitude":LONGITUDE,
        "current":"temperature_2m,weather_code,wind_speed_10m",
        "daily":"temperature_2m_min,temperature_2m_max,precipitation_probability_max",
        "forecast_days":1,"timezone":"Asia/Shanghai"})
    request=Request(WEATHER_API+"?"+params,headers={"User-Agent":"DeepseekLive-ReadOnlyWeather/1"})
    if opener is None:opener=build_opener(ProxyHandler({}))
    try:
        with opener.open(request,timeout=7) as response:
            if getattr(response,"status",200)!=200:raise WeatherUnavailable("weather_http_status")
            raw=response.read(16385)
        if len(raw)>16384:raise WeatherUnavailable("weather_payload_too_large")
        decoded=json.loads(raw)
        return _parse(decoded,(clock or (lambda:datetime.now(TIMEZONE)))())
    except (ValueError,TypeError,UnicodeError,OSError,TimeoutError) as exc:
        raise WeatherUnavailable("weather_source_unavailable") from exc
