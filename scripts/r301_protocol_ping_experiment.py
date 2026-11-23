"""R301: expiring server-origin Ping experiment for authenticated LAN gateway.

An invalid, altered, expired, symlinked or world-readable flag fails closed.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import time
from pathlib import Path

FLAG=(Path.home()/"Library/Application Support/Deepseek-live/lan-pairing"
      /"r301_protocol_ping_experiment.json")
MAX_TTL_SECONDS=12*3600
EXPECTED={"schema":1,"experiment":"disable_server_origin_ws_ping",
          "device_baseline":"r298_compatible_wifi_protocol"}


def active(path=FLAG,now=None)->bool:
    if now is None:now=time.time()
    try:
        st=path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid():
            return False
        if stat.S_IMODE(st.st_mode)!=0o600 or st.st_size>400:
            return False
        row=json.loads(path.read_text())
        if not isinstance(row,dict) or set(row)!=set(EXPECTED)|{"expires_unix"}:
            return False
        if any(row.get(k)!=v for k,v in EXPECTED.items()):
            return False
        expiry=row["expires_unix"]
        return type(expiry) is int and now<expiry<=now+MAX_TTL_SECONDS
    except (OSError,ValueError,TypeError,KeyError):
        return False


def arm(path=FLAG,now=None,seconds=MAX_TTL_SECONDS-60):
    if now is None:now=time.time()
    if not isinstance(seconds,int) or not 0<seconds<MAX_TTL_SECONDS:
        raise ValueError("invalid_experiment_ttl")
    if path.is_symlink():raise ValueError("refuse_symlink")
    path.parent.mkdir(parents=True,exist_ok=True)
    row=dict(EXPECTED,expires_unix=int(now)+seconds)
    temp=path.with_suffix(".tmp")
    fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"w") as f:
            json.dump(row,f,separators=(",",":"))
            f.write("\n")
        os.replace(temp,path)
        os.chmod(path,0o600)
    finally:
        if temp.exists():temp.unlink()
    if not active(path,now):raise ValueError("flag_failed_validation")
    return row["expires_unix"]


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--enabled",action="store_true")
    mode.add_argument("--arm",action="store_true")
    mode.add_argument("--clear",action="store_true")
    args=ap.parse_args()
    if args.enabled:print("1" if active() else "0")
    elif args.arm:print("R301_EXPERIMENT_EXPIRES_UNIX",arm())
    else:
        if FLAG.exists() and not FLAG.is_symlink():FLAG.unlink()
        print("R301_EXPERIMENT_DISABLED")
