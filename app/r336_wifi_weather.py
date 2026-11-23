"""Authorized Wi-Fi source adapter for the existing USB weather capability.

An explicitly configured city or a current *device-local* weather
request is answered by the same read-only checked Open-Meteo API as USB.
No location inference, other-city substitution, extra DSH, or fabricated data.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from app.local_weather_chikan import accepts,current_chikan_weather,WeatherUnavailable,LOCATION

WEATHER_OK = "verified_open_meteo_weather"
WEATHER_UNAVAILABLE = "local_weather_source_unavailable"
OTHER_CITY = re.compile("北京|上海|广州|深圳|茂名|海口|珠海|佛山|东莞|中山|台山")
REMOTE_DATE = re.compile("明天|后天|下周|下个月|去年|历史|未来|前天|昨天")
META_REQUEST = re.compile("介绍|科普|原理|解释|为什么|怎么形成|历史|比较|对比|趋势|写一篇|故事")
CURRENT_DEVICE = re.compile(
    "今天天气|今天的天气|现在天气|现在的天气|现在.{0,8}天气|当地天气|本地天气|"
    "这里天气|这边天气|附近天气|当前天气|今天会下雨|外面下雨|"
    "今天气温|现在气温|今天温度|现在温度")


@dataclass(frozen=True)
class VerifiedWeatherReply:
    text: str
    source: str
    available: bool


def accepts_wifi_weather(transcript: str) -> bool:
    if not isinstance(transcript,str) or not transcript.strip() or len(transcript)>180:
        return False
    if not LOCATION:return False
    if accepts(transcript):
        return True
    if (OTHER_CITY.search(transcript) or REMOTE_DATE.search(transcript)
            or META_REQUEST.search(transcript)):
        return False
    return bool(CURRENT_DEVICE.search(transcript))


def wifi_weather_reply(transcript: str) -> VerifiedWeatherReply | None:
    if not accepts_wifi_weather(transcript):
        return None
    # The user-visible response itself names the device's configured
    # location. No city silently follows a network/VPN/IP location.
    try:
        text=current_chikan_weather(LOCATION+"现在天气")
        if not text:
            raise WeatherUnavailable("weather_source_empty")
        return VerifiedWeatherReply(text,WEATHER_OK,True)
    except WeatherUnavailable:
        return VerifiedWeatherReply(
            "暂时没能核实当前配置地区的实时天气，不能给你编造温度或降雨情况。"
            "请稍后重试，或在Mac查看可信天气来源。",
            WEATHER_UNAVAILABLE,False)
