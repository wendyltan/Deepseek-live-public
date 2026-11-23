#!/bin/zsh
# R268 supervisor identity-only process, default dry-run. Do NOT install
# as LaunchAgent before real board Wi-Fi DHCP and independent 5V acceptance.
set -euo pipefail
project="$(cd "$(dirname "$0")/.." && pwd -P)"
vendor="${DAFEIYU_WEBSOCKETS_VENDOR:-$project/app/runtime/vendor}"
[[ -f "$vendor/serial/__init__.py" ]] || { echo "R268: board locator unavailable" >&2; exit 30; }
export PYTHONNOUSERSITE=1
export PYTHONPATH="$vendor:$project${PYTHONPATH:+:$PYTHONPATH}"
exec "${DAFEIYU_PYTHON:-python3.12}" -u "$project/scripts/r268_transport_supervisor.py" "$@"
