#!/usr/bin/env python3
"""Explicit, read-back macOS service switches for the fish's two owner services.

Never use a generic switch on the shared DSH/tts service: those have other
clients. The user switches exactly the USB voice LaunchAgent or the automatic
USB/Wi-Fi owner supervisor; neither action opens USB, invokes DSH or writes
NVS/SD. launchctl disable persists the owner's intent across restarts.
"""
from __future__ import annotations
import json,os,re,stat,subprocess,sys,time
from pathlib import Path

HOME=Path.home()
UID=os.getuid()
DOMAIN=f"gui/{UID}"
BASE=HOME/"Library/Application Support/Deepseek-live"
LABELS={"usb":"local.deepseeklive.r29.voice",
        "transport":"local.deepseeklive.r319.transport-supervisor"}
PLISTS={key:HOME/"Library/LaunchAgents"/f"{label}.plist" for key,label in LABELS.items()}
SAFE_PHASES={"idle","standby"}
ACTIVE_PHASES={"listening","recording","transcribing","thinking","tool_pending",
               "approval_pending","voice_generating","speaking","processing",
               "audio_ready","capturing"}


def invoke(*args,timeout=8):
    try:
        return subprocess.run(["/bin/launchctl",*args],capture_output=True,
                              text=True,timeout=timeout,check=False)
    except (OSError,subprocess.TimeoutExpired):
        return None


def read_private(relative,limit=32768):
    p=BASE/relative
    try:
        info=p.lstat()
        if(not stat.S_ISREG(info.st_mode) or info.st_uid!=UID or
           (stat.S_IMODE(info.st_mode)&0o077)!=0 or
           not 0<info.st_size<=limit):return None
        a=json.loads(p.read_text())
        return a if isinstance(a,dict) else None
    except (OSError,ValueError):
        return None


def disabled_flags():
    p=invoke("print-disabled",DOMAIN)
    if p is None or p.returncode:return None
    result={}
    for key,label in LABELS.items():
        found=re.search(r'(?m)^\s*"'+re.escape(label)+r'"\s*=>\s*(enabled|disabled)\s*$',p.stdout)
        result[key]=found.group(1)=="disabled" if found else False
    return result


def launch_state(key):
    label=LABELS[key]
    p=invoke("print",f"{DOMAIN}/{label}")
    if p is None:return None
    if p.returncode:return {"loaded":False,"running":False}
    return {
        "loaded":True,
        "running":bool(re.search(r'(?m)^\s*pid = [1-9][0-9]*\s*$',p.stdout)),
    }


def state():
    flags=disabled_flags()
    if flags is None:return {"schema":1,"ok":False,"reason":"launchctl_read_failed"}
    services={}
    for key in LABELS:
        found=launch_state(key)
        if found is None:return {"schema":1,"ok":False,"reason":"launchctl_read_failed"}
        services[key]={"enabled":not flags[key],
                       "loaded":found["loaded"],"running":found["running"]}
    return {"schema":1,"ok":True,"services":services}


def activity_gate(key,target):
    wifi=read_private("lan-pairing/lan-gateway-status.json",4096)
    # An unknown or old wireless receipt cannot justify stopping another
    # service when a LAN process might own an unfinished official DSH turn.
    if wifi is None:
        raise RuntimeError("wireless_status_unavailable")
    stamp=wifi.get("updated_at_unix")
    if type(stamp) not in (float,int) or not -5<=time.time()-stamp<=15:
        if wifi.get("active_devices") or wifi.get("pending_dsh_jobs"):
            raise RuntimeError("wireless_status_stale")
        # If the gateway is absent and the receipt is old, check no WSS
        # owner remains; never infer safety from a historical zero.
        p=subprocess.run(["/usr/sbin/lsof","-nP","-iTCP:8877","-sTCP:LISTEN"],
                         capture_output=True,timeout=5)
        if p.returncode!=1:raise RuntimeError("wireless_owner_unverified")
    elif wifi.get("active_devices")!=0 or wifi.get("pending_dsh_jobs")!=0:
        raise RuntimeError("wireless_conversation_active")
    if not target:
        usb=read_private("companion-native/status.json",32768)
        if usb is None:raise RuntimeError("usb_state_unavailable")
        age=time.time()-usb.get("updated_at_unix",0)
        if not -5<=age<=12 or usb.get("phase") not in SAFE_PHASES or usb.get("current_task_id"):
            raise RuntimeError("voice_not_idle")
        if usb.get("session_verified") is not True:
            raise RuntimeError("voice_not_verified")
    if key=="transport" and not target:
        # Supervisor owns the LAN child. It may be turned off only while no
        # WSS listener can be left orphaned by a supervisor bootout.
        p=subprocess.run(["/usr/sbin/lsof","-nP","-iTCP:8877","-sTCP:LISTEN"],
                         capture_output=True,timeout=5)
        if p.returncode!=1:raise RuntimeError("wifi_gateway_running")
    return True


