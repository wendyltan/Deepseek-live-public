"""Mac-only local voice preferences: opt-in, owner-only, minimal, recoverable.

Not raw microphone recordings, not an auto-generated personal memory, not ReMe.
Long-term agent memories should reuse project's already existing opt-in E1b vault.
"""
from __future__ import annotations
import json
import os
import re
import stat
import tempfile
from pathlib import Path

DEFAULT_ROOT=Path.home()/"Library/Application Support/Deepseek-live/companion-local"
NAME=re.compile(r"^[\u4e00-\u9fffA-Za-z0-9]{1,12}$")
KEYS={"user_name","whale_name"}

class LocalPreferenceError(ValueError):
    pass

class LocalVoicePreferences:
    def __init__(self,root:Path=DEFAULT_ROOT):
        if root.is_symlink():
            raise LocalPreferenceError("preference_directory_symlink")
        self.root=root
        self.file=root/"user-preferences.json"
        self._data:dict[str,str]={}
        if root.exists():
            self._safe_existing()
            if self.file.is_file():
                if self.file.is_symlink() or self.file.stat().st_size>8_192:
                    raise LocalPreferenceError("private_profile_unsafe")
                data=json.loads(self.file.read_text(encoding="utf-8"))
                if not isinstance(data,dict) or data.get("schema")!=1:
                    raise LocalPreferenceError("private_profile_invalid")
                values=data.get("names",{})
                if not isinstance(values,dict) or any(k not in KEYS or
                   not isinstance(v,str) or not NAME.fullmatch(v) for k,v in values.items()):
                    raise LocalPreferenceError("private_profile_invalid")
                self._data=dict(values)
        # Do not even create the directory before the user explicitly confirms.
    def _safe_existing(self):
        if self.root.is_symlink() or not self.root.is_dir() or self.root.stat().st_mode&0o077:
            raise LocalPreferenceError("private_profile_permissions")
        if self.file.is_symlink():
            raise LocalPreferenceError("private_file_symlink")
    def read(self,key):
        if key not in KEYS:
            raise LocalPreferenceError("unknown_preference")
        return self._data.get(key)
    def export(self):
        return {"schema":1,"names":dict(self._data)}
    def put_explicit(self,key,value,*,confirmed:bool):
        if confirmed is not True:
            raise LocalPreferenceError("explicit_confirmation_required")
        if key not in KEYS or not isinstance(value,str) or not NAME.fullmatch(value):
            raise LocalPreferenceError("bad_preference")
        new=dict(self._data)
        new[key]=value
        self._atomic(new)
        self._data=new
    def delete_explicit(self,key,*,confirmed:bool):
        if confirmed is not True or key not in KEYS:
            raise LocalPreferenceError("explicit_confirmation_required")
        new=dict(self._data)
        new.pop(key,None)
        self._atomic(new)
        self._data=new
    def _atomic(self,new:dict):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self._safe_existing()
        tmp=None
        try:
            with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=self.root,
                                              prefix=".profile-",delete=False) as f:
                tmp=Path(f.name)
                os.fchmod(f.fileno(),0o600)
                json.dump({"schema":1,"names":new},f,ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp,self.file)
            os.chmod(self.file,0o600)
        finally:
            if tmp is not None:tmp.unlink(missing_ok=True)
