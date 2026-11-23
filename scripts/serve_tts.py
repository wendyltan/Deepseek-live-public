#!/usr/bin/env python3
"""Start the local Qwen3-TTS speech service with the selected reference voice."""
from __future__ import annotations

import runpy

if __name__ == "__main__":
    runpy.run_module("app.r644_r503_production_server", run_name="__main__")
