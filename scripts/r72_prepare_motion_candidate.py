"""Mac-only single-motion transcoder and DFSP verifier (no connected hardware).

Input is an explicitly imported private video/GIF, output is a *candidate*
240x240 8fps RGB565+A8 zlib key/delta DFSP asset. This cannot bypass the
ESP32 firmware's current 35-ID allowlist. Writes stay in owner-only Mac path.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Deepseek-live/motion-library"
FILES=ROOT/"imports"
BUILD=ROOT/"candidates"
ID=re.compile(r"u[a-f0-9]{12}\Z")
EXT={"gif","mp4","mov","webm"}
FPS=8
SIDE=240
FRAME_BYTES=SIDE*SIDE*4
RAW_BYTES=SIDE*SIDE*3
HEADER=struct.Struct("<4sBHHBH")
PACKET=struct.Struct("<BI")
MAX_COMPRESSED=65536
MAX_FRAMES=80
MAX_SOURCE_BYTES=30_000_000

class ConversionError(ValueError):pass

def strict_file(path:Path,allowed:Path):
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(allowed.resolve()):
        raise ConversionError("untrusted_source_path")
    size=path.stat().st_size
    if not 500<size<=MAX_SOURCE_BYTES:raise ConversionError("source_size_exceeds_policy")

def pixel565a8(rgba:bytes)->bytes:
    if len(rgba)!=FRAME_BYTES:raise ConversionError("wrong_rgba_length")
    out=bytearray(RAW_BYTES)
    for i in range(SIDE*SIDE):
        j=i*4; k=i*3
        r,g,b,a=rgba[j:j+4]
        rgb=((r&0xf8)<<8)|((g&0xfc)<<3)|(b>>3)
        out[k]=rgb&255;out[k+1]=rgb>>8;out[k+2]=a
    return bytes(out)

def encode(frames:list[bytes],level=6)->tuple[bytes,int]:
    if not 1<=len(frames)<=MAX_FRAMES:raise ConversionError("invalid_frame_count")
    output=bytearray(HEADER.pack(b"DFSP",1,SIDE,SIDE,FPS,len(frames)))
    last=None;largest=0
    for idx,rgba in enumerate(frames):
        pixels=pixel565a8(rgba)
        whole=zlib.compress(pixels,level)
        kind=1;chosen=whole
        if idx%8 and last is not None:
            delta=bytes(a^b for a,b in zip(pixels,last))
            smaller=zlib.compress(delta,level)
            if len(smaller)<len(whole):kind=2;chosen=smaller
        if len(chosen)>MAX_COMPRESSED:
            raise ConversionError("frame_exceeds_device_64kb_decode_limit")
        output+=PACKET.pack(kind,len(chosen))+chosen
        largest=max(largest,len(chosen))
        last=pixels
    return bytes(output),largest

def verify(payload:bytes)->dict:
    if len(payload)<HEADER.size:raise ConversionError("truncated_dfsp")
    magic,version,w,h,fps,count=HEADER.unpack_from(payload)
    if (magic,version,w,h,fps)!=(b"DFSP",1,SIDE,SIDE,FPS):
        raise ConversionError("invalid_dfsp_header")
    if not 1<=count<=MAX_FRAMES:raise ConversionError("invalid_dfsp_count")
    offset=HEADER.size;prev=None;largest=0
    for index in range(count):
        if offset+PACKET.size>len(payload):raise ConversionError("truncated_packet")
        kind,length=PACKET.unpack_from(payload,offset);offset+=PACKET.size
        if not 1<=length<=MAX_COMPRESSED or offset+length>len(payload):
            raise ConversionError("invalid_frame_packet")
        if kind not in (1,2) or (index==0 and kind!=1):
            raise ConversionError("invalid_frame_kind")
        try:
            inflator=zlib.decompressobj()
            raw=inflator.decompress(payload[offset:offset+length],RAW_BYTES+1)
        except zlib.error as exc:raise ConversionError("invalid_frame_zlib") from exc
        offset+=length
        if (len(raw)!=RAW_BYTES or not inflator.eof or inflator.unconsumed_tail
            or inflator.unused_data):
            raise ConversionError("invalid_or_unbounded_frame_output")
        prev=bytes(a^b for a,b in zip(raw,prev)) if kind==2 else raw
        largest=max(largest,length)
    if offset!=len(payload):raise ConversionError("trailing_bytes")
    return {"frames":count,"fps":fps,"dimensions":"240x240",
            "max_compressed_packet":largest,"bytes":len(payload),
            "sha256":hashlib.sha256(payload).hexdigest(),"verified":True}

def convert(ident:str,*,root:Path=ROOT,level:int=6,mode:str="contain",ffmpeg=None)->dict:
    if ID.fullmatch(ident) is None:raise ConversionError("invalid_candidate_id")
    if level not in (3,6,9) or mode not in ("contain","cover"):
        raise ConversionError("invalid_encode_parameters")
    imports=root/"imports"
    available=[imports/(ident+"."+ext) for ext in sorted(EXT)
               if (imports/(ident+"."+ext)).exists()]
    if len(available)!=1:raise ConversionError("missing_or_multiple_imports")
    src=available[0];strict_file(src,imports)
    target=root/"candidates"/(ident+".DFS")
    metadata=root/"candidates"/(ident+".json")
    if target.exists() or metadata.exists():raise ConversionError("candidate_exists_no_overwrite")
    exe=ffmpeg or shutil.which("ffmpeg")
    if not exe:raise ConversionError("ffmpeg_not_installed")
    fit=("decrease" if mode=="contain" else "increase")
    scale=f"scale={SIDE}:{SIDE}:force_original_aspect_ratio={fit}:flags=lanczos"
    position=(
       f"pad={SIDE}:{SIDE}:(ow-iw)/2:(oh-ih)/2:color=black@0"
       if mode=="contain" else f"crop={SIDE}:{SIDE}"
    )
    filt=f"fps={FPS},{scale},{position},format=rgba"
    # Time and output bounded: no shell, no network sources, no arbitrary path.
    # Limit to 10s = 80 frames; cap output independently.
    command=[str(exe),"-nostdin","-hide_banner","-loglevel","error",
             "-protocol_whitelist","file,pipe","-i",str(src),
             "-vf",filt,"-frames:v",str(MAX_FRAMES),
             "-f","rawvideo","-pix_fmt","rgba","pipe:1"]
    try:
        proc=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             timeout=80,check=False)
    except subprocess.TimeoutExpired as exc:
        raise ConversionError("video_decode_timed_out") from exc
    if proc.returncode or not proc.stdout or len(proc.stdout)>FRAME_BYTES*MAX_FRAMES:
        raise ConversionError("ffmpeg_decode_failed")
    if len(proc.stdout)%FRAME_BYTES:raise ConversionError("incomplete_decoded_rgba")
    decoded=[proc.stdout[i:i+FRAME_BYTES]
             for i in range(0,len(proc.stdout),FRAME_BYTES)]
    payload,peak=encode(decoded,level=level)
    receipt=verify(payload)
    if receipt["max_compressed_packet"]!=peak:raise ConversionError("encoder_verifier_mismatch")
    receipt.update(schema=1,id=ident,source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                   source_extension=src.suffix.lower(),role="unassigned",fit_mode=mode,
                   level=level,status="local_candidate_uninstalled",
                   esp32_written=False,sd_written=False,
                   hardware_allowlist_updated=False)
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if target.parent.is_symlink():raise ConversionError("unsafe_candidate_directory")
    # No replace even if another worker races us.
    try:
        with target.open("xb") as f:
            os.fchmod(f.fileno(),0o600);f.write(payload);f.flush();os.fsync(f.fileno())
        with metadata.open("x",encoding="utf8") as f:
            os.fchmod(f.fileno(),0o600)
            json.dump(receipt,f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return receipt

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--id",required=True)
    p.add_argument("--mode",choices=("contain","cover"),default="contain")
    p.add_argument("--level",type=int,choices=(3,6,9),default=6)
    args=p.parse_args()
    try:print(json.dumps(convert(args.id,mode=args.mode,level=args.level),ensure_ascii=False))
    except (ConversionError,OSError) as exc:
        print(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False))
        raise SystemExit(2)
if __name__=="__main__":main()
