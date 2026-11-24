#!/bin/zsh
# Experimental R268 Mac Voice Gateway. Fail-closed on missing pairing/TLS.
# Starts no listener when old USB owner still runs. Does not change LaunchAgents.
set -euo pipefail
# R658 checkout-relative gateway; optional vendor root or installed websockets.
project="$(cd "$(dirname "$0")/.." && pwd -P)"
tools_root="${DAFEIYU_TOOLS_ROOT-}"
vendor="${DAFEIYU_WEBSOCKETS_VENDOR-}"
python="${DAFEIYU_PYTHON-}"
runtime_vendor="$HOME/Library/Application Support/Deepseek-live/runtime/host-vendor"
[[ -n "$tools_root" ]] || tools_root="$(dirname "$(dirname "$project")")/Tools"
if [[ -z "$vendor" ]]; then
    if [[ -f "$runtime_vendor/websockets/__init__.py" ]]; then
        vendor="$runtime_vendor"
    else
        vendor="$tools_root/esp32-s3-lab/r268-host-vendor"
    fi
fi
[[ -n "$python" ]] || python="/opt/homebrew/bin/python3.12"
[[ -x "$python" ]] || python="$(command -v python3 || true)"
[[ -x "$python" ]] || { echo 'R268 Python missing' >&2; exit 19; }
[[ -f "$project/scripts/r268_wifi_mac_gateway.py" ]] || exit 21
export PYTHONNOUSERSITE=1
if [[ -f "$vendor/websockets/__init__.py" ]]; then
    export PYTHONPATH="$vendor:$project${PYTHONPATH:+:$PYTHONPATH}"
else
    "$python" -c 'import websockets' 2>/dev/null || {
        echo 'R268 missing websockets; install in venv or set DAFEIYU_WEBSOCKETS_VENDOR' >&2
        exit 20
    }
    export PYTHONPATH="$project${PYTHONPATH:+:$PYTHONPATH}"
fi
# R301: time-limited private experiment flag, checked on every LAN startup.
# Expiry/tamper fails closed to the old Ping/Pong. USB remains untouched.
# Do not inherit a previous or unrelated shell's experimental override.
unset DF_LAN_DISABLE_PROTOCOL_PING
if [[ "$("$python" "$project/scripts/r301_protocol_ping_experiment.py" --enabled)" == "1" ]]; then
    export DF_LAN_DISABLE_PROTOCOL_PING=1
fi
# R439: user-controlled durable Mac-side preference, pinned to the
# physically verified R436 factory APP. Explicit OFF overrides temporary flags.
# With no valid preference, fail closed: old one-shot tests are not production.
# Always read private policy at gateway start; never inherit shell overrides.
unset DF_LAN_PREWAKE_ENABLED
unset DF_R441_WSS_SAFE_CONTROL
r439_pref="$(cd "$project" && "$python" "$project/scripts/r439_persistent_prewake_control.py" --decision)"
if [[ "$r439_pref" == "on" ]]; then
    export DF_LAN_PREWAKE_ENABLED=1
    # R441 controlled WSS compatibility path. No extra DSH owners or calls.
    export DF_R441_WSS_SAFE_CONTROL=1
fi
# R509: opt into unknown-total-frame streaming only when the exact APP was
# physically written and read back with an owner-only recovery receipt.
# Never trust inherited environment variables. A pre-R509 client cannot
# trigger incrementality even with a valid MAC-side policy (two-sided hello).
unset DF_LAN_INCREMENTAL_PCM_ENABLED
if [[ "$(cd "$project" && "$python" "$project/app/r509_incremental_gate.py" --enabled)" == "1" ]]; then
    export DF_LAN_INCREMENTAL_PCM_ENABLED=1
    # Stream completed multi-phrase R503 replies progressively without changing
    # legacy single-buffer test contracts.
    export DAFEIYU_R503_PROGRESSIVE_PHRASES="${DAFEIYU_R503_PROGRESSIVE_PHRASES:-1}"
fi
exec "$python" -u "$project/scripts/r268_wifi_mac_gateway.py" "$@"
