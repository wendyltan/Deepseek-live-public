#!/usr/bin/env python3
"""Generate original, deterministic firmware bootstrap assets.

This is intentionally separate from existing user voice/animation assets.
Produces a simple geometric DFSP fallback and two synthesized chimes so a
fresh ESP-IDF checkout can build without private audio or 3rd-party artwork.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
import struct
import wave
import zlib
from pathlib import Path

WIDTH=HEIGHT=240
FPS=8
FRAMES=8
RATE=24000


def create_chime(duration:float, notes:tuple[tuple[float,float,float],...])->bytes:
    samples=int(round(duration*RATE))
    pcm=bytearray(samples*2)
    for i in range(samples):
        t=i/RATE
        value=0.0
        for start,freq,length in notes:
            age=t-start
            if 0<=age<length:
                env=min(1,age/0.025)*max(0,1-age/length)**2
                value+=0.18*env*(math.sin(2*math.pi*freq*age)+0.15*math.sin(4*math.pi*freq*age))
        scaled=int(max(-1,min(1,value))*32767)
        struct.pack_into('<h',pcm,i*2,scaled)
    out=io.BytesIO()
    with wave.open(out,'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out.getvalue()


def fallback_animation()->bytes:
    header=struct.pack('<4sBHHBH',b'DFSP',1,WIDTH,HEIGHT,FPS,FRAMES)
    out=bytearray(header)
    for frame_index in range(FRAMES):
        pixels=bytearray(WIDTH*HEIGHT*3)
        radius=40 + int(4*math.sin(frame_index*math.pi/4))
        for y in range(HEIGHT):
            for x in range(WIDTH):
                distance=(x-120)**2+(y-120)**2
                if distance>radius*radius:
                    continue
                alpha=255
                # Original minimal indicator geometry, not an adapted character.
                r,g,b=(58,136,189) if abs(x-120)>4 and abs(y-120)>4 else (87,175,213)
                rgb565=((r&0xf8)<<8)|((g&0xfc)<<3)|(b>>3)
                pos=(y*WIDTH+x)*3
                pixels[pos:pos+3]=bytes((rgb565&255,rgb565>>8,alpha))
        block=zlib.compress(bytes(pixels),6)
        out.extend(struct.pack('<BI',1,len(block)))
        out.extend(block)
    return bytes(out)


def assets()->dict[str,bytes]:
    return {
        'ANIM.DFS':fallback_animation(),
        'VOICE.WAV':create_chime(4.64,((0.15,523.25,0.30),(0.52,659.25,0.35),(0.95,783.99,0.55))),
        'R185_GREETING.WAV':create_chime(1.60,((0.12,659.25,0.22),(0.38,783.99,0.30))),
    }


def generate(destination:Path)->dict:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('destination_must_not_exist')
    destination.mkdir(parents=True,exist_ok=False)
    receipt={}
    try:
        for name,data in assets().items():
            p=destination/name
            p.write_bytes(data)
            receipt[name]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
        return receipt
    except Exception:
        for p in destination.iterdir():
            if p.is_file():p.unlink()
        destination.rmdir()
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destination',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps({'generated':generate(a.destination),
                      'asset_provenance':'Original programmatic tones and geometric fallback',
                      'identical_to_author_existing_media':False},
                      ensure_ascii=False,indent=2))


if __name__=='__main__':main()
