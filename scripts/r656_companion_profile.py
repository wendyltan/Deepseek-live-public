#!/usr/bin/env python3
"""R656 portable, no-network, no-secret companion DSH Profile generator.

Creates an *independent*, owner-only DSH_HOME. Does not start/restart DSH,
modify a live profile, copy credentials/sessions, install dependencies, or
call a model/device. The generated config contains path references only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

BUNDLES = (
    "@deepseek-ai/dsh-base",
    "@deepseek-ai/dsh-web-app",
    "dsh-live-bridge",
)
# R658 OSS cold-install baseline: match host CLI rc.2 exactly.
# The older author's live R657 profile had rc.5 plugins. Official CLI
# correctly warns those are incompatible. In an isolated test, rc.2 installs
# and composes without exemptions; do NOT mutate the running R657 profile.
# DSH rc.2 has runtime imports declared as peers, rather than
# direct dependencies. With pnpm autoInstallPeers=false, omitting them
# causes ERR_MODULE_NOT_FOUND even after a successful pnpm install.
PACKAGES = {
    "@deepseek-ai/dsh": "0.2.1-rc.2",
    "@deepseek-ai/dsh-anonymous-user-id": "0.2.1-rc.2",
    "@deepseek-ai/dsh-attachment": "0.2.1-rc.2",
    "@deepseek-ai/dsh-bash-local": "0.2.1-rc.2",
    "@deepseek-ai/dsh-compaction": "0.2.1-rc.2",
    "@deepseek-ai/dsh-computer-use": "0.2.1-rc.2",
    "@deepseek-ai/dsh-deepseek-account": "0.2.1-rc.2",
    "@deepseek-ai/dsh-experimental-cua-macos": "0.2.1-rc.2",
    "@deepseek-ai/dsh-fs": "0.2.1-rc.2",
    "@deepseek-ai/dsh-jobs": "0.2.1-rc.2",
    "@deepseek-ai/dsh-llm-deepseek": "0.2.1-rc.2",
    "@deepseek-ai/dsh-output-retention": "0.2.1-rc.2",
    "@deepseek-ai/dsh-ptc-runtime": "0.2.1-rc.2",
    "@deepseek-ai/dsh-sandbox": "0.2.1-rc.2",
    "@deepseek-ai/dsh-scope": "0.2.1-rc.2",
    "@deepseek-ai/dsh-sdk-protocol": "0.2.1-rc.2",
    "@deepseek-ai/dsh-session-persistence": "0.2.1-rc.2",
    "@deepseek-ai/dsh-session-query": "0.2.1-rc.2",
    "@deepseek-ai/dsh-session-telemetry": "0.2.1-rc.2",
    "@deepseek-ai/dsh-session-title-llm": "0.2.1-rc.2",
    "@deepseek-ai/dsh-shell": "0.2.1-rc.2",
    "@deepseek-ai/dsh-spill": "0.2.1-rc.2",
    "@deepseek-ai/dsh-util-time": "0.2.1-rc.2",
    "@deepseek-ai/dsh-util-workspace-path": "0.2.1-rc.2",
    "@deepseek-ai/dsh-workflow": "0.2.1-rc.2",
    "@deepseek-ai/cordis-plugin-group": "1.0.5",
    "@opentelemetry/api": "1.9.0",
}
CLI_VERSION = "0.2.1-rc.2"
BRIDGE_VERSION = "0.4.6"
PRESET = "deepseek-live-web"
REQUIRED_FILES = (
    "plugins/dsh-live-bridge/package.json",
    "plugins/dsh-live-bridge/cordis.patch.yml",
    "scripts/pinky_mcp_named_proxy.py",
    "app/companion_persona.txt",
)


def need(value: bool, code: str) -> None:
    if not value:
        raise ValueError(code)


def yaml_string(value: str | Path) -> str:
    # JSON strings are YAML-safe double-quoted scalars, including quotes,
    # backslashes, non-ASCII, whitespace and # in paths.
    return json.dumps(str(value), ensure_ascii=False)


def norm(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def ensure_new_dir(target: Path, *, mode: int = 0o700) -> None:
    need(not target.exists() and not target.is_symlink(),
         "destination_already_exists")
    target.mkdir(parents=True, mode=mode, exist_ok=False)
    os.chmod(target, mode)


def write_once(path: Path, data: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def patch_text(*, project: Path, home: Path, python: Path,
               computer_helper: Path, bridge_token: Path,
               memory_token: Path, pinky_proxy: Path,
               session_dir: Path, manual_memory_dir: Path,
               growth_dir: Path, trusted_hosts: tuple[str, ...]) -> str:
    for host in trusted_hosts:
        need(host and len(host) <= 253 and
             all(c.isalnum() or c in ".-:" for c in host),
             "trusted_host_invalid")
    # New installations get empty owner-only directories. An existing
    # installation can explicitly bind to its ORIGINAL state directories.
    # Never copy sessions or rewrite approved memory during generation.
    # DSH patches replace an entire config row, rather than merging configs.
    # Every setting below is intentionally explicit. We preserve native
    # approval policy, rather than granting automatic approvals.
    hosts_patch = ""
    if trusted_hosts:
        hosts = "\n".join(f"      - {yaml_string(h)}" for h in trusted_hosts)
        hosts_patch = (
            "- id: connection\n  config:\n    trustedHosts:\n" +
            hosts + "\n"
            "- id: web-runtime\n  config:\n    openBrowser: false\n"
            "    printUrl: true\n    surfaceContext: true\n"
            "    trustedHosts:\n" + hosts + "\n\n"
        )
    return f"""# Dafeiyu / Deepseek-live portable companion-only Web Profile.
