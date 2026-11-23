#!/bin/zsh
# Start the user-authorized Wi-Fi voice gateway. This script is never
# installed as a background service and does not alter running USB owners.
set -euo pipefail

project="$(cd "$(dirname "$0")/.." && pwd -P)"
python="${DAFEIYU_PYTHON:-python3.12}"
bind="${DAFEIYU_GATEWAY_BIND:-127.0.0.1}"
port="${DAFEIYU_GATEWAY_PORT:-8877}"
identity="$HOME/Library/Application Support/Deepseek-live/lan-pairing"

[[ -n "${DAFEIYU_DSH_BRIDGE_TOKEN_FILE:-}" ]] || {
  print -u2 "Set DAFEIYU_DSH_BRIDGE_TOKEN_FILE to the Host's private bridge.token path."
  exit 2
}
[[ -x "$(command -v "$python")" ]] || { print -u2 "Python executable missing"; exit 3; }
[[ -f "$identity/authorized-devices.json" ]] || {
  print -u2 "Run python3.12 scripts/r268_pairing_prepare.py on your Mac first."
  exit 4
}
[[ -f "$identity/gateway.crt.pem" && -f "$identity/gateway.key.pem" ]] || {
  print -u2 "Gateway TLS identity missing."
  exit 4
}
[[ "$port" == <-> ]] || { print -u2 "Port must be numeric"; exit 5; }

exec /bin/zsh "$project/scripts/r268_start_lan_gateway.sh"  --bind "$bind" --port "$port"  --tls-cert "$identity/gateway.crt.pem"  --tls-key "$identity/gateway.key.pem"
