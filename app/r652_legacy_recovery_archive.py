"""R652 private immutable recovery-only archive: R550/R556 were NOT current R619.

A sealed bundle verifies historical manifests and APP hashes; it cannot
authorize a new flash or replace the distinct R619 on-device physical receipt.
"""
from __future__ import annotations
import hashlib,json,os,stat
from functools import lru_cache
from pathlib import Path

ROOT=Path.home()/'Library/Application Support/Deepseek-live/release-evidence/r652-r550-r556-recovery-20261120'
MANIFEST_SHA='d465613d5234cfb21ee64f2b3c13b60abe1d7011c9e26478a5760b038cd46d0b'
FILES=('r550/app.bin','r550/manifest.json','r556/app.bin','r556/manifest.json')
EXPECTED={'r550/app.bin':'331a211897e71a71b05e3e0f6f180bb97c24230723f0a42019d41ea79c113d5e',
          'r556/app.bin':'28fbf6e3e29fb376bbe699df9e03aa13cbf52caf96c81d238789e4e103251b8d'}
def private_dir(p:Path)->bool:
    try:
        st=p.lstat()
        return stat.S_ISDIR(st.st_mode) and not p.is_symlink() and st.st_uid==os.getuid() and stat.S_IMODE(st.st_mode)==0o700
    except OSError:return False
@lru_cache(maxsize=20)
def digest(path:str,key:tuple[int,...])->str|None:
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        try:
            st=os.fstat(fd)
            if (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)!=key:return None
            h=hashlib.sha256();left=st.st_size
            while left:
                x=os.read(fd,min(2**20,left))
                if not x:return None
                h.update(x);left-=len(x)
            return h.hexdigest()
        finally:os.close(fd)
    except OSError:return None
def file_sha(p:Path)->str|None:
    try:
        st=p.lstat()
        if (not stat.S_ISREG(st.st_mode) or p.is_symlink()
            or st.st_uid!=os.getuid()
            or stat.S_IMODE(st.st_mode)!=0o600
            or not 0<st.st_size<=12*2**20):return None
        return digest(str(p),(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns))
    except OSError:return None
def archive_valid(*,root:Path=ROOT,manifest_sha:str=MANIFEST_SHA)->bool:
    try:
        if not all(private_dir(p) for p in (root.parent,root,root/'r550',root/'r556')):return False
        m=root/'manifest.json'
        if file_sha(m)!=manifest_sha:return False
        data=json.loads(m.read_bytes())
        rows=data.get('entries')
        if not (data.get('schema')==1 and
                data.get('stage')=='r652_sealed_historical_r550_r556_recovery_only'
                and data.get('not_current_firmware') is True
                and data.get('no_live_flash_authorization') is True
                and type(rows) is dict and set(rows)==set(FILES)):return False
        for name in FILES:
            info=rows[name]
            if (type(info) is not dict or type(info.get('bytes')) is not int
                or type(info.get('sha256')) is not str
                or file_sha(root/name)!=info['sha256']
                or (root/name).stat().st_size!=info['bytes']):return False
            if name in EXPECTED and info['sha256']!=EXPECTED[name]:return False
        return True
    except (OSError,ValueError,TypeError,KeyError,UnicodeError):
        return False
