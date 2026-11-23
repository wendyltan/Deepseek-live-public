#!/usr/bin/env python3
"""Provision one owner-controlled ESP32 over its serial interface.

The default action is a no-secret plan. --apply requires an explicit serial
device and host IPv4. This script never changes launchd or running services.
"""
from __future__ import annotations
import argparse
import base64
import ipaddress
import json
import os
import re
import stat
import time
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Deepseek-live/lan-pairing"
DEVICE="dafeiyu-esp32-s3"


def trusted(path:Path)->bool:
    try:
        s=path.lstat()
        return stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and stat.S_IMODE(s.st_mode)==0o600
    except OSError:return False


def prepare_command(root:Path,host:str,port:int=8877)->str:
    addr=str(ipaddress.IPv4Address(host))
    if not 1024<=port<=65535:raise ValueError("invalid_gateway_port")
    auth=root/"authorized-devices.json"
    cert=root/"gateway.ca.der"
    if not trusted(auth) or not trusted(cert):
        raise ValueError("pairing_identity_permissions_or_file_missing")
    record=json.loads(auth.read_text())
    token=record.get("devices",{}).get(DEVICE)
    if not isinstance(token,str) or not re.fullmatch("[a-f0-9]{64}",token):
        raise ValueError("invalid_device_token")
    raw=cert.read_bytes()
    if not 150<=len(raw)<=1536:
        raise ValueError("invalid_server_ca_der")
    command=f"@@DFLAN2 PAIR host={addr} port={port} device={DEVICE} token={token} cert={base64.b64encode(raw).decode('ascii')}"
    if len(command)>3000:raise ValueError("pairing_command_too_large")
    return command


def transact(port:str,command:str)->dict:
    if not re.fullmatch(r"/dev/cu\.[A-Za-z0-9._-]{2,160}",port):
        raise ValueError("expected_mac_serial_device_path")
    import serial  # only imported after --apply and all identity checks
    link=serial.Serial(port=None,baudrate=115200,timeout=0.2,
                       write_timeout=3,rtscts=False,dsrdtr=False)
    try:
        link.dtr=False
        link.rts=False
        link.port=port
        link.open()
        link.reset_input_buffer()
        def send(s:str,header:str,seconds:int=7)->str:
            link.write((s+"\n").encode("ascii"))
            link.flush()
            expiry=time.monotonic()+seconds
            while time.monotonic()<expiry:
                data=link.readline().decode("ascii","replace").strip()
                if data.startswith(header):
                    return data
            raise TimeoutError("device_reply_timeout")
        before=send("@@DFLAN2 STATUS","@@DFLAN2 STATUS")
        if not re.fullmatch(r"@@DFLAN2 STATUS paired=[01] wifi_ip=[01] voice_busy=[01]",before):
            raise ValueError("unexpected_firmware_status")
        if "voice_busy=1" in before:
            raise RuntimeError("board_busy")
        if "paired=0" in before:
            reply=send(command,"@@DFLAN2 ",seconds=8)
            if reply!="@@DFLAN2 PAIRED":
                raise RuntimeError("device_rejected_pairing")
        after=send("@@DFLAN2 STATUS","@@DFLAN2 STATUS")
        if "paired=1" not in after:
            raise RuntimeError("device_pairing_not_persisted")
        return {"paired":True,"before_paired":"paired=1" in before,
                "device_token_logged":False,"certificate_logged":False}
    finally:
        link.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port",help="Explicit Mac serial path, e.g. /dev/cu.usbmodemXXXX")
    p.add_argument("--host-ip",help="Mac LAN IP, must match the gateway TLS certificate")
    p.add_argument("--apply",action="store_true",
                   help="Interact with an owner-controlled ESP32 over USB")
    args=p.parse_args()
    if not args.apply:
        print(json.dumps({"mode":"plan","serial_device_required":True,
                          "host_ipv4_required":True,"will_modify_device":False,
                          "identity_dir":str(ROOT)},ensure_ascii=False))
        return
    if not args.port or not args.host_ip:
        p.error("--apply requires --port and --host-ip")
    command=prepare_command(ROOT,args.host_ip)
    result=transact(args.port,command)
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
