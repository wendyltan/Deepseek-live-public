"""Verified, private, phrase-exact local Qwen PCM cache for fixed greetings.

This is a Mac-side first stage. No ESP SD filesystem writes are authorized.
No model/LLM call when hitting the cache. Missing/corrupt files fall back to
verified normal TTS. Never reuse a recording for a different spoken phrase.
"""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
from pathlib import Path
from app.preset_voice_commands import PRESET_WORDING

ROOT=Path.home()/"Library/Application Support/Deepseek-live/voice-pcm-cache-v1"
ALLOWED=frozenset(PRESET_WORDING.values())
RATE=24000
MAX_BYTES=2_000_000

def key(text):
    return hashlib.sha256(text.encode("utf8")).hexdigest()

def safe_file(path,max_bytes):
    try:
        info=path.lstat()
        return (path.is_file() and not path.is_symlink() and 0<info.st_size<=max_bytes
                and info.st_mode&0o077==0)
    except OSError:return False

def cached_pcm(text,*,root=ROOT):
    if text not in ALLOWED or root.is_symlink():return None
    k=key(text)
    m=root/(k+".json")
    f=root/(k+".pcm")
    if not safe_file(m,512) or not safe_file(f,MAX_BYTES):return None
    try:
        meta=json.loads(m.read_text())
        raw=f.read_bytes()
        if meta!={"text_sha256":k,"pcm_sha256":hashlib.sha256(raw).hexdigest(),
                 "bytes":len(raw),"rate":RATE} or len(raw)%2:return None
        return raw
    except (OSError,ValueError):return None

def store_pcm(text,pcm,*,root=ROOT):
    if text not in ALLOWED or not isinstance(pcm,bytes) or not 2<=len(pcm)<=MAX_BYTES or len(pcm)%2:
        raise ValueError("unapproved_cached_phrase")
    if root.exists() and (root.is_symlink() or root.stat().st_mode&0o077):
        raise ValueError("unsafe_pcm_cache_directory")
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    metadata={"text_sha256":key(text),"pcm_sha256":hashlib.sha256(pcm).hexdigest(),
              "bytes":len(pcm),"rate":RATE}
    for suffix,data in ((".pcm",pcm),(".json",json.dumps(metadata,separators=(",",":")).encode())):
        target=root/(key(text)+suffix)
        temp=None
        try:
            with tempfile.NamedTemporaryFile(dir=root,delete=False,prefix=".verified-qwen-") as f:
                temp=Path(f.name);os.fchmod(f.fileno(),0o600);f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(temp,target)
        finally:
            if temp:temp.unlink(missing_ok=True)
    return cached_pcm(text,root=root) is not None
