#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${DAFEIYU_PYTHON:-python3}" -m scripts.start_whisper_server "$@"
