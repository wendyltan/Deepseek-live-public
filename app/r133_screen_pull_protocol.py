"""Owner-only DFSCREEN3 decoder; no open/close of USB port in this module.

Never publishes a partial screenshot. A live voice event aborts the request.
Call only from the existing ESP32 serial owner after a fresh idle receipt.
"""
from __future__ import annotations
import base64,binascii,re,time,zlib

class ScreenPullError(RuntimeError):pass
START=re.compile(r'^@@DFSCREEN3 BEGIN bytes=460800 chunks=600 crc32=([0-9a-f]{8})$')
CHUNK=re.compile(r'^@@DFSCREEN3 DATA index=(\d{1,3}) b64=([A-Za-z0-9+/=]{1024})$')
READY='@@DFSCREEN3 READY width=480 height=480 format=rgb565 chunks=600 pull=1'

def pull(device,*,confirmed_owner:bool,phase:str,should_cancel,
         monotonic=time.monotonic,max_seconds:float=20.0,on_chunk=None):
    if not confirmed_owner or phase!='idle':
        raise ScreenPullError('not_verified_single_usb_owner_and_idle')
    # Longer windows are diagnostic only; production should use <=30s and
    # never claim continuous screen streaming without voice-owner arbitration.
    if max_seconds<=0 or max_seconds>150:
        raise ScreenPullError('unbounded_request')
    deadline=monotonic()+max_seconds
    def command(text):
        wire=(text+'\n').encode('ascii')
        if device.write(wire)!=len(wire):raise ScreenPullError('usb_short_write')
        if hasattr(device,'flush'):device.flush()
    def receive():
        while monotonic()<deadline:
            if should_cancel():raise ScreenPullError('voice_takes_priority')
            raw=device.readline()
            if raw:
                s=raw.decode('ascii','replace').strip()
                if s.startswith('@@DFSCREEN3 '):return s
                if s.startswith('@@DFVOICE3 '):raise ScreenPullError('mic_event_not_screen_frame')
        raise ScreenPullError('screen_deadline')
    started=False
    try:
        command('@@DFSCREEN3 CAPS')
        if receive()!=READY:raise ScreenPullError('missing_exact_screen_caps')
        command('@@DFSCREEN3 START')
        info=START.fullmatch(receive())
        if not info:raise ScreenPullError('missing_start_frame')
        expected_crc=int(info[1],16)
        frame=bytearray()
        for seq in range(600):
            if should_cancel():raise ScreenPullError('voice_takes_priority')
            command(f'@@DFSCREEN3 NEXT index={seq}')
            packet=CHUNK.fullmatch(receive())
            if not packet or int(packet[1])!=seq:
                raise ScreenPullError('missing_or_out_of_sequence_chunk')
            try:raw=base64.b64decode(packet[2],validate=True)
            except (ValueError,binascii.Error) as e:raise ScreenPullError('invalid_chunk_base64') from e
            if len(raw)!=768:raise ScreenPullError('short_chunk')
            frame.extend(raw)
            if on_chunk is not None and (seq+1)%25==0:
                on_chunk(seq+1,monotonic())
        if receive()!='@@DFSCREEN3 END count=600':raise ScreenPullError('missing_final_receipt')
        if len(frame)!=460800 or zlib.crc32(frame)!=expected_crc:
            raise ScreenPullError('pixel_crc_mismatch')
        return bytes(frame),f'{expected_crc:08x}'
    except ScreenPullError:
        try:command('@@DFSCREEN3 ABORT')
        except (OSError,ScreenPullError):pass
        raise
