"""Single-use Mac screenshot request consumed by current verified USB owner.

Mic's physical BEGIN preempts transfer; OwnedLinePort pushes it back to the
existing H28 microphone receiver. Never opens another USB port or records mic.
"""
import json,stat,time
from pathlib import Path
from app.r135_screen_pull_windowed import pull_windowed
from app.r133_screen_pull_protocol import ScreenPullError
from app.r92_lvgl_frame_protocol import persist

ROOT=Path.home()/'Library/Application Support/Deepseek-live'
REQUEST=ROOT/'companion-native/screen-single-request.json'
OUTPUT=ROOT/'display-diagnostics/r92-live'

def consume_screen_request(port,native,*,target=REQUEST,outdir=OUTPUT,
                           clock=time.time,log=print,pull=pull_windowed):
    if not target.is_file() or target.is_symlink():return False
    try:
        meta=target.stat()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_size>512 or
            meta.st_size<65 or meta.st_mode&0o077):
            log('R136_SCREEN_REJECT_UNSAFE_LOCAL_REQUEST')
            return False
        request=json.loads(target.read_text(encoding='utf-8'))
        target.unlink()
    except (OSError,ValueError,UnicodeError):
        log('R136_SCREEN_INVALID_LOCAL_REQUEST')
        return False
    if (not isinstance(request,dict) or request.get('schema')!=1 or
        request.get('capture')!='single' or
        request.get('session_id')!=native.projector.session_id or
        type(request.get('at')) not in (int,float) or
        not 0<=clock()-request['at']<=35 or
        not native.bound or native.projector.turn_id is not None):
        log('R136_SCREEN_REQUEST_EXPIRED_OR_WRONG_SESSION')
        return False
    if native.projector.state.get('phase') not in ('idle','standby'):
        log('R136_SCREEN_REFUSED_ACTIVE_AUDIO_PHASE')
        return False
    native.projector.state['screen_capture_status']='capturing'
    native.projector.write()
    try:
        pixels,crc=pull(port,single_owner=True,phase='idle',
                        should_cancel=lambda:not native.bound,
                        window=3,timeout=22)
        info=persist(pixels,outdir,board_caps_verified=True)
        if info['crc32']!=crc:raise ScreenPullError('persist_crc_disagreed')
        native.projector.state['screen_capture_status']='complete'
        native.projector.state['screen_capture_crc32']=crc
        native.projector.write()
        log('R136_SCREEN_USB_OWNER_PIXEL_VERIFIED crc32='+crc)
        return True
    except (OSError,ValueError,RuntimeError) as e:
        native.projector.state['screen_capture_status']='aborted_or_unverified'
        native.projector.write()
        log('R136_SCREEN_USB_OWNER_SAFE_ABORT '+type(e).__name__+' '+str(e)[:70])
        return False
