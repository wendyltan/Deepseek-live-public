"""R676 user-chosen global CUA application access policy.
Does not change macOS TCC, native CUA grants, or DSH model permissions.
"""
from __future__ import annotations
import argparse,json,os,stat,tempfile,time
from pathlib import Path
DIR=Path.home()/"Library/Application Support/Deepseek-live/companion-native"
FILE=DIR/"r676-computer-preconsent.json"
def read():
    try:
        s=FILE.lstat()
        if not stat.S_ISREG(s.st_mode) or FILE.is_symlink() or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>1024:return False
        j=json.loads(FILE.read_text())
        return j.get("schema")==1 and j.get("allow_all_native_cua_apps") is True
    except (OSError,ValueError,TypeError):return False
def set_choice(enabled):
    s=DIR.lstat()
    if not stat.S_ISDIR(s.st_mode) or DIR.is_symlink() or s.st_uid!=os.getuid() or s.st_mode&0o077:
        raise ValueError("private_owner_directory_required")
    if FILE.is_symlink():raise ValueError("symlink_target_forbidden")
    info={"schema":1,"allow_all_native_cua_apps":bool(enabled),
          "scope":"native_cua_app_access_all_apps",
          "chosen_by_mac_app":True,"changed_at_unix":time.time()}
    with tempfile.NamedTemporaryFile("w",dir=DIR,prefix=".r676-",delete=False) as fd:
        tmp=Path(fd.name)
        os.fchmod(fd.fileno(),0o600)
        json.dump(info,fd,separators=(",",":"))
        fd.flush();os.fsync(fd.fileno())
    try:os.replace(tmp,FILE)
    finally:tmp.unlink(missing_ok=True)
    return read()==enabled
if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("action",choices=("status","allow","revoke"))
    a.add_argument("--confirm",default="")
    q=a.parse_args()
    try:
        if q.action!="status":
            assert q.confirm==("CONFIRM_ALL_MAC_APPS_PRECONSENT" if q.action=="allow"
                                else "REVOKE_ALL_MAC_APPS_PRECONSENT")
            if not set_choice(q.action=="allow"):raise ValueError("write_not_verified")
        print(json.dumps({"ok":True,"enabled":read(),
                          "scope":"all_native_cua_application_access_not_system_tcc"},separators=(",",":")))
    except Exception:
        print(json.dumps({"ok":False,"error":"local_permission_write_rejected"}))
        raise SystemExit(2)
