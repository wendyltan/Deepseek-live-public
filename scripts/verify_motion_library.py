#!/usr/bin/env python3
"""Verify all 106 DFSP files on a staged folder or mounted microSD, read-only."""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/"release-assets/animation/dfsp-hashes.json"
HEADER=struct.Struct("<4sBHHBH")


def sha(path:Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):
            h.update(b)
    return h.hexdigest()


def inspect(motions_dir:Path) -> dict:
    m=json.loads(MANIFEST.read_text())
    expected=m["motions"]
    if len(expected)!=106 or [x["id"] for x in expected]!=[f"m{i:03}" for i in range(106)]:
        raise ValueError("invalid_expected_manifest")
    ok=0
    missing=[]
    mismatched=[]
    for entry in expected:
        path=motions_dir/(entry["id"].upper()+".DFS")
        if path.is_symlink() or not path.is_file():
            missing.append(entry["id"])
            continue
        if path.stat().st_size!=entry["bytes"]:
            mismatched.append(entry["id"]+":size")
            continue
        with path.open("rb") as f:
            raw=f.read(HEADER.size)
        if len(raw)!=HEADER.size:
            mismatched.append(entry["id"]+":header")
            continue
        head=HEADER.unpack(raw)
        if head!=(b"DFSP",1,240,240,8,entry["frames"]):
            mismatched.append(entry["id"]+":header")
            continue
        if sha(path)!=entry["sha256"]:
            mismatched.append(entry["id"]+":sha256")
            continue
        ok+=1
    extras=sorted(
        p.name for p in motions_dir.glob("*.DFS")
        if p.name not in {x["id"].upper()+".DFS" for x in expected}
    ) if motions_dir.is_dir() else []
    return {"schema":1,"license":m["license"],"verified":ok,
            "required":106,"missing":missing,"mismatched":mismatched,
            "extra_dfs":extras,"complete":ok==106 and not extras,
            "sd_written":False,"flash_performed":False}


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--motions-dir",type=Path,required=True)
    a.add_argument("--strict",action="store_true")
    args=a.parse_args()
    result=inspect(args.motions_dir)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.strict and not result["complete"]:
        raise SystemExit(2)


if __name__=="__main__":
    main()
