"""R254: read real WakeNet/codec state before clearing stale UI on reconnect.

State-only, same serial owner, no microphone trigger/recording, model call,
volume, SD animation selection, device reboot or firmware write.
"""
from __future__ import annotations
import re
import time

DIAG=re.compile(
    r'^@@DFWAKE3 DIAG can_listen=([01]) wake_mic=([01]) reading=([01]) '
    r'capture=([01]) speak=([01]) pcm2=([01]) h10=([01]) '
    r'transfer=([01]) phase=([a-z_]{2,24})$')
STATE=re.compile(
    r'^@@DFWAKE3 STATE model=(?:wn9_hilexin|mn(?:4q8|5q8)_nihaodafeiyu) ready=1 enabled=1 '
    r'source=esp32_mic commands=0 boot=[0-9a-f]{16}$')
STALE=frozenset(('voice_generating','thinking','transcribing','tool_pending','speaking'))

def read_wake_status(port, *, duration=2.5, clock=time.monotonic):
    if not 0.2<=duration<=5.0:raise ValueError('r254_bad_duration')
    frame=b'@@DFWAKE3 STATUS\n'
    if port.write(frame)!=len(frame):raise OSError('r254_status_write_short')
    port.flush()
    deadline=clock()+duration
    partial=b'';confirmed=False;diag=None
    while clock()<deadline:
        raw=port.readline()
        if not raw:continue
        partial+=raw
        if len(partial)>1536:partial=b'';continue
        if b'\n' not in partial:continue
        row,partial=partial.split(b'\n',1)
        text=row.decode('ascii','replace').strip()
        index=text.find('@@DFWAKE3 ')
        if index<0:continue
        text=text[index:]
        if STATE.fullmatch(text):confirmed=True
        match=DIAG.fullmatch(text)
        if match:diag=tuple(match.groups())
        if confirmed and diag:
            keys=('can_listen','wake_mic','reading','capture','speak',
                  'pcm2','h10','transfer','phase')
            return dict(zip(keys,tuple(map(int,diag[:8]))+(diag[8],)))
    raise RuntimeError('r254_unverified_wake_status')

def recover_stale_board_idle(port,motion_link,*,output=print):
    """Repair ONLY an authenticated idle transport with no physical audio IO."""
    if motion_link is None or not getattr(motion_link,'enabled',False):
        return {'recovered':False,'reason':'link_not_probed'}
    before=read_wake_status(port)
    if before['can_listen']==1:
        return {'recovered':False,'reason':'already_listening'}
    if any(before[key] for key in ('capture','speak','pcm2','h10','transfer')):
        return {'recovered':False,'reason':'real_audio_busy'}
    if before['phase'] not in STALE:
        return {'recovered':False,'reason':'phase_not_stale'}
    ack=motion_link.apply_phase_only('idle')
    if ack.get('display_ack') is not True:raise RuntimeError('r254_no_board_idle_ack')
    # WakeNet mic claims asynchronously; observe actual read permission,
    # not just the display phase command receipt.
    last=None
    for _ in range(4):
        now=read_wake_status(port,duration=1.5)
        last=now
        if now['can_listen']==1 and now['phase']=='idle':
            output('R254_STARTUP_STALE_PHASE_REARM_VERIFIED')
            return {'recovered':True,'reason':'stale_phase_cleared'}
        time.sleep(.15)
    raise RuntimeError('r254_board_still_not_listening_'+str(last['phase'] if last else 'unknown'))
