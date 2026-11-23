#!/usr/bin/env python3
"""Install the Dafeiyu DSH Host with pinned dependencies.

Commands: plan, prepare, deps, doctor, device-plan."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from scripts import r656_companion_profile as profile

PROJECT = Path(__file__).resolve().parents[1]
LOCK_TEMPLATE = PROJECT / "config/locks/pnpm-lock.template.yaml"
BRIDGE_LOCK = PROJECT / "config/locks/bridge-pnpm-lock.yaml"
WORKSPACE = "packages:\n  - .\n\nnodeLinker: hoisted\nautoInstallPeers: false\n\n"

class InstallFailure(RuntimeError):
    pass

def need(ok, reason):
    if not ok:
        raise InstallFailure(reason)

def private(path, directory=False):
    try:
        st=path.lstat()
        return (st.st_uid==os.getuid() and not path.is_symlink()
                and (stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode))
                and stat.S_IMODE(st.st_mode)==(0o700 if directory else 0o600))
    except OSError:
        return False

def store_once(path, data):
    need(private(path.parent, directory=True), "private_destination_parent_required")
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())

def args_home(args):
    home=Path(args.dsh_home).expanduser().resolve(strict=False)
    need(home != Path.home()/".dsh" and home != PROJECT
         and PROJECT not in home.parents and home not in PROJECT.parents
         and home.name not in (".","..","web","profiles","runtime"),
         "unsafe_home")
    return home

def manifest(home):
    path=home/"profiles/web/package.json"
    need(path.is_file() and not path.is_symlink(),"profile_manifest_missing")
    obj=json.loads(path.read_text())
    deps={**profile.PACKAGES,"dsh-live-bridge":
          "link:"+str(home/"extensions/dsh-live-bridge")}
    need(obj.get("dependencies")==deps and
         obj.get("dsh",{}).get("profile",{}).get("bundles")==list(profile.BUNDLES),
         "profile_dependency_mismatch")
    return obj

def rendered_lock(home):
    text=LOCK_TEMPLATE.read_text()
    for placeholder in ("__COMPANION_BRIDGE_SPEC__","__COMPANION_BRIDGE_VERSION__"):
        need(text.count(placeholder)==1,"lock_template_missing_placeholder")
    bridge=home/"extensions/dsh-live-bridge"
    spec="link:"+str(bridge)
    version="link:"+os.path.relpath(bridge,home/"profiles/web")
    output=text.replace("__COMPANION_BRIDGE_SPEC__",spec).replace(
        "__COMPANION_BRIDGE_VERSION__",version)
    need(output.startswith("lockfileVersion: '9.0'") and "__COMPANION_" not in output,
         "lock_template_invalid")
    return output

def plan(args):
    home=args_home(args)
    checks={
        "macos_arm64":sys.platform=="darwin" and platform.machine()=="arm64",
        "python_3_12_plus":sys.version_info>=(3,12),
        "node_available":shutil.which("node") is not None,
        "pnpm_available":shutil.which("pnpm") is not None,
        "git_available":shutil.which("git") is not None,
        "repository_complete":all((PROJECT/f).is_file() for f in profile.REQUIRED_FILES),
        "lock_template_present":LOCK_TEMPLATE.is_file() and BRIDGE_LOCK.is_file(),
        "new_home_available":not home.exists() and not home.is_symlink(),
        "parent_exists":home.parent.is_dir(),
    }
    return {"schema":1,"mode":"host-only","checks":checks,
            "can_prepare":all(checks.values()),
            "will_start_services":False,"will_flash_esp32":False,
            "will_use_other_profile":False,"will_run_phone_or_model":False,
            "requires_manual_provider_authorization":True}

def copy_private_bridge(home):
    """Make a self-contained extension copy; never install into source tree."""
    source=PROJECT/"plugins/dsh-live-bridge"
    parent=home/"extensions"
    parent.mkdir(mode=0o700,exist_ok=False)
    dest=parent/"dsh-live-bridge"
    dest.mkdir(mode=0o700,exist_ok=False)
    exclude={"node_modules",".git","__pycache__",".DS_Store"}
    count=0
    for root,dirs,files in os.walk(source,followlinks=False):
        dirs[:]=sorted(x for x in dirs if x not in exclude)
        directory=Path(root)
        relative=directory.relative_to(source)
        output=dest/relative
        if relative!=Path("."):
            output.mkdir(mode=0o700,exist_ok=False)
        for name in sorted(files):
            if name in exclude:continue
            original=directory/name
            need(original.is_file() and not original.is_symlink(),
                 "bridge_source_symlink_denied")
            # The private Bridge package declares MIT; its license must
            # accompany each independently provisioned package copy.
            need(name=="LICENSE" or original.suffix in
                 (".js",".mjs",".json",".yml",".md"),
                 "unrecognized_bridge_source_file")
            need(original.stat().st_size < 1048576,
                 "bridge_source_too_large")
            store_once(output/name,original.read_bytes())
            count+=1
    need(count>=35 and (dest/"lib/index.js").is_file() and
         (dest/"package.json").is_file(),"bridge_source_copy_incomplete")
    # This separate pinned lock installs zod and the plugin's exact Agent
    # peer contracts INTO the private extension. A link: dependency alone
    # does not install a local package's own node_modules.
    store_once(dest/"pnpm-lock.yaml",BRIDGE_LOCK.read_bytes())
    return dest


def prepare(args):
    ready=plan(args)
    need(ready["can_prepare"],"host_prerequisites_incomplete")
    home=args_home(args)
    options=argparse.Namespace(
        dsh_home=str(home),project_root=str(PROJECT),
        python=str(Path(args.python).expanduser()),pinky_proxy=None,
        computer_helper=str(Path(args.computer_helper).expanduser()),
        bridge_token=None,memory_token=None,session_dir=None,
        manual_memory_dir=None,growth_dir=None,
        trusted_host=list(args.trusted_host or []),
    )
    result=profile.generate(options)
    private_bridge=copy_private_bridge(home)
    target=home/"profiles/web"
    package=target/"package.json"
    manifest=json.loads(package.read_text())
    manifest["dependencies"]["dsh-live-bridge"]="link:"+str(private_bridge)
    # This is a brand-new owner-private profile; no running processes refer
    # to it. We never write to the source plugin node_modules or unrelated DSH profiles.
    package.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    package.chmod(0o600)
    lock=rendered_lock(home)
    store_once(target/"pnpm-lock.yaml",lock.encode())
    store_once(target/"pnpm-workspace.yaml",WORKSPACE.encode())
    if args.initialize_secrets:
        for name in ("bridge.token","memory-admin.token"):
            store_once(home/"secrets"/name,
                       (secrets.token_urlsafe(48)+"\n").encode())
    return {"schema":1,"created_home":result["home"],
            "bundles":result["bundles"],
            "private_tokens_created":2 if args.initialize_secrets else 0,
            "lock_sha256":hashlib.sha256(lock.encode()).hexdigest(),
            "packages_installed":False,"services_started":False,
            "private_bridge_copy":True,
            "device_writes":0}

def deps(args):
    home=args_home(args)
    need(private(home,True),"home_not_owner_private")
    directory=home/"profiles/web"
    bridge=home/"extensions/dsh-live-bridge"
    need(private(directory,True) and
         private(directory/"pnpm-lock.yaml"),"private_lock_missing")
    need(private(bridge,True) and
         private(bridge/"pnpm-lock.yaml"),"private_bridge_lock_missing")
    need((bridge/"pnpm-lock.yaml").read_bytes()==BRIDGE_LOCK.read_bytes(),
         "private_bridge_lock_changed")
    manifest(home)
    locked=rendered_lock(home).encode()
    need((directory/"pnpm-lock.yaml").read_bytes()==locked,"pinned_lock_changed")
    need(not args.network or args.confirm_network,"network_requires_explicit_confirmation")
    pnpm=shutil.which("pnpm")
    node=shutil.which("node")
    need(bool(pnpm and node),"node_or_pnpm_missing")
    command=[pnpm,"install","--frozen-lockfile","--ignore-scripts",
             "--reporter=append-only",
             "--prefer-offline" if args.network else "--offline"]
    env={k:v for k,v in os.environ.items() if k not in
         {"DEEPSEEK_API_KEY","OPENAI_API_KEY","HF_TOKEN","ANTHROPIC_API_KEY"}}
    # Install plugin-owned deps first, inside a private extension. Never
    # install into PROJECT/plugins/dsh-live-bridge: the author's live R657
    # service imports that source tree and must remain untouched.
    bridge_install=subprocess.run(command,cwd=bridge,env=env,
                                  capture_output=True,text=True,timeout=180,
                                  check=False)
    if bridge_install.returncode!=0:
        return {"schema":1,"installed":False,
                "ready_for_configuration_smoke":False,
                "error_code":"private_bridge_deps_failed",
                "bridge_dependencies_exit":bridge_install.returncode,
                "model_and_device_calls":0}
    p=subprocess.run(command,cwd=directory,env=env,capture_output=True,
                     text=True,timeout=180,check=False)
    cli=directory/"node_modules/@deepseek-ai/dsh/lib/bin.js"
    runtime_code=None
    inspector_code=None
    bridge_import_code=None
    missing=[]
    compatible=False
    # No model calls; import checks code/package resolution only.
    if p.returncode==0 and cli.is_file():
        safe_env={**env,"DSH_HOME":str(home)}
        cmd=[node,str(cli)]
        probe=subprocess.run([node,"--input-type=module","-e",
            "import(process.argv[1])",str(bridge/"lib/index.js")],
            cwd=bridge,env=safe_env,capture_output=True,text=True,
            timeout=30,check=False)
        bridge_import_code=probe.returncode
        if bridge_import_code==0:
            compose=subprocess.run(cmd+["--profile","web","--dump-config"],
                                   cwd=directory,env=safe_env,
                                   capture_output=True,text=True,timeout=60,
                                   check=False)
            runtime_code=compose.returncode
            required=("id: dsh-live-bridge","id: mcp-pinky-dafeiyu",
                      "id: computer-use","id: cua-macos")
            missing=[name for name in required if name not in compose.stdout]
            if compose.returncode==0 and not missing:
                inspector=subprocess.run(cmd+["plugin","--profile","web","list"],
                                         cwd=directory,env=safe_env,
                                         capture_output=True,text=True,
                                         timeout=30,check=False)
                inspector_code=inspector.returncode
                warnings=("incompatible","startup denies",
                          "exemption: not active")
                compatible=(inspector.returncode==0 and
                            not any(k in inspector.stderr.casefold()
                                    for k in warnings))
    ready=(p.returncode==0 and cli.is_file() and runtime_code==0 and
           bridge_import_code==0 and not missing and compatible and
           (directory/"pnpm-lock.yaml").read_bytes()==locked and
           (bridge/"pnpm-lock.yaml").read_bytes()==BRIDGE_LOCK.read_bytes())
    return {"schema":1,"installed":p.returncode==0,
            "exit_code":p.returncode,
            "bridge_dependencies_exit":bridge_install.returncode,
            "private_bridge_import_exit":bridge_import_code,
            "private_bridge_dependencies_installed":bridge_import_code==0,
            "pinned_cli_available":cli.is_file(),
            "pinned_cli_compose_exit":runtime_code,
            "pinned_cli_plugin_inspect_exit":inspector_code,
            "core_rows_verified":runtime_code==0 and not missing,
            "plugin_compatibility_accepted":compatible,
            "ready_for_configuration_smoke":ready,
            "lock_unchanged":(directory/"pnpm-lock.yaml").read_bytes()==locked,
            "network_allowed":bool(args.network),
            "lifecycle_scripts_disabled":True,
            "model_and_device_calls":0,
            "error_code":("none" if ready else
                "pnpm_install_failed" if p.returncode!=0 else
                "pinned_bridge_cli_or_config_not_verified")}


def doctor(args):
    home=args_home(args)
    d=profile.doctor(argparse.Namespace(
        dsh_home=str(home),pinky_app=args.pinky_app,dsh_cli=args.dsh_cli))
    manifest(home)
    lock=home/"profiles/web/pnpm-lock.yaml"
    d["lock_matches_template"]=private(lock) and lock.read_bytes()==rendered_lock(home).encode()
    # A new Mac must be allowed to provision the *Host* before optional
    # Pinky.app and native CUA helper have been installed. The older full
    # status is retained unchanged for tool-level readiness.
    optional_tool_files={"pinky_app_installed","cua_helper_executable"}
    checks=d.get("checks",{})
    d["ready_for_host_only_configuration_smoke"]=(
        d["lock_matches_template"] and bool(checks) and
        all(value is True for name,value in checks.items()
            if name not in optional_tool_files))
    d["ready_for_local_configuration_smoke"]=(
        d["ready_for_local_configuration_smoke"] and d["lock_matches_template"])
    return d

def device_plan(args):
    fw=PROJECT/"firmware/esp32/unified-wifi-wake"
    names=("CMakeLists.txt","sdkconfig.defaults","partitions.csv")
    has_lock=(fw/"dependencies.lock").is_file() or (fw/"dependencies.reference.lock").is_file()
    return {"schema":1,"mode":"esp32-first-boot-read-only",
            "firmware_tree_complete":has_lock and all((fw/n).is_file() for n in names),
            "ordered_steps":["check exact board/flash/PSRAM and partition layout",
                "install pinned ESP-IDF; build from defaults and lock",
                "back up existing board before any flash",
                "create board-specific release receipt (not another board's R619 proof)",
                "require explicit serial and confirmed flash",
                "verify physical readback, then pair USB/Wi-Fi"],
            "writes":0,"flash_authorized":False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="cmd",required=True)
    for op in ("plan","prepare","deps","doctor"):
        subcmd=sub.add_parser(op);subcmd.add_argument("--dsh-home",required=True)
        if op=="prepare":
            subcmd.add_argument("--python",default=sys.executable)
            subcmd.add_argument("--computer-helper",
                                default="~/.dsh/cua-native/dsh-cua-native")
            subcmd.add_argument("--trusted-host",action="append",default=[])
            subcmd.add_argument("--initialize-secrets",action="store_true")
        if op=="deps":
            subcmd.add_argument("--network",action="store_true")
            subcmd.add_argument("--confirm-network",action="store_true")
        if op=="doctor":
            subcmd.add_argument("--pinky-app");subcmd.add_argument("--dsh-cli")
    sub.add_parser("device-plan")
    args=parser.parse_args()
    try:
        result={"plan":plan,"prepare":prepare,"deps":deps,
                "doctor":doctor,"device-plan":device_plan}[args.cmd](args)
    except (OSError,ValueError,InstallFailure,json.JSONDecodeError,
            subprocess.TimeoutExpired) as ex:
        parser.exit(2,f"INSTALL_ERROR: {type(ex).__name__}: {ex}\n")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.cmd=="deps" and not result["ready_for_configuration_smoke"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
