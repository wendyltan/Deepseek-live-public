"""Bounded DFSCREEN3 sliding windows; one verified serial owner only.

Groups up to 3 NEXT frames so the serial-jtag device never fills its ~4KiB
TX queue while host reads nothing. No USB open, no SD writes, no audio.
"""
from __future__ import annotations
import base64,binascii,re,time,zlib
from app.r133_screen_pull_protocol import ScreenPullError,START,CHUNK,READY
def pull_windowed(device,*,single_owner,phase,should_cancel,
                  window=3,clock=time.monotonic,timeout=75,on_progress=lambda *_:None):
    if not single_owner or phase!='idle':
        raise ScreenPullError('single_verified_idle_owner_required')
    if type(window)!=int or window<1 or window>3 or timeout<=0 or timeout>90:
        raise ScreenPullError('invalid_limits')
    stop=clock()+timeout
    def command(data):
        if should_cancel():raise ScreenPullError('voice_started_abort')
        raw=(data+'\n').encode('ascii')
        if device.write(raw)!=len(raw):raise ScreenPullError('incomplete_write')
    def receive():
        while clock()<stop:
            if should_cancel():raise ScreenPullError('voice_started_abort')
            line=device.readline()
            if not line:continue
            row=line.decode('ascii','replace').strip()
            if '@@DFVOICE3 BEGIN' in row or row.startswith('@@DFVOICE3 PCM '):
                # Return the *original* bytes for the still-live MIC receiver.
                # Merely aborting here would consume its physical BEGIN frame.
                if hasattr(device,'unread'):
                    device.unread(line)
                raise ScreenPullError('mic_has_priority')
            if row.startswith('@@DFSCREEN3 '):return row
        raise ScreenPullError('frame_capture_deadline')
    try:
        command('@@DFSCREEN3 CAPS');device.flush()
        if receive()!=READY:raise ScreenPullError('no_exact_caps')
        command('@@DFSCREEN3 START');device.flush()
        marker=START.fullmatch(receive())
        if not marker:raise ScreenPullError('invalid_header')
        want_crc=int(marker[1],16)
        pixels=bytearray(460800)
        for base in range(0,600,window):
            indices=range(base,min(600,base+window))
            for i in indices:command(f'@@DFSCREEN3 NEXT index={i}')
            device.flush()
            for i in indices:
                row=receive()
                match=CHUNK.fullmatch(row)
                if not match or int(match[1])!=i:
                    raise ScreenPullError(f'out_of_order_or_missing_{i}')
                try:raw=base64.b64decode(match[2],validate=True)
                except (binascii.Error,ValueError) as e:
                    raise ScreenPullError('bad_base64') from e
                if len(raw)!=768:raise ScreenPullError('short_chunk')
                pixels[i*768:(i+1)*768]=raw
            if base%60==0:
                on_progress(min(600,base+window),round(clock()-(stop-timeout),2))
        if receive()!='@@DFSCREEN3 END count=600':raise ScreenPullError('no_final_frame_receipt')
        crc=zlib.crc32(pixels)
        if crc!=want_crc:raise ScreenPullError('crc_mismatch')
        return bytes(pixels),f'{crc:08x}'
    except (ScreenPullError,OSError):
        try:
            # Owner sends its own abort. Never opens a second serial session.
            device.write(b'@@DFSCREEN3 ABORT\n');device.flush()
        except OSError:pass
        raise
