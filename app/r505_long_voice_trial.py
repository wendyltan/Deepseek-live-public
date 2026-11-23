"""R505: scoped user-enabled R503 0.6B long-answer voice trial.

Only an authenticated Wi-Fi backend decides whether a verified official DSH
long answer may use the 8907 localhost research voice. The live D10 remains
the default for every short answer, all failures and any absent config.
No model/port is started by importing this module.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME=Path.home()
ROOT=HOME/"Library/Application Support/Deepseek-live/companion-native"
CONFIG=ROOT/"voice-trial-r505.json"
CANDIDATE="http://127.0.0.1:8907"
BASELINE="http://127.0.0.1:8906"
EXPECTED_SHA="33bce3a2c5078f1ae71c117783412b16de7886ed11f580e8d4ac9edaf93556fc"
MIN_LONG_CHARS=160

def enabled(*, config:Path=CONFIG) -> bool:
    path=Path(config)
    try:
        if path.is_symlink() or path.parent.is_symlink():return False
        folder=path.parent.stat()
        f=path.stat()
        if (folder.st_uid!=os.getuid() or folder.st_mode&0o077 or
                f.st_uid!=os.getuid() or f.st_mode&0o077 or f.st_size<10 or f.st_size>1024):
            return False
        data=json.loads(path.read_text())
        return (type(data)==dict and data.get("schema")==1 and
                data.get("mode")=="r505-long-only" and data.get("enabled") is True)
    except (OSError,ValueError,TypeError,AttributeError):
        return False

def candidate_ready(*, opener=None) -> bool:
    opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req=urllib.request.Request(CANDIDATE+"/health",method="GET")
    try:
        with opener.open(req,timeout=2) as resp:
            if resp.status!=200:return False
            data=resp.read(2048)
        row=json.loads(data)
        return (
            row.get("ready") is True and row.get("error") is None and
            row.get("busy") is False and
            row.get("candidate")=="R505-0p6b-long-only" and
            row.get("reference_sha256")==EXPECTED_SHA and
            row.get("stream_contract")=="h11-ndjson")
    except (OSError,urllib.error.URLError,ValueError,TypeError):
        return False

def select(reply_origin:str, spoken:str, *, source_chars:int=0,
           summarized_long:bool=False,
           config:Path=CONFIG,opener=None) -> str:
    # A verified long DSH reply can be reduced to <160 characters by the
    # user's optional summarizer. The candidate remains a "long answer"
    # trial in that case, but the transcript and DSH reply must be genuine.
    if (reply_origin!="official_dsh_verified" or not isinstance(spoken,str)
        or not 1<=len(spoken)<=8000 or
        type(source_chars) is not int or source_chars<0 or source_chars>12000 or
        not (len(spoken)>=MIN_LONG_CHARS or
             (source_chars>320 and len(spoken)>=80) or
             (summarized_long is True and
              source_chars>=MIN_LONG_CHARS and len(spoken)>=65))):
        return BASELINE
    # R503 human acceptance was for Chinese. Do not silently route a
    # multilingual/code-heavy answer to a Chinese-forced clone model.
    han=sum("\u4e00"<=c<="\u9fff" for c in spoken)
    if han<30 or han*4<len(spoken):
        return BASELINE
    if not enabled(config=config):return BASELINE
    return CANDIDATE if candidate_ready(opener=opener) else BASELINE

def mode_of(endpoint:str) -> str:
    return "dafeiyu-r503-qwen06-long-trial" if endpoint==CANDIDATE else "dafeiyu-qwen3-d10"