# Only three bundles are installed (see package.json).
# Computer-use and CUA are intentional; sidebar, ops console, slides, whale,
# Unrelated profile, market and integration components are not included.
{hosts_patch}- id: agent-default-model
  name: "@deepseek-ai/dsh-agent-default-model"
  config:
    provider: deepseek-official
    model: deepseek-flash
    reasoningEffort: high

- id: dsh-live-bridge
  name: "dsh-live-bridge"
  config:
    workspaceRoot: {yaml_string(project)}
    bridgeTokenFile: {yaml_string(bridge_token)}
    toolMode: native
    sessionRecovery: true
    sessionStateDir: {yaml_string(session_dir)}
    webPresetId: {PRESET}
    companionFacts: true
    companionPersona: true
    manualMemory: true
    personaGrowth: true
    memoryAdminTokenFile: {yaml_string(memory_token)}
    manualMemoryDir: {yaml_string(manual_memory_dir)}
    personaGrowthDir: {yaml_string(growth_dir)}

# Optional native Web search only. Web fetch remains off to match the
# reference profile. Computer/Pinky tools are governed by native approvals.
- id: preset-deepseek-live-web
  name: "@deepseek-ai/dsh-agent-preset"
  config:
    id: {PRESET}
    order: 5
    plugins:
      - id: tool-web
        name: "@deepseek-ai/dsh-tool-web"
        config:
          search: true
          fetch: false
          searchTimeoutMs: 60000

- insert:
    - id: mcp-pinky-dafeiyu
      name: "@deepseek-ai/dsh-mcp-client"
      config:
        serverName: pinky_dafeiyu
        transport: stdio
        command: {yaml_string(python)}
        args:
          - {yaml_string(pinky_proxy)}
        toolCallTimeoutMs: 120000
        failOnStartupError: false

    # Retain explicit computer control. Does not imply automatic permission.
    - id: computer-use
      name: "@deepseek-ai/dsh-computer-use"
    - id: cua-macos
      name: "@deepseek-ai/dsh-experimental-cua-macos"
      config:
        helperPath: {yaml_string(computer_helper)}
