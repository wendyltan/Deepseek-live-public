"""Read-only metadata summary for the opt-in E1b manual memory vault.

This never scans for user's memory, enables consent, reads DSH sessions, or
exposes Markdown bodies. Call with a *known* project-local, private vault path.
User-facing SwiftUI reads only this bounded, owner-private sidecar summary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path.home() / "Library/Application Support/Deepseek-live/companion-native/memory-overview.json"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f-]{27,35}$",re.IGNORECASE)


class MemoryOverviewError(ValueError):
    pass


def build_overview(vault: Path, *, project_root: Path = PROJECT_ROOT, now=None):
    project = project_root.resolve(strict=True)
    path = vault.resolve(strict=True)
    if vault.is_symlink() or not path.is_relative_to(project) or path == project:
        raise MemoryOverviewError("vault_not_within_project")
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise MemoryOverviewError("vault_not_private")
    index_path = path / "memory-index-v1.json"
    if index_path.is_symlink() or not index_path.is_file() or index_path.stat().st_size > 128*1024:
        raise MemoryOverviewError("memory_index_unavailable_or_unsafe")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    consent = index.get("consent")
    entries = index.get("items")
    if index.get("version")!=1 or not isinstance(consent,dict) or        type(consent.get("manual_write")) is not bool or consent.get("auto_extraction") is not False or        not isinstance(entries,dict) or len(entries)>128:
        raise MemoryOverviewError("memory_index_invalid")
    result = []
    for identifier,info in entries.items():
        if not isinstance(identifier,str) or not UUID_RE.fullmatch(identifier) or not isinstance(info,dict):
            raise MemoryOverviewError("memory_entry_invalid")
        revision, updated = info.get("revision"),info.get("updated_at")
        source=info.get("source")
        path_md = path / f"{identifier}.md"
        if path_md.is_symlink() or not path_md.is_file() or path_md.stat().st_size>8193:
            raise MemoryOverviewError("memory_document_missing_or_unsafe")
        if (type(revision) is not int or revision<1 or
            not isinstance(updated,(int,float)) or not isinstance(source,str) or
            source not in ("user_explicit","verified_esp32_user_voice") or
            not isinstance(info.get("hash"),str)):
            raise MemoryOverviewError("memory_entry_metadata_invalid")
        raw = path_md.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=info["hash"]:
            raise MemoryOverviewError("memory_entry_integrity_failed")
        result.append({
            "id_short":identifier[:8].upper(),
            "file_name":identifier+".md",
            "revision":revision,
            "updated_at_unix":float(updated)/1000.0 if updated>10**11 else float(updated),
            "source":"手动添加" if source=="user_explicit" else "语音记住",
        })
    result.sort(key=lambda item:item["updated_at_unix"],reverse=True)
    return {
        "schema":1,
        "source":"e1b_manual_memory",
        "vault_path":str(path),
        "generated_at_unix":now if now is not None else time.time(),
        "manual_write":consent["manual_write"],
        "auto_extraction":False,
        "item_count":len(result),
        "recent":result[:12],
        "redaction":"metadata_only_no_content",
    }


def atomic_write(snapshot:dict,output:Path):
    target=output.parent
    if target.is_symlink() or output.is_symlink():
        raise MemoryOverviewError("symlink_target_not_allowed")
    target.mkdir(parents=True,mode=0o700,exist_ok=True)
    if stat.S_IMODE(target.stat().st_mode) & 0o077:
        raise MemoryOverviewError("overview_dir_not_private")
    raw=(json.dumps(snapshot,ensure_ascii=False,separators=(",",":"))+"\n").encode()
    if len(raw)>16_384:
        raise MemoryOverviewError("overview_too_large")
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(mode="wb",dir=target,prefix=".memory-summary-",delete=False) as handle:
            tmp=Path(handle.name)
            os.fchmod(handle.fileno(),0o600)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp,output)
        os.chmod(output,0o600)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return output


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--vault",required=True,type=Path,
                        help="already authorised 0700 project-local E1b memory directory")
    parser.add_argument("--output",type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args()
    data=build_overview(args.vault)
    result=atomic_write(data,args.output)
    print("NATIVE_MEMORY_OVERVIEW_METADATA_ONLY",
          json.dumps({"entries":data["item_count"],"manual":data["manual_write"],
                      "auto_extraction":False,"output":str(result)},ensure_ascii=False))


if __name__=="__main__":
    main()
