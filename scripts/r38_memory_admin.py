"""Small OS-process boundary for Mac owner UI; scoped local memory only."""
from __future__ import annotations
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.r38_memory_loop import read_store,remove_record
def main():
    action=sys.argv[1] if len(sys.argv)>1 else "status"
    if action=="status":
        print(json.dumps({"schema":1,"items":read_store()},ensure_ascii=False))
    elif action=="remove" and len(sys.argv)==3:
        print(json.dumps({"removed":remove_record(sys.argv[2])}))
    else:raise ValueError("bad_memory_admin_command")
if __name__=="__main__":main()