"""


def generate(args: argparse.Namespace) -> dict:
    home = norm(args.dsh_home)
    project = norm(args.project_root)
    # Keep the original invocation path, even if Homebrew's Python binary
    # is a symlink. The MCP launch command is an observable Session contract.
    python = Path(args.python).expanduser().absolute()
    helper = norm(args.computer_helper)
    bridge = norm(args.bridge_token or home / "secrets" / "bridge.token")
    memory = norm(args.memory_token or home / "secrets" / "memory-admin.token")
    pinky = norm(args.pinky_proxy or project / "scripts/pinky_mcp_named_proxy.py")
    state_dir = home / "companion-state"
    session_dir = norm(args.session_dir or state_dir / "session-ledger")
    manual_memory_dir = norm(args.manual_memory_dir or state_dir / "manual-memory")
    growth_dir = norm(args.growth_dir or state_dir / "persona-growth")
    need(project.is_dir(), "project_root_not_found")
    need(all((project / f).is_file() for f in REQUIRED_FILES),
         "project_sources_incomplete")
    need(home != project and home not in project.parents and
         project not in home.parents and
         not any(part in ("node_modules", "private-runtime", "tmp")
                 for part in home.parts),
         "home_must_be_a_separate_durable_location")
    need(home.parent.is_dir(), "home_parent_missing")
    # Public package manifest contains a local source *path*, not local
    # credentials, tokens, Session data, private voice seed or identity.
    manifest = {
        "name": "dsh-profile-web",
        "private": True,
        "dependencies": {
            **PACKAGES,
            "dsh-live-bridge":
                "link:" + str(project / "plugins/dsh-live-bridge"),
        },
        "dsh": {"profile": {"bundles": list(BUNDLES)}},
    }
    patch = patch_text(project=project, home=home, python=python,
                       computer_helper=helper, bridge_token=bridge,
                       memory_token=memory, pinky_proxy=pinky,
                       session_dir=session_dir, manual_memory_dir=manual_memory_dir,
                       growth_dir=growth_dir,
                       trusted_hosts=tuple(args.trusted_host or ()))
    # Everything generated is owner-only and never overwrites a pre-existing
    # official DSH_HOME, including any pre-existing DSH profiles.
    ensure_new_dir(home)
    try:
        profile_root = home / "profiles"
        profile = profile_root / "web"
        secret_dir = home / "secrets"
        state_dir = home / "companion-state"
        for p in (profile_root, profile, secret_dir, state_dir,
                  state_dir/"session-ledger", state_dir/"manual-memory",
                  state_dir/"persona-growth"):
            ensure_new_dir(p)
        write_once(profile / "package.json",
                   json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        write_once(profile / "cordis.patch.yml", patch)
        write_once(profile / "cordis.yml", "[]\n")
        write_once(home / "PROFILE_INFO.json", json.dumps({
            "schema": 1,
            "purpose": "minimal_dafeiyu_companion",
            "dsh_cli_version_tested": CLI_VERSION,
            "bridge_version_tested": BRIDGE_VERSION,
            "bundles": list(BUNDLES),
            "required_local_tools": ["pinky_dafeiyu", "computer-use",
                                     "cua-macos"],
            "secrets_created": False,
            "third_party_assets_copied": False,
            "users_session_copied": False,
            "model_api_calls": 0,
            "phones_acted_on": 0,
        }, indent=2, ensure_ascii=False) + "\n")
    except BaseException:
        # Do not delete a directory if a concurrent actor created anything
        # else in it. Leave evidence for manual inspection instead.
        raise
    return {"home": str(home), "bundles": len(BUNDLES),
            "declared_packages": len(manifest["dependencies"]),
            "contains_secrets": False, "started_service": False}


def inspect(args: argparse.Namespace) -> dict:
    home = norm(args.dsh_home)
    profile = home / "profiles/web"
    need(home.is_dir() and profile.is_dir(), "profile_not_found")
    data = json.loads((profile / "package.json").read_text())
    info = json.loads((home / "PROFILE_INFO.json").read_text())
    txt = (profile / "cordis.patch.yml").read_text()
    need(data.get("dsh", {}).get("profile", {}).get("bundles")
         == list(BUNDLES), "bundle_allowlist_wrong")
    need(info.get("purpose") == "minimal_dafeiyu_companion",
         "wrong_profile_identity")
    need(all(f"id: {x}" in txt
             for x in ("mcp-pinky-dafeiyu", "computer-use", "cua-macos",
                       "dsh-live-bridge")), "essential_tools_missing")
    need(not any(x in txt for x in (
        "dsh-better-sidebar", "dsh-ops-console", "dsh-slidestudio",
        "dsh-bili-whale", "cc-switch-mcp-rea")),
        "optional_plugin_in_primary_companion_patch")
    for p in (home, home / "profiles", profile, home / "secrets",
              home / "companion-state"):
        need(not p.is_symlink() and
             stat.S_IMODE(p.stat().st_mode) == 0o700,
             "profile_permissions_not_owner_private")
    return {"profile_created": True, "bundles": len(BUNDLES),
            "computer_control_declared": True,
            "pinky_declared": True, "session_recovery_declared": True,
            "requires_official_dsh_dependencies_install": True,
            "requires_personal_secrets": True,
            "actual_model_phone_computer_tests": "not_run"}


def doctor(args: argparse.Namespace) -> dict:
    """Check local prerequisites without connecting to a provider or device.

    Never disclose token bytes, private paths, Session contents or phone info.
    An all-green local check still does NOT prove consent or real tool execution.
    """
    base = inspect(args)
    home = norm(args.dsh_home)
    patch = (home / "profiles/web/cordis.patch.yml").read_text()
    package_root = home / "profiles/web/node_modules"

    def scalar(field: str) -> Path:
        values = [x.split(":", 1)[1].strip() for x in patch.splitlines()
                  if re.match(r"^\s*" + re.escape(field) + r":\s*", x)]
        need(len(values) == 1, "doctor_scalar_missing_" + field)
        return Path(json.loads(values[0]))

    def secret_ready(path: Path) -> bool:
        try:
            st = path.lstat()
            return (stat.S_ISREG(st.st_mode) and
                    not path.is_symlink() and st.st_uid == os.getuid() and
                    stat.S_IMODE(st.st_mode) == 0o600 and
                    0 < st.st_size < 4096)
        except OSError:
            return False

    helper = scalar("helperPath")
    lines = patch.splitlines()
    locations = []
    for index, line in enumerate(lines[:-1]):
        if line.strip() == "args:" and lines[index + 1].strip().startswith("- "):
            locations.append(lines[index + 1].strip()[2:])
    need(len(locations) == 1, "pinky_proxy_command_missing")
    pinky_proxy = Path(json.loads(locations[0]))
    phone = str(norm(args.pinky_app)) if args.pinky_app else (
        "/Applications/Pinky.app")
    names = {
        "macos_host": sys.platform == "darwin",
        "pinky_proxy_script_available": pinky_proxy.is_file(),
        "bridge_plugin_installed": (package_root / "dsh-live-bridge/package.json").is_file(),
        "computer_use_plugin_installed": (
            package_root / "@deepseek-ai/dsh-computer-use/package.json").is_file(),
        "cua_macos_plugin_installed": (
            package_root / "@deepseek-ai/dsh-experimental-cua-macos/package.json").is_file(),
        "cua_helper_executable": helper.is_file() and os.access(helper, os.X_OK),
        "pinky_app_installed": Path(phone).is_dir(),
        "bridge_token_private": secret_ready(scalar("bridgeTokenFile")),
        "memory_admin_token_private": secret_ready(scalar("memoryAdminTokenFile")),
        "python_available": shutil.which("python3") is not None,
        "node_available": shutil.which("node") is not None,
        "pnpm_available": shutil.which("pnpm") is not None,
        "dsh_cli_available": (
            (package_root / "@deepseek-ai/dsh/lib/bin.js").is_file() or
            shutil.which("dsh") is not None or
            bool(args.dsh_cli and norm(args.dsh_cli).is_file())),
    }
    return {
        "profile": base["profile_created"],
        "checks": names,
        "ready_for_local_configuration_smoke": all(names.values()),
        "provider_authenticated": "not_checked",
        "physical_r619_firmware_provisioned": "not_checked",
        "phone_or_computer_action_verified": "not_run",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create", help="create a new private profile only")
    create.add_argument("--dsh-home", required=True)
    create.add_argument("--project-root", required=True)
    create.add_argument("--python", default=sys.executable)
    create.add_argument("--pinky-proxy")
    create.add_argument("--computer-helper", default="~/.dsh/cua-native/dsh-cua-native")
    create.add_argument("--bridge-token")
    create.add_argument("--memory-token")
    create.add_argument("--session-dir", help="explicit existing Session ledger")
    create.add_argument("--manual-memory-dir", help="explicit existing approved memory")
    create.add_argument("--growth-dir", help="explicit existing growth approval state")
    create.add_argument("--trusted-host", action="append", default=[],
                        help="opt-in trusted remote host, no URL/path")
    verify = sub.add_parser("verify", help="offline structural verification")
    verify.add_argument("--dsh-home", required=True)
    health = sub.add_parser("doctor", help="read-only prerequisite inventory")
    health.add_argument("--dsh-home", required=True)
    health.add_argument("--pinky-app", help="installed macOS Pinky.app location")
    health.add_argument("--dsh-cli", help="local official DSH bin.js if not on PATH")
    opts = parser.parse_args()
    try:
        result = (generate(opts) if opts.cmd == "create" else
                  doctor(opts) if opts.cmd == "doctor" else inspect(opts))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.exit(2, f"COMPANION_PROFILE_ERROR: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