def reload_supervisor_after_usb_off(transport):
    """Apply the new R459 no-rebootstrap rule only after an explicit user stop.

    R319 stays untouched during GUI installation and ordinary status polls.
    A user-requested USB shutdown may reload the supervisor only when no WSS
    listener remains. If a listener unexpectedly appears, leave it untouched.
    """
    if not (transport and transport.get("running")):
        return True
    proc=subprocess.run(["/usr/sbin/lsof","-nP","-iTCP:8877",
                         "-sTCP:LISTEN"],capture_output=True,timeout=5)
    if proc.returncode!=1:
        return False
    r=invoke("kickstart","-k",f"{DOMAIN}/{LABELS['transport']}",timeout=15)
    return r is not None and r.returncode==0


def change(key,target):
    if key not in LABELS:raise RuntimeError("unsupported_service")
    now=state()
    if not now.get("ok"):raise RuntimeError("status_read_failed")
    if now["services"][key]["enabled"]==target:
        return {"schema":1,"ok":True,"changed":False,
                "reason":"already_in_requested_mode","services":now["services"]}
    agent=PLISTS[key]
    if not agent.is_file() or agent.is_symlink():
        raise RuntimeError("missing_or_untrusted_launchagent")
    if agent.stat().st_uid!=UID:raise RuntimeError("launchagent_owner_mismatch")
    activity_gate(key,target)
    label=f"{DOMAIN}/{LABELS[key]}"
    command="enable" if target else "disable"
    r=invoke(command,label)
    if r is None or r.returncode:
        raise RuntimeError("launchctl_"+command+"_failed")
    try:
        if target:
            if not now["services"][key]["loaded"]:
                r=invoke("bootstrap",DOMAIN,str(agent),timeout=12)
                if r is None or r.returncode:
                    # The live transport supervisor may win the same bootstrap
                    # race. An already-loaded real agent is a valid outcome.
                    current=launch_state(key)
                    if current is None or not current["loaded"]:
                        raise RuntimeError("bootstrap_failed")
        else:
            if now["services"][key]["loaded"]:
                r=invoke("bootout",label,timeout=12)
                if r is None or r.returncode:
                    raise RuntimeError("bootout_failed")
        after=state()
        if not after.get("ok") or after["services"][key]["enabled"]!=target:
            raise RuntimeError("readback_mismatch")
        if not target and after["services"][key]["loaded"]:
            raise RuntimeError("service_still_loaded")
        reason="launchctl_verified"
        if key=="usb" and not target:
            if not reload_supervisor_after_usb_off(after["services"]["transport"]):
                # Intent was still correctly committed: the USB service is
                # disabled and unloaded. Do not lie or re-enable it.
                reason="launchctl_verified_supervisor_reload_pending"
        return {"schema":1,"ok":True,"changed":True,
                "reason":reason,"services":after["services"]}
    except Exception:
        # Restore the launchd intent on a partial failure. Never silently
        # bootstrap/restart an active service during rollback.
        invoke("disable" if target else "enable",label)
        raise


def main(args):
    if len(args)==1 and args[0]=="status":
        print(json.dumps(state(),ensure_ascii=False))
        return
    if len(args)==2 and args[0] in LABELS and args[1] in ("on","off"):
        try:
            result=change(args[0],args[1]=="on")
            print(json.dumps(result,ensure_ascii=False))
        except (RuntimeError,ValueError,TypeError,OSError,subprocess.TimeoutExpired) as exc:
            current=state()
            print(json.dumps({"schema":1,"ok":False,"reason":str(exc)[:90],
                              "services":current.get("services",{})},
                             ensure_ascii=False))
        return
    print(json.dumps({"schema":1,"ok":False,"reason":"invalid_request"}))


if __name__=="__main__":
    main(sys.argv[1:])
