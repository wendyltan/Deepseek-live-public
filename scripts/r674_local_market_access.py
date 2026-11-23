#!/usr/bin/env python3
"""R674 local, exact-host official DSH Web token handoff for a native Mac view.

The startup URL is sensitive: --url returns it ONLY into CompanionPluginsView's
owner-only private temporary result file. Never log/print the URL in diagnostics.
Does not make HTTP requests, consume the one-time login token or change DSH.
"""
from __future__ import annotations
import argparse,json,os,re,stat,subprocess,sys,urllib.parse,urllib.request
from pathlib import Path
from scripts.r659_plugin_manager import home_path,DEFAULT_HOME
from scripts.r268_transport_supervisor import paired
LOG=Path.home()/"Library/Application Support/Deepseek-live/companion-native/r107-dsh-web.log"
URL=re.compile(r"(?m)^dsh web:\s+(http://127\.0\.0\.1:3080/\?token=[A-Za-z0-9_-]{32,128})\s*$")
LABEL=f"gui/{os.getuid()}/local.deepseeklive.r108.dsh-web"
HEALTH="http://127.0.0.1:3080/dsh-live-bridge/health"
def identity():
    p=subprocess.run(["/bin/launchctl","print",LABEL],capture_output=True,text=True,timeout=7)
    if p.returncode==0:
        m=re.search(r"(?m)^\s*pid = (\d+)\s*$",p.stdout)
        if m:return int(m.group(1))
    return port(3080) or 0
def port(number:int)->int|None:
    p=subprocess.run(["/usr/sbin/lsof","-nP","-t",f"-iTCP:{number}","-sTCP:LISTEN"],
                     capture_output=True,text=True,timeout=7)
    if p.returncode==1 and not p.stdout.strip():return None
    values=p.stdout.strip().splitlines()
    if p.returncode!=0 or len(values)!=1 or not values[0].isdigit():
        raise RuntimeError("R674_SOCKET_OWNER_NOT_UNIQUE")
    return int(values[0])
def health():
    try:
        op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open(HEALTH,timeout=4) as resp:
            return json.load(resp) if resp.status==200 else {}
    except (OSError,ValueError,TypeError):
        return {}
def need(ok,why):
    if not ok:raise RuntimeError("R674_"+why)
def check(*,log=LOG,profile=DEFAULT_HOME,transaction=None):
    file=log.lstat()
    need(stat.S_ISREG(file.st_mode) and not log.is_symlink()
         and file.st_uid==os.getuid() and (file.st_mode&0o077)==0
         and 0<file.st_size<2_000_000,"STARTUP_LOG_NOT_OWNER_PRIVATE")
    need(identity()==port(3080) and health().get("ok") is True,
         "DSH_HOST_UNVERIFIED")
    text=log.read_text(encoding="utf-8",errors="replace")
    rows=URL.findall(text)
    need(bool(rows),"DSH_STARTUP_TOKEN_NOT_FOUND")
    url=rows[-1]
    parsed=urllib.parse.urlsplit(url)
    need(parsed.scheme=="http" and parsed.hostname=="127.0.0.1"
         and parsed.port==3080 and parsed.path=="/"
         and not parsed.username and not parsed.password and not parsed.fragment
         and len(urllib.parse.parse_qs(parsed.query))==1
         and "token" in urllib.parse.parse_qs(parsed.query),
         "INVALID_OFFICIAL_STARTUP_URL")
    requireBundle=profile/"profiles/web/package.json"
    cfg=json.loads(requireBundle.read_text())
    need("@deepseek-ai/dsh-experimental-plugin-market-bundle" in
         cfg.get("dsh",{}).get("profile",{}).get("bundles",[]),
         "OFFICIAL_MARKET_BUNDLE_NOT_ENABLED")
    # The latest startup URL must be newer than this signed deployment, not
    # a stale token from prior dsh host restarts.
    record=(transaction if transaction is not None else
        Path.home()/"Library/Application Support/Deepseek-live/deployments/r673-dsh-market-cua-20261121/receipt.json")
    if transaction is not None or record.is_file():
        txn=json.loads(record.read_text())
        # The official installer may restart only DSH later. Keep accepting a
        # newer process's latest token, but require the original guarded market
        # rollout and the currently healthy exact loopback service.
        need(txn.get("stage")=="r673_market_and_cua_facts_live"
             and type(txn.get("new_dsh_pid")) is int and txn["new_dsh_pid"]>1
             and file.st_mtime>=txn.get("at_unix",0)-120,
             "DSH_WEB_TOKEN_NOT_CURRENT_DEPLOYMENT")
    return url
def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("command",choices=("check","url"))
    cli.add_argument("--dsh-home",default=str(DEFAULT_HOME))
    opts=cli.parse_args()
    try:
        need(home_path(opts.dsh_home)==DEFAULT_HOME.resolve(),"WRONG_DSH_HOME")
        value=check()
        if opts.command=="check":
            print(json.dumps({"ok":True,"official_market_ready":True,
                              "private_local_browser_handoff":True}))
        else: print(json.dumps({"ok":True,"url":value}))
    except (OSError,ValueError,RuntimeError,TypeError,KeyError) as e:
        cli.exit(2,"R674_AUTH_HANDOFF_FAILED: "+type(e).__name__+"\n")
if __name__=="__main__":main()
