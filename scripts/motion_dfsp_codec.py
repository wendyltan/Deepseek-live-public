#!/usr/bin/env python3
"""Portable DFSP v1 codec used by the ESP32 motion-library converter."""
from __future__ import annotations

import shutil
import struct
import subprocess
import zlib
from pathlib import Path

FPS=8
WIDTH,HEIGHT=640,360
FRAME_RGBA_BYTES=WIDTH*HEIGHT*4
FILE_HEADER=struct.Struct("<4sBHHBH")
FRAME_HEADER=struct.Struct("<BI")


def decode_frames(path: Path):
    exe=shutil.which("ffmpeg")
    if exe is None:
        raise RuntimeError("ffmpeg is required")
    result=subprocess.run([exe,"-hide_banner","-loglevel","error",
                           "-c:v","libvpx-vp9","-i",str(path),
                           "-vf","fps=8","-pix_fmt","rgba",
                           "-f","rawvideo","-"],
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    if not result.stdout or len(result.stdout)%FRAME_RGBA_BYTES:
        raise ValueError(f"bad_webm_rgba_frames:{path.name}")
    for p in range(0,len(result.stdout),FRAME_RGBA_BYTES):
        yield result.stdout[p:p+FRAME_RGBA_BYTES]


def calculate_box(frames):
    from PIL import Image
    xmin,ymin,xmax,ymax=WIDTH,HEIGHT,0,0
    for data in frames:
        alpha=Image.frombytes("RGBA",(WIDTH,HEIGHT),data).getchannel("A")
        box=alpha.point(lambda a:255 if a>8 else 0).getbbox()
        if box:
            xmin=min(xmin,box[0])
            ymin=min(ymin,box[1])
            xmax=max(xmax,box[2])
            ymax=max(ymax,box[3])
    if xmax<=xmin or ymax<=ymin:
        raise ValueError("source_no_visible_pixels")
    return max(0,xmin-8),max(0,ymin-8),min(WIDTH,xmax+8),min(HEIGHT,ymax+8)


def rgba_to_rgb565_alpha(image):
    rgba=image.tobytes()
    out=bytearray((len(rgba)//4)*3)
    for j in range(0,len(rgba),4):
        r,g,b,a=rgba[j:j+4]
        rgb565=((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)
        k=(j//4)*3
        out[k:k+3]=bytes((rgb565&255,rgb565>>8,a))
    return bytes(out)


def rescale_sprite(raw:bytes,bbox,size:int):
    from PIL import Image
    image=Image.frombytes("RGBA",(WIDTH,HEIGHT),raw).crop(bbox)
    image.thumbnail((size,size),Image.Resampling.LANCZOS)
    canvas=Image.new("RGBA",(size,size),(0,0,0,0))
    canvas.alpha_composite(image,((size-image.width)//2,size-image.height))
    return rgba_to_rgb565_alpha(canvas)


def decode_dfsp_frames(path:Path):
    stream=path.read_bytes()
    if len(stream)<FILE_HEADER.size:
        raise ValueError("dfsp_header_truncated")
    magic,version,w,h,fps,count=FILE_HEADER.unpack_from(stream)
    if (magic,version,fps)!=(b"DFSP",1,FPS) or not(1<=count<=100) or w!=h:
        raise ValueError("dfsp_bad_header")
    pos=FILE_HEADER.size
    previous=None
    for _ in range(count):
        if pos+FRAME_HEADER.size>len(stream):
            raise ValueError("dfsp_frame_header_truncated")
        kind,length=FRAME_HEADER.unpack_from(stream,pos)
        pos+=FRAME_HEADER.size
        raw_size=w*h*3
        if kind not in (1,2) or not(0<length<=raw_size+max(64,raw_size//100)) or pos+length>len(stream):
            raise ValueError("dfsp_invalid_block_size")
        payload=zlib.decompress(stream[pos:pos+length])
        pos+=length
        if len(payload)!=raw_size:
            raise ValueError("dfsp_frame_size_mismatch")
        if kind==2:
            if previous is None:
                raise ValueError("dfsp_orphan_delta")
            payload=bytes(x^y for x,y in zip(payload,previous))
        previous=payload
        yield w,h,payload
    if pos!=len(stream):
        raise ValueError("dfsp_trailing_bytes")


def rgb565a8_to_rgb_image(raw:bytes,size:int=240,bg:tuple[int,int,int]=(238,247,255)):
    from PIL import Image
    out=bytearray(size*size*3)
    br,bg_g,bb=bg
    p=0
    for i in range(0,len(raw),3):
        c=raw[i]|(raw[i+1]<<8)
        a=raw[i+2]
        r=((c>>11)&31)*255//31
        g=((c>>5)&63)*255//63
        b=(c&31)*255//31
        out[p]=(r*a+br*(255-a)+127)//255
        out[p+1]=(g*a+bg_g*(255-a)+127)//255
        out[p+2]=(b*a+bb*(255-a)+127)//255
        p+=3
    return Image.frombytes("RGB",(size,size),bytes(out))


def verify_container(path:Path)->int:
    return sum(1 for _ in decode_dfsp_frames(path))
