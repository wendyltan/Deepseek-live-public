"""ESP32 onboard-mic push-to-talk: bounded release-framed Voice3 USB input.

Source must be the real selected ESP32 USB port after a real device capability
receipt; no Mac/iPhone/USB external microphone, simulated event or paid call.
Caller arms microphone through existing H8 verified ARM handshake; this module
handles physical Voice3 BEGIN/PCM/END whether from touch or a locally
verified WakeNet event. Neither event alone can submit a model request.
"""
from __future__ import annotations
import base64
import binascii
import re
import time

RATE=16000
MAX_FRAMES=1000
MIC_BLOCK_BYTES=640
BEGIN='@@DFVOICE3 BEGIN rate=16000 max_frames=1000'
CAPS='@@DFVOICE3 READY source=esp32_mic trigger=hold_release max_frames=1000'
CAPS_TOGGLE='@@DFVOICE3 READY source=esp32_mic trigger=tap_toggle max_frames=1000'
PCM=re.compile(r'^@@DFVOICE3 PCM (\d{1,4}) ([A-Za-z0-9+/=]{4,1400})$')
END=re.compile(r'^@@DFVOICE3 END frames=(\d{1,4}) samples=(\d{1,7}) reason=(released|limit|toggled)$')
VISUAL=re.compile(r'^@@DF(TOUCH|IDLE)1 APPLIED id=(m\d{3}) frame=1$')
WAKE_EVENT='@@DFWAKE2 DETECTED id=ni_hao_da_fei_yu'

class PhysicalHoldCaptureError(RuntimeError):pass

def peel(raw:bytes)->str:
    line=raw.decode('ascii','replace').strip()
    if line.startswith('@@DFVOICE3 '):return line
    if line.startswith(('I (','W (','E (','D (')) and line.count('@@DFVOICE3 ')==1:
        return line[line.index('@@DFVOICE3 '):]
    return ''

def probe(device,*,clock=time.monotonic,timeout=8):
    command=b'@@DFVOICE3 CAPS\n'
    if device.write(command)!=len(command):raise PhysicalHoldCaptureError('hold_caps_usb_partial')
    device.flush();deadline=clock()+timeout
    while clock()<deadline:
        text=peel(device.readline())
        if text in (CAPS,CAPS_TOGGLE):return True
        if text.startswith('@@DFVOICE3 '):raise PhysicalHoldCaptureError('board_hold_capability_invalid')
    raise PhysicalHoldCaptureError('board_does_not_support_release_to_send')

