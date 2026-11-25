#!/usr/bin/env python3
"""Start local loopback whisper-server for fast low-latency ASR."""
from __future__ import annotations

import os
from pathlib import Path
import shutil

from app.stt_local import ROOT, TOOLS, VAD_MODEL, _pick_path, selected_asr_model


def main() -> None:
    _, model = selected_asr_model()
    server = _pick_path(
        "DAFEIYU_WHISPER_SERVER",
        *([Path(found)] if (found := shutil.which("whisper-server")) else []),
        ROOT / "app/runtime/bin/whisper-server",
        TOOLS / "whisper.cpp/build/bin/whisper-server",
    )
    if not server.is_file():
        raise SystemExit(f"whisper-server executable not found: {server}")
    if not VAD_MODEL.is_file() or VAD_MODEL.stat().st_size < 100_000:
        raise SystemExit("Whisper VAD model is unavailable")
    port = os.environ.get("DAFEIYU_WHISPER_PORT", "8910").strip() or "8910"
    os.execv(
        str(server),
        [
            str(server),
            "--host",
            "127.0.0.1",
            "--port",
            port,
            "-m",
            str(model),
            "--vad",
            "-vm",
            str(VAD_MODEL),
            "-l",
            "zh",
            "-sns",
            "-nt",
            "-nf",
        ],
    )


if __name__ == "__main__":
    main()
