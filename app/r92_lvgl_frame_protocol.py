"""Strict RGB565 480-square physical ESP32 LVGL-software snapshot.

Does not claim OLED optical proof. Reject stale/partial/missing/replayed
chunks and unsuitable source. No real serial side effects in this module.
"""
from __future__ import annotations
import base64,binascii,json,os,re,struct,time,zlib
from pathlib import Path

W=H=480
RAW_BYTES=W*H*2
CHUNK_BYTES=768
COUNT=RAW_BYTES//CHUNK_BYTES
CAPS='@@DFSCREEN2 READY width=480 height=480 format=rgb565 source=lvgl_snapshot'
HEADER=re.compile(r'^@@DFSCREEN2 BEGIN source=lvgl_snapshot width=480 height=480 format=rgb565 bytes=460800 chunks=600 crc32=([0-9a-f]{8})$')
CHUNK=re.compile(r'^@@DFSCREEN2 DATA index=([0-9]{1,3}) b64=([A-Za-z0-9+/]{1024})$')
END='@@DFSCREEN2 END count=600'

class ScreenProtocolError(RuntimeError): pass

def decode(lines:list[str])->bytes:
    if len(lines)!=COUNT+2:raise ScreenProtocolError('screen_packet_count_invalid')
    start=HEADER.fullmatch(lines[0].strip())
    if not start or lines[-1].strip()!=END:
        raise ScreenProtocolError('screen_header_or_tail_invalid')
    raw=bytearray(RAW_BYTES)
    for idx,line in enumerate(lines[1:-1]):
        match=CHUNK.fullmatch(line.strip())
        if not match or int(match[1])!=idx:
            raise ScreenProtocolError('screen_chunk_order_invalid')
        try:piece=base64.b64decode(match[2],validate=True)
        except (binascii.Error,ValueError) as e:
            raise ScreenProtocolError('screen_chunk_encoding_invalid') from e
        if len(piece)!=CHUNK_BYTES:raise ScreenProtocolError('screen_chunk_size_invalid')
        raw[idx*CHUNK_BYTES:(idx+1)*CHUNK_BYTES]=piece
    if zlib.crc32(raw)!=int(start[1],16):
        raise ScreenProtocolError('screen_crc_mismatch')
    return bytes(raw)

def png565(raw:bytes)->bytes:
    if len(raw)!=RAW_BYTES:raise ScreenProtocolError('screen_raw_size_invalid')
    pixels=bytearray((W*3+1)*H)
    for y in range(H):
        out=y*(W*3+1);pixels[out]=0
        for x in range(W):
            i=(y*W+x)*2
            col=raw[i]|raw[i+1]<<8
            j=out+1+x*3
            pixels[j]=(col>>11 &31)*255//31
            pixels[j+1]=(col>>5 &63)*255//63
            pixels[j+2]=(col&31)*255//31
    def block(tag,data):
        return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data))
    return b'\x89PNG\r\n\x1a\n'+block(b'IHDR',struct.pack('>IIBBBBB',W,H,8,2,0,0,0))+block(b'IDAT',zlib.compress(pixels,5))+block(b'IEND',b'')

def persist(raw:bytes,folder:Path,*,board_caps_verified:bool)->dict:
    if not board_caps_verified:raise ScreenProtocolError('board_caps_unverified')
    if folder.is_symlink():raise ScreenProtocolError('unsafe_snapshot_folder')
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    picture=folder/'esp32-rendered-screen.png'
    meta=folder/'esp32-rendered-screen.json'
    if picture.is_symlink() or meta.is_symlink():
        raise ScreenProtocolError('unsafe_snapshot_output')
    stamp=time.time()
    information={
        'schema':2,'source':'physical_esp32_lvgl_snapshot_over_usb',
        'width':W,'height':H,'bytes':RAW_BYTES,
        'captured_at_unix':round(stamp,3),
        'crc32':f'{zlib.crc32(raw):08x}',
        'esp32_pixel_data_received':True,
        'entire_lvgl_page_rendered':True,
        'optical_amoled_panel_verified':False,
        'camera_frame_available':False
    }
    for path,content in (
        (picture,png565(raw)),
        (meta,json.dumps(information,ensure_ascii=False).encode('utf-8'))):
        tmp=path.with_suffix(path.suffix+'.writing')
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write(content)
                out.flush();os.fsync(out.fileno())
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        os.replace(tmp,path)
    return information
