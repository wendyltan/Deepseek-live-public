"""Explicit Mac-only action to dismiss one private voice memory suggestion.

Approval follows separate E1b per-fact explicit confirmation; never save
facts from this tool. No path is accepted from the user-facing CLI.
"""
from __future__ import annotations
import json
import os
import re
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.voice_memory_candidates import QUEUE, _private_file

ID = re.compile(r"[a-f0-9]{32}\Z")
def discard_candidate(identifier:str,queue:Path=QUEUE)->bool:
    if not isinstance(identifier,str) or ID.fullmatch(identifier) is None:
        return False
    if not _private_file(queue,32768):
        return False
    if queue.parent.is_symlink() or queue.parent.stat().st_mode&0o077:
        return False
    try:
        obj=json.loads(queue.read_text(encoding="utf-8"))
        if obj.get("schema")!=1 or not isinstance(obj.get("items"),list):
            return False
        rows=obj["items"]
        if len(rows)>24 or any(not isinstance(x,dict) or
           set(x)!={"id","text","created_at"} or
           not isinstance(x["id"],str) or ID.fullmatch(x["id"]) is None or
           not isinstance(x["text"],str) or len(x["text"])>200 or
           not isinstance(x["created_at"],int)
           for x in rows):
            return False
        after=[x for x in rows if x["id"]!=identifier]
        if len(after)==len(rows):return False
        blob=json.dumps({"schema":1,"items":after},
                        ensure_ascii=False,separators=(",",":")).encode("utf-8")
        if len(blob)>32768:return False
        temp=None
        try:
            with tempfile.NamedTemporaryFile(dir=queue.parent,
                    prefix=".voice-reviewed-",delete=False) as f:
                temp=Path(f.name)
                os.fchmod(f.fileno(),0o600)
                f.write(blob);f.flush();os.fsync(f.fileno())
            os.replace(temp,queue)
        finally:
            if temp:temp.unlink(missing_ok=True)
        return True
    except (OSError,ValueError,TypeError):
        return False

if __name__=="__main__":
    if len(sys.argv)!=3 or sys.argv[1]!="discard":
        raise SystemExit(2)
    success=discard_candidate(sys.argv[2])
    print(json.dumps({"removed":success},separators=(",",":")))
    raise SystemExit(0 if success else 2)
