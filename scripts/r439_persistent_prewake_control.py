#!/usr/bin/env python3
"""R439 explicit, persistent R436 wake setting; no service or audio side effects."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.r439_persistent_prewake import decision, set_enabled, status


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--decision", action="store_true")
    g.add_argument("--enabled", action="store_true")
    g.add_argument("--enable", action="store_true")
    g.add_argument("--disable", action="store_true")
    args = p.parse_args()
    if args.decision:
        pref = decision()
        print("unset" if pref is None else "on" if pref else "off")
    elif args.enabled:
        print("1" if decision() is True else "0")
    else:
        report = set_enabled(args.enable) if (args.enable or args.disable) else status()
        print(json.dumps(report, separators=(",", ":")))


if __name__ == "__main__":
    main()
