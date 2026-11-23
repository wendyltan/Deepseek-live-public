"""R640 immutable, owner-only archival release proof for historical gates.

Old R436..R511/R587 receipts remain historical facts, NEVER current flash
authorization. R619's separate physical gate alone authorizes current PCM.
No test directory, mocks or writable enable flags in this production reader.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib,json,os,stat
from pathlib import Path

ROOT=Path.home()/'Library/Application Support/Deepseek-live/release-evidence/r640-historical-physical-proofs-20261120'
PINNED_MANIFEST_SHA256='7a09309206bc716c48db6c71c92e3c41a1624cd47b472f97f7c1f40d6f2413f0'
MAX_BYTES=12*1024*1024

def _private_dir(p:Path)->bool:
    try:
        s=p.lstat()
        return (stat.S_ISDIR(s.st_mode) and not p.is_symlink()
                and s.st_uid==os.getuid() and stat.S_IMODE(s.st_mode)==0o700)
    except OSError:return False

@lru_cache(maxsize=96)
def _digest_file(path:str,signature:tuple[int,...])->str|None:
    """Bounded digest with O_NOFOLLOW; cache only exact immutable file identity."""
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        try:
            check=os.fstat(fd)
            now=(check.st_dev,check.st_ino,check.st_size,
                 check.st_mtime_ns,check.st_ctime_ns)
            if now!=signature:return None
            h=hashlib.sha256()
            remaining=check.st_size
            while remaining:
                data=os.read(fd,min(1024*1024,remaining))
                if not data:return None
                h.update(data)
                remaining-=len(data)
            return h.hexdigest()
        finally:os.close(fd)
    except OSError:return None

def _entry_digest(p:Path,max_bytes:int=MAX_BYTES)->str|None:
    try:
        s=p.lstat()
        if (not stat.S_ISREG(s.st_mode) or p.is_symlink()
            or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o600
            or not 0<s.st_size<=max_bytes):
            return None
        signature=(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        return _digest_file(str(p),signature)
    except OSError:return None

def archive_valid(*,root:Path=ROOT,pinned_sha:str=PINNED_MANIFEST_SHA256)->bool:
    """Fail closed on a missing, replaced, modified or insufficiently private proof.

    Comparison to an exact code-pinned sealed manifest prevents unapproved
    additions/rewrites. All 18 active sources verified by SHA on first read and
    whenever identity/mtime/ctime changes. Stat is rechecked every call.
    """
    try:
        root=Path(root)
        if not (_private_dir(root.parent) and _private_dir(root)):
            return False
        manifest=root/'manifest.json'
        if _entry_digest(manifest,64*1024)!=pinned_sha:return False
        doc=json.loads(manifest.read_bytes())
        rows=doc.get('entries')
        if not (doc.get('schema')==1 and
                doc.get('stage')=='r640_sealed_historical_proof_archive' and
                doc.get('no_current_flash_authorization') is True and
                type(rows) is dict and len(rows)==19 and
                doc.get('optional_absent')==['wake/R441_RECOVERY']):
            return False
        for section in ('wake','pcm','r587'):
            if not _private_dir(root/section):return False
        present=0
        for alias,row in rows.items():
            if type(alias) is not str or type(row) is not dict:return False
            parts=alias.split('/')
            if (len(parts)!=2 or parts[0] not in ('wake','pcm','r587') or
                not parts[1].replace('_','').isalnum()):
                return False
            ext='.bin' if parts[1].endswith(('_APP','_IMAGE')) else '.json'
            rel=alias+ext
            if row.get('path')!=rel:return False
            file=root/rel
            if row.get('present') is False:
                if (alias!='wake/R441_RECOVERY' or
                    file.exists() or file.is_symlink()):
                    return False
                continue
            if (row.get('present') is not True or
                type(row.get('bytes')) is not int or
                type(row.get('sha256')) is not str or
                not 0<row['bytes']<=MAX_BYTES):
                return False
            if _entry_digest(file)!=row['sha256']:return False
            if file.stat().st_size!=row['bytes']:return False
            present+=1
        return present==18
    except (OSError,ValueError,KeyError,TypeError,UnicodeError):
        return False