def receive(device,*,clock=time.monotonic,limit_seconds=180,output=print,
            on_physical_frame=None,idle_handler=None,
            wake_gate=None,on_capture_origin=None)->bytes:
    begun=False;rows=0;pcm=bytearray();deadline=clock()+limit_seconds
    stream_deadline=None
    pending_wake_seq=None
    pending_wake_at=None
    # R239: same verified USB owner can poll the read-only board wake flags
    # while waiting for an actual physical trigger. No second port/open,
    # no DSH request, no audio acquisition and no serial reboot.
    next_wake_diag=clock()+8.0 if wake_gate is not None else None
    wake_diag_pending=False
    wake_diag_state=None
    while clock()<deadline:
        if stream_deadline is not None and clock()>stream_deadline:
            raise PhysicalHoldCaptureError('voice3_usb_stream_timeout')
        raw=device.readline()
        if not raw:
            if not begun and next_wake_diag is not None and clock()>=next_wake_diag:
                # One status command every 30s, not a discovery probe that
                # closes and reopens USB-JTAG. Voice events retain priority.
                request=b"@@DFWAKE3 STATUS\n"
                if device.write(request)!=len(request):
                    output("R239_WAKE_DIAG_UNAVAILABLE write_incomplete")
                else:
                    device.flush()
                    wake_diag_pending=True
                    wake_diag_state=None
                next_wake_diag=clock()+30.0
            if not begun and idle_handler is not None:
                idle_handler()
            continue
        raw_text=raw.decode('ascii','replace')
        if 'Guru Meditation' in raw_text or 'Rebooting...' in raw_text:
            raise PhysicalHoldCaptureError('device_restarted_mid_audio')
        text=raw_text.strip()
        if not begun:
            other=text
            if text.startswith(("I (","W (","E (","D (")) and text.count("@@DF")==1:
                other=text[text.index("@@DF"):]
            if wake_diag_pending and other.startswith("@@DFWAKE3 STATE "):
                match=re.fullmatch(
                    r"@@DFWAKE3 STATE model=(?:wn[0-9]+_[a-z0-9_]+|mn(?:4q8|5q8)_nihaodafeiyu) "
                    r"ready=([01]) enabled=([01]) "
                    r"source=esp32_mic commands=0(?: boot=[0-9a-f]{16})?",other)
                if match:
                    wake_diag_state=(match[1],match[2])
                    output("R239_WAKE_STATE ready="+match[1]+" enabled="+match[2])
                    wake_diag_pending=False
                continue
            if other.startswith("@@DFWAKE3 MIC "):
                # R240 firmware emits only coarse 30s energy counters, not
                # waveform, transcript, PCM, voiceprints or user-specific data.
                match=re.fullmatch(
                    r"@@DFWAKE3 MIC reads=(\d{1,10}) errors=(\d{1,10}) "
                    r"peak30=(\d{1,5}) prev_peak30=(\d{1,5}) "
                    r"loud30=(\d{1,10}) prev_loud30=(\d{1,10}) "
                    r"detects=(\d{1,10})",other)
                if match:
                    output("R240_WAKE_MIC "
                           +" ".join(k+"="+v for k,v in zip(
                           ("reads","errors","peak30","prev_peak30",
                            "loud30","prev_loud30","detects"),match.groups())))
                continue
            if other.startswith("@@DFWAKE3 RATE "):
                # R247 numeric timing/energy for a completed ~10s window.
                # Never log PCM, text, voiceprints, names or an unknown line.
                match=re.fullmatch(
                    r"@@DFWAKE3 RATE n=(\d{1,4}) ch=([0-9]) hz=(\d{1,6}) "
                    r"window_ms=(\d{1,6}) frames=(\d{1,5}) "
                    r"read_us=(\d{1,10}) detect_us=(\d{1,10}) "
                    r"read_max_us=(\d{1,7}) detect_max_us=(\d{1,7}) "
                    r"peak=(\d{1,5}) loud=(\d{1,5}) clipped=(\d{1,5})",other)
                if match:
                    output("R247_WAKE_NUMERIC "
                           +" ".join(k+"="+v for k,v in zip(
                           ("chunk_samples","channels","sample_hz","window_ms",
                            "frames","read_us_total","detect_us_total",
                            "read_us_max","detect_us_max","peak_16bit",
                            "loud_frames","clipped_frames"),match.groups())))
                continue
            if other.startswith("@@DFWAKE3 BOOT "):
                # R249 same-owner read-only reset cause + uptime. Never read
                # unrelated USB output, and never reset the device here.
                match=re.fullmatch(r"@@DFWAKE3 BOOT reason=(\d{1,2}) uptime_ms=(\d{1,10})",other)
                if match and int(match[1])<=31:
                    output("R249_WAKE_BOOT reset_reason="+match[1]
                           +" uptime_ms="+match[2])
                continue
            if other.startswith("@@DFWAKE3 BOOT2 "):
                # R251 RTC retained wake crash stage: numeric metadata ONLY.
                # Never copy unsolicited serial output or user audio.
                match=re.fullmatch(
                    r"@@DFWAKE3 BOOT2 boots=(\d{1,10}) last_step=(\d{1,3}) "
                    r"crash_step=(\d{1,3}) crash_reason=(\d{1,2})",other)
                if match and int(match[2])<=899 and int(match[3])<=899 \
                   and int(match[4])<=31:
                    output("R251_WAKE_RTC_TRACE "+
                           " ".join(k+"="+v for k,v in zip(
                               ("boots","last_step","crash_step","crash_reason"),
                               match.groups())))
                continue
            if other.startswith("@@DFWAKE3 STAGE "):
                # R242: numeric counters from the original onboard WakeNet
                # task. No PCM, no waveforms, no transcript, no new USB port.
                match=re.fullmatch(
                    r"@@DFWAKE3 STAGE re=(\d{1,10}) ok=(\d{1,10}) "
                    r"err=(\d{1,10}) skip=(\d{1,10}) "
                    r"de=(\d{1,10}) dr=(\d{1,10}) hit=(\d{1,10}) "
                    r"of=(\d{1,10}) phase=([0-3]) age_ms=(\d{1,10})",other)
                if match:
                    output("R242_WAKE_STAGES "
                           +" ".join(k+"="+v for k,v in zip(
                           ("read_enter","read_ok","read_error","gate_skip",
                            "detect_enter","detect_return","hit","open_fail",
                            "phase","age_ms"),match.groups())))
                continue
            if other.startswith("@@DFWAKE3 DIAG "):
                match=re.fullmatch(
                    r"@@DFWAKE3 DIAG can_listen=([01]) wake_mic=([01]) "
                    r"reading=([01]) capture=([01]) speak=([01]) "
                    r"pcm2=([01]) h10=([01]) transfer=([01]) phase=([a-z_]{2,24})",other)
                if match:
                    output("R239_WAKE_DIAG "
                           +" ".join(k+"="+v for k,v in zip(
                           ("can_listen","wake_mic","reading","capture",
                            "speak","pcm2","h10","transfer","phase"),match.groups())))
                continue
            if other.startswith("@@DFWAKE3 DETECTED "):
                seq=wake_gate.consume(other) if wake_gate is not None else None
                if seq is not None:
                    pending_wake_seq=seq
                    pending_wake_at=clock()
                    output("R228_BOARD_WAKENET3_ORIGIN_SEQUENCED")
                # Legacy DFWAKE3 count=1 is never replay proof.
                continue
            if other==WAKE_EVENT:
                output("R38_LEGACY_WAKE2_UNSEQUENCED_TOUCH_FALLBACK")
                continue
        line=peel(raw)
        if not line and not begun and on_physical_frame is not None:
            other=raw_text.strip()
            if other.startswith(('I (','W (','E (','D (')) and other.count('@@DF')==1:
                other=other[other.index('@@DF'):]
            if VISUAL.fullmatch(other):
                on_physical_frame(other)
            continue
        if not line:continue
        if not begun:
            if line=='@@DFVOICE3 CANCEL':
                raise PhysicalHoldCaptureError(
                    'wake_no_speech_no_submit' if pending_wake_seq is not None
                    else 'physical_mic_cancelled_before_begin')
            if line!=BEGIN:continue
            begun=True
            stream_deadline=clock()+100
            if pending_wake_at is None or clock()-pending_wake_at>10:
                pending_wake_seq=None
            output('H28_HOLD_MIC_BEGIN board_microphone_voice3')
            continue
        if line=='@@DFVOICE3 CANCEL':
            raise PhysicalHoldCaptureError(
                'wake_no_speech_no_submit' if pending_wake_seq is not None
                else 'physical_mic_cancelled_short_press_or_error')
        end=END.fullmatch(line)
        if end:
            n=int(end[1]);samples=int(end[2]);reason=end[3]
            if n!=rows or not 5<=rows<=MAX_FRAMES or samples!=rows*320 or len(pcm)!=rows*MIC_BLOCK_BYTES:
                raise PhysicalHoldCaptureError('hold_release_incomplete_or_mismatched_frames')
            if on_capture_origin is not None:
                on_capture_origin("wake" if pending_wake_seq is not None else "touch",
                                  pending_wake_seq)
            output('H28_HOLD_MIC_DONE frames='+str(rows)+' seconds='+str(round(rows/50,2))+' reason='+reason)
            return bytes(pcm)
        match=PCM.fullmatch(line)
        if not match:raise PhysicalHoldCaptureError('voice3_corrupted_serial_frame')
        seq=int(match[1]);
        if seq!=rows or seq>=MAX_FRAMES:
            raise PhysicalHoldCaptureError('voice3_frame_gap_or_overflow')
        try:payload=base64.b64decode(match[2],validate=True)
        except (ValueError,binascii.Error) as exc:
            raise PhysicalHoldCaptureError('voice3_corrupt_base64') from exc
        if len(payload)!=MIC_BLOCK_BYTES:
            raise PhysicalHoldCaptureError('voice3_wrong_pcm_size')
        pcm.extend(payload);rows+=1
        if rows in (1,50,150,500,1000):output('H28_HOLD_MIC_PROGRESS frames='+str(rows))
    raise PhysicalHoldCaptureError('no_board_press_or_incomplete_hold_recording')
