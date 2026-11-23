"""ESP32-source-only wake/state event gate (protocol candidate, NOT H10 support).

Only an explicit future device-side wake detector can emit a wake event.
No Mac audio capture, Whisper transcript or UI text can manufacture one.
A handshake grants no access to DSH; a user utterance must still be verified.
"""
from __future__ import annotations
import re
import time

READY=re.compile(r'^@@DFWAKE1 READY engine=(wakenet9|wakenet10|multinet6|multinet7) model=([a-z0-9_]{3,40}) boot=([0-9a-f]{16})$')
WAKE=re.compile(r'^@@DFWAKE1 DETECTED boot=([0-9a-f]{16}) seq=(\d{1,9}) model=([a-z0-9_]{3,40})$')
PHASES=frozenset(('idle','listening','transcribing','thinking','tool_pending',
                  'approval_pending','voice_generating','speaking','error'))
STATE=re.compile(r'^@@DFSTATE1 APPLIED seq=(\d{1,9}) phase=([a-z_]{2,24})$')
MOTION=re.compile(r'^@@DFMOTION1 READY profile=selected35 store=sd$')

class DeviceEventError(RuntimeError):pass

class PhysicalWakeGate:
    def __init__(self, *, clock=time.monotonic, cooldown=2):
        self.clock=clock;self.cooldown=cooldown
        self.boot=None;self.model=None;self.seq=0;self.last=-cooldown
        self.events=0
    def bind(self, raw:str):
        match=READY.fullmatch(raw.strip())
        if not match:raise DeviceEventError('UNVERIFIED_DEVICE_WAKE_CAPABILITY')
        engine,model,boot=match.groups()
        self.boot=boot;self.model=model;self.seq=0;self.last=-self.cooldown
        self.events=0
        return {'engine':engine,'model':model,'boot':boot}
    def accept(self,raw:str):
        if self.boot is None:
            raise DeviceEventError('DEVICE_WAKE_NOT_BOUND')
        match=WAKE.fullmatch(raw.strip())
        if not match:
            raise DeviceEventError('DEVICE_WAKE_EVENT_MALFORMED')
        boot,seq,model=match.groups();seq=int(seq)
        if boot!=self.boot or model!=self.model:
            raise DeviceEventError('DEVICE_WAKE_WRONG_BOOT_OR_MODEL')
        if seq<=self.seq:
            raise DeviceEventError('DEVICE_WAKE_DUPLICATE_OR_REPLAY')
        now=self.clock()
        if now-self.last<self.cooldown:
            raise DeviceEventError('DEVICE_WAKE_COOLDOWN')
        self.seq=seq;self.last=now;self.events+=1
        return {'source':'esp32_wakenet_device_report','model':model,'seq':seq,
                'allow_model_request':False,'allow_mic_capture':True}

class DeviceStateBridge:
    """Hardware phase reporting is independent from 35-motion storage.

    H10 has neither capability: callers MUST refuse to transmit to H10.
    Even with phase ACK, a motion is NOT on screen until SD renderer ACKs.
    """
    def __init__(self):
        self.supports_state=False;self.supports_selected35=False;self.next_seq=1
    def bind(self,reported:str):
        if reported.strip()=='@@DFSTATE1 READY phases=9':
            self.supports_state=True
        elif MOTION.fullmatch(reported.strip()):
            self.supports_selected35=True
        else:raise DeviceEventError('DEVICE_STATE_CAPABILITY_UNVERIFIED')
    def state_message(self,phase:str):
        if not self.supports_state:
            raise DeviceEventError('DEVICE_STATE_PROTOCOL_NOT_SUPPORTED')
        if phase not in PHASES:
            raise DeviceEventError('DEVICE_STATE_UNKNOWN_PHASE')
        seq=self.next_seq;self.next_seq+=1
        return seq,f'@@DFSTATE1 SET seq={seq} phase={phase}\n'.encode('ascii')
    def verify_applied(self,reply:str,seq:int,phase:str):
        match=STATE.fullmatch(reply.strip())
        if not match or (int(match[1]),match[2])!=(seq,phase):
            raise DeviceEventError('DEVICE_STATE_ACK_MISMATCH')
        return {'phase':phase,'display_ack':True,'motion_ack':False}
    def require_motion(self):
        if not self.supports_selected35:
            raise DeviceEventError('SELECTED35_NOT_ON_DEVICE_SD')



def probe_device_wake(port,*,clock=time.monotonic,timeout=3.0):
    """Opt-in capability probe of ESP32. H10 must fail closed.

    Never read a Mac input device and never activate audio/model generation.
    """
    gate=PhysicalWakeGate(clock=clock)
    sent=port.write(b'@@DFWAKE1 CAPS\n')
    if sent!=len(b'@@DFWAKE1 CAPS\n'):
        raise DeviceEventError('DEVICE_WAKE_PROBE_WRITE_FAILED')
    port.flush()
    deadline=clock()+timeout
    while clock()<deadline:
        row=port.readline().decode('ascii','replace').strip()
        if row.startswith('@@DFWAKE1 READY '):
            gate.bind(row)
            return gate
        if row.startswith('@@DFWAKE1 UNAVAILABLE'):
            raise DeviceEventError('DEVICE_WAKE_MODEL_NOT_INSTALLED')
        if 'Guru Meditation' in row or 'Rebooting...' in row:
            raise DeviceEventError('DEVICE_REBOOTED_DURING_WAKE_PROBE')
    raise DeviceEventError('ESP32_WAKE_CAPABILITY_NOT_AVAILABLE')


def wait_for_device_wake(port,gate,*,clock=time.monotonic,timeout=None,
                         on_heartbeat=None,heartbeat_seconds=8):
    """Passive wait reads ESP32 protocol ONLY, never Mac audio or model.

    A caller may install a free, verified official DSH /session heartbeat so
    the native UI does not falsely disconnect while the ESP32 is idle.
    """
    if gate.boot is None:raise DeviceEventError('DEVICE_WAKE_NOT_BOUND')
    if timeout is not None and not (0<timeout<=3600):
        raise DeviceEventError('DEVICE_WAKE_TIMEOUT_INVALID')
    deadline=clock()+timeout if timeout is not None else None
    next_heartbeat=clock()+heartbeat_seconds
    while deadline is None or clock()<deadline:
        line=port.readline().decode('ascii','replace').strip()
        if line.startswith('@@DFWAKE1 DETECTED '):
            return gate.accept(line)
        if 'Guru Meditation' in line or 'Rebooting...' in line:
            raise DeviceEventError('DEVICE_REBOOTED_DURING_WAKE_WAIT')
        if line.startswith('@@DFWAKE1 READY '):
            # A new boot must not inherit a previously verified wake session.
            raise DeviceEventError('DEVICE_WAKE_CAPABILITY_RESTARTED')
        if on_heartbeat is not None and clock()>=next_heartbeat:
            on_heartbeat()
            next_heartbeat=clock()+heartbeat_seconds
    raise DeviceEventError('DEVICE_WAKE_WAIT_TIMEOUT')
