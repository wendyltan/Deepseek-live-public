"""Real ESP32 battery and local clock snapshot from a single USB GET receipt.
No port ownership, ambient polling, made-up battery percentages, or disk log.
"""
from __future__ import annotations
import re,time
FRAME=re.compile(
    r"^@@DFTELEMETRY1 mac=([01]) battery_valid=([01]) present=([01]) percent=(\d{1,3}) time_valid=([01]) hhmm=(\d{4})$")
def query_telemetry(port,*,clock=time.monotonic,timeout=1.5):
    try:
        cmd=b"@@DFTELEMETRY1 GET\n"
        if port.write(cmd)!=len(cmd):return None
        port.flush();end=clock()+timeout
        while clock()<end:
            text=port.readline().decode("ascii","replace").strip()
            if text.startswith(("I (","W (","E (","D (")) and "@@DFTELEMETRY1 " in text:
                text=text[text.index("@@DFTELEMETRY1 "):]
            m=FRAME.fullmatch(text)
            if not m:continue
            mac,valid,present,percent,tvalid,hhmm=map(int,m.groups())
            if percent>100 or int(hhmm//100)>=24 or int(hhmm%100)>=60:return None
            return {"device_mac_seen":bool(mac),"board_battery_valid":bool(valid and present),
                    "board_battery_percent":percent if valid and present else None,
                    "board_clock_hhmm":f"{hhmm:04d}" if tvalid else None}
    except (OSError,ValueError,AttributeError):return None
    return None
