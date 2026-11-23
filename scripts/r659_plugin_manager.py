#!/usr/bin/env python3
"""R659 companion-only DSH plugin inventory, curated catalog and change plans.

Read-only. Never loads plugin code, installs packages, edits a live Profile,
restarts DSH or interacts with other DSH instances, a model, CUA, ESP32 or Pinky.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
ALLOWED_BASE=Path.home()/"Library/Application Support/Deepseek-live"
def _default_home()->Path:
    env=os.environ.get("DAFEIYU_HOME","").strip()
    if env:return Path(env).expanduser()
    for name in ("dsh-home-production-r645","my-companion","companion-public"):
        cand=ALLOWED_BASE/name
        if (cand/"profiles/web/package.json").is_file():return cand
    return ALLOWED_BASE/"my-companion"
DEFAULT_HOME=_default_home()
CATALOG=PROJECT/"config/plugin-catalog.json"
CORE_BUNDLES=frozenset({
    "@deepseek-ai/dsh-base",
    "@deepseek-ai/dsh-web-app",
    "dsh-live-bridge",
})
CORE_TOOL_IDS=frozenset({"mcp-pinky-dafeiyu","computer-use",
                         "cua-macos","agent-default-model",
                         "preset-deepseek-live-web"})
ALLOWED_ACTIONS=frozenset({"enable","disable","install","remove","update"})

def need(value,reason):
    if not value:
        raise ValueError("PLUGIN_"+reason)

def home_path(value):
    raw=Path(value).expanduser()
    need(not raw.is_symlink(),"HOME_SYMLINK")
    home=raw.resolve(strict=False)
    base=ALLOWED_BASE.resolve()
    need(home!=base and home.is_relative_to(base) and
         "runtime" not in home.parts and ".dsh" not in home.parts,
         "NOT_IN_COMPANION_APPLICATION_SUPPORT")
    st=home.lstat()
    need(stat.S_ISDIR(st.st_mode) and st.st_uid==os.getuid() and
         (st.st_mode&0o777)==0o700,"PRIVATE_HOME_REQUIRED")
    return home

def read_profile(home):
    directory=home/"profiles/web"
    need(directory.is_dir() and not directory.is_symlink(),"WEB_PROFILE_REQUIRED")
    manifest=directory/"package.json"
    need(manifest.is_file() and not manifest.is_symlink(),"PACKAGE_MANIFEST_UNTRUSTED")
    need(manifest.stat().st_uid==os.getuid() and manifest.stat().st_size<65536,
         "PACKAGE_MANIFEST_NOT_OWNER")
    raw=manifest.read_bytes()
    data=json.loads(raw)
    bundles=data.get("dsh",{}).get("profile",{}).get("bundles")
    need(isinstance(bundles,list) and bundles[:2]==[
        "@deepseek-ai/dsh-base","@deepseek-ai/dsh-web-app"
    ] and "dsh-live-bridge" in bundles,"NOT_COMPANION_PROFILE")
    need(isinstance(data.get("dependencies"),dict) and len(bundles)<=80,
         "INVALID_DEPENDENCY_TABLE")
    return data,raw

def catalog_data():
    j=json.loads(CATALOG.read_text())
    need(j.get("schema")==1 and type(j.get("items")) is list,"INVALID_CATALOG")
    return j["items"]

def package_version(home,name,expected):
    directory=home/"profiles/web/node_modules"
    package=directory/name/"package.json"
    try:
        if not package.is_file():return None
        real=package.resolve(strict=True)
        # Local live-bridge can point to checked-out source and is accepted
        # only because it matches a declared dependency. Never import it.
        need(real.is_relative_to(home.resolve()) or real.is_relative_to(PROJECT),
             "PACKAGE_LINK_OUTSIDE_COMPANION")
        manifest=json.loads(real.read_text())
        need(manifest.get("name")==name,"PACKAGE_NAME_MISMATCH")
        return str(manifest.get("version") or "")[:40]
    except (OSError,ValueError,json.JSONDecodeError):
        return None


def bundle_available(home,name):
    """Read-only check: a profile dependency is a real DSH bundle, not a library.

    The bundle patch must belong to the installed package. Runtime components
    without a DSH bundle are never offered an Enable/Uninstall card.
    """
    package=home/"profiles/web/node_modules"/name/"package.json"
    try:
        real=package.resolve(strict=True)
        need(real.is_relative_to(home.resolve()) or real.is_relative_to(PROJECT),
             "PACKAGE_LINK_OUTSIDE_COMPANION")
        metadata=json.loads(real.read_text())
        if metadata.get("name")!=name:return False
        patch=metadata.get("dsh",{}).get("bundle",{}).get("patch")
        if not isinstance(patch,str) or not patch or Path(patch).is_absolute():
            return False
        if any(x==".." for x in Path(patch).parts):return False
        target=(real.parent/patch).resolve(strict=True)
        return (target.is_relative_to(real.parent) and target.is_file()
                and not (real.parent/patch).is_symlink())
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError):
        return False

def status(home):
    config,raw=read_profile(home)
    bundles=config["dsh"]["profile"]["bundles"]
    declared=config["dependencies"]
    patch=(home/"profiles/web/cordis.patch.yml").read_text()
    rows=[]
    for name,spec in sorted(declared.items()):
        ver=package_version(home,name,spec)
        rows.append({"name":name,"requested_spec":spec if not str(spec).startswith("link:") else "local-link",
                     "version":ver,"installed":ver is not None,
                     "is_bundle":ver is not None and bundle_available(home,name),
                     "enabled_bundle":name in bundles,
                     "protected":name in CORE_BUNDLES})
    return {"schema":1,"scope":"dafeiyu-companion-only",
            "host_port":3080,
            "bundle_count":len(bundles),
            "bundles":[{"name":n,"protected":n in CORE_BUNDLES} for n in bundles],
            "declared_package_count":len(declared),
            "packages":rows,
            "essential_tools":[{"name":k,"declared":(
                f"id: {k}" in patch),"protected":True} for k in sorted(CORE_TOOL_IDS)],
            "manifest_sha256":hashlib.sha256(raw).hexdigest(),
            "installations_modified":0}

def marketplace(home,query="",online=False):
    need(len(query)<=75,"QUERY_TOO_LONG")
    q=query.casefold().strip()
    entries=[row for row in catalog_data()
             if q in (row["title"]+" "+row["id"]+" "+row["scope"]).casefold()]
    declared=read_profile(home)[0]["dependencies"]
    results=[]
    for item in entries[:15]:
        row={**item,"declared_locally":item["id"] in declared,
             "published_version_verified_online":False}
        if online and item["source"]=="npm":
            # Network requests only on an explicit UI action. Never executes
            # registry package code, custom URLs, postinstall or new plugins.
            pnpm=shutil.which("pnpm")
            if pnpm:
                try:
                    p=subprocess.run([pnpm,"view",item["id"]+"@"+item["version"],
                                      "version","--fetch-retries=0","--fetch-timeout=6000"],
                                     capture_output=True,text=True,timeout=9)
                    row["published_version_verified_online"]=(
                        p.returncode==0 and p.stdout.strip()==item["version"])
                except (OSError,subprocess.TimeoutExpired):
                    pass
        results.append(row)
    return {"schema":1,"scope":"companion-only","catalog_type":"curated_not_entire_npm",
            "query":query,"count":len(results),"items":results,
            "online_checked":bool(online),"packages_installed":0,
            "needs_human_install_approval":True}

def proposal(home,action,package):
    need(action in ALLOWED_ACTIONS,"UNKNOWN_ACTION")
    need(bool(re.fullmatch(r"(?:@[-a-z0-9]+/)?[-a-z0-9.]+",package)),
         "INVALID_PACKAGE")
    need(package not in CORE_BUNDLES and package not in CORE_TOOL_IDS,
         "PROTECTED_CORE")
    config,raw=read_profile(home)
    requested=config["dependencies"]
    enabled=config["dsh"]["profile"]["bundles"]
    known=next((r for r in catalog_data() if r["id"]==package),None)
    installed=package in requested
    # R676: the native DSH marketplace can install a package that is not in
    # our small curated discovery catalog. Permit *only* enable/disable of an
    # exact, already declared and physically installed profile package.
    # Install/update/remove retain the curated restriction; no shell code
    # or arbitrary npm source is executed by this read-only plan.
    if known is None and action in ("enable","disable") and installed:
        ver=package_version(home,package,requested[package])
        meta_file=home/"profiles/web/node_modules"/package/"package.json"
        need(ver is not None and meta_file.is_file(),"LOCAL_PLUGIN_NOT_RESOLVED")
        meta=json.loads(meta_file.read_text())
        patch=meta.get("dsh",{}).get("bundle",{}).get("patch")
        need(isinstance(patch,str) and
             (meta_file.parent/patch).is_file() and
             not (meta_file.parent/patch).is_symlink(),
             "INSTALLED_PACKAGE_NOT_DSH_BUNDLE")
        need(isinstance(requested[package],str) and
             len(requested[package])<90 and
             not requested[package].startswith(("link:","file:")),
             "MARKET_INSTALLED_PACKAGE_SPEC_UNTRUSTED")
        known={"id":package,"version":ver,"source":"installed_local"}
    need(known is not None,"NOT_IN_REVIEWED_CATALOG")
    if action=="enable":
        need(installed and package not in enabled,"ENABLE_REQUIRES_INSTALLED_INACTIVE")
        need(package_version(home,package,requested[package]) is not None,
             "LOCAL_PLUGIN_NOT_RESOLVED")
    if action=="disable":
        need(package in enabled,"DISABLE_REQUIRES_ENABLED")
    if action=="install":
        need(not installed and known["source"]=="npm","INSTALL_NEEDS_REGISTRY_PACKAGE")
    if action=="remove":
        need(installed and package not in enabled,
             "REMOVE_REQUIRES_ALREADY_DISABLED")
    if action=="update":
        need(installed and known["source"]=="npm","UPDATE_NEEDS_REGISTRY_PACKAGE")
    fingerprint=hashlib.sha256(raw+action.encode()+package.encode()).hexdigest()
    return {"schema":1,"scope":"companion-only",
            "action":action,"name":package,"catalog_source":known["source"],
            "requested_version":known["version"],
            "manifest_sha256":hashlib.sha256(raw).hexdigest(),
            "plan_sha256":fingerprint,
            "requires_user_approval":True,
            "requires_exact_version_check":True,
            "requires_idle_host":True,
            "requires_snapshot_and_verified_rollback":True,
            "requires_dsh_restart":action in ("enable","disable","install","remove","update"),
            "will_apply_now":False,
            "other_profile_affected":False,
            "phone_or_computer_tools_executed":0,
            "paid_model_requests":0}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("status","catalog","discover","plan"))
    parser.add_argument("--dsh-home",default=str(DEFAULT_HOME))
    parser.add_argument("--query",default="")
    parser.add_argument("--online",action="store_true")
    parser.add_argument("--action",choices=sorted(ALLOWED_ACTIONS))
    parser.add_argument("--package")
    args=parser.parse_args()
    try:
        home=home_path(args.dsh_home)
        if args.command=="status":
            result=status(home)
        elif args.command=="catalog":
            result=marketplace(home,args.query,args.online)
        elif args.command=="discover":
            from scripts.r668_live_market import discover
            result=discover(home,args.query)
        else:
            need(bool(args.action and args.package),"PLAN_REQUIRES_ACTION_AND_PACKAGE")
            result=proposal(home,args.action,args.package)
    except (OSError,ValueError,json.JSONDecodeError) as e:
        parser.exit(2,f"PLUGIN_MANAGER_ERROR: {type(e).__name__}: {e}\n")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
