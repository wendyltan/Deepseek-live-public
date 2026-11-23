"""Opt-in remote LVGL screen monitor via sole ESP32 USB serial owner.

No model, audio capture or WLAN. During monitor the named Mac voice owner
is stopped, and always restored. R61 has no DFSCREEN2 and fails closed.
Every screenshot is a verified **software** LVGL view, not OLED optics.
"""
from __future__ import annotations
import argparse,json,os,signal,subprocess,time
from pathlib import Path
from app.r92_lvgl_frame_protocol import CAPS,COUNT,decode,persist,ScreenProtocolError

PORT=os.environ.get('DAFEIYU_USB_SERIAL_PORT','/dev/cu.usbmodem')
HOME=Path.home()
APP=HOME/'Library/Application Support/Deepseek-live/companion-native'
OUT=HOME/'Library/Application Support/Deepseek-live/display-diagnostics/r92-live'
NAME='local.deepseeklive.r29.voice'
STOP=False

def _signal(signum,frame):
    global STOP
    STOP=True

def launchctl(arguments,timeout=16):
    return subprocess.run(['/bin/launchctl',*arguments],capture_output=True,
                          timeout=timeout,check=False)

def screen_capture(device,*,timeout=32):
    # On real board only: capability first prevents interpreting e.g. console
    # lines or local GIFs as a screenshot.
    pending=bytearray()
    def read(timeout_until,max_line=1900):
        # Same Serial.readline() transport as the proven real-board CAPS
        # diagnostic. A timed-out partial line is carried across reads.
        while time.monotonic()<timeout_until:
            if b'\n' in pending:
                raw,remain=bytes(pending).split(b'\n',1)
                pending[:]=remain
                if len(raw)>max_line:continue
                try:return raw.decode('ascii').strip()
                except UnicodeDecodeError:continue
            part=device.readline()
            if part:
                pending.extend(part)
                if len(pending)>3000:pending.clear()
        raise ScreenProtocolError('usb_screen_protocol_timeout')
    device.reset_input_buffer()
    device.write(b'@@DFSCREEN2 CAPS\n');device.flush()
    limit=time.monotonic()+9.0
    verified=False
    probe_lines=0
    while time.monotonic()<limit:
        row=read(limit)
        probe_lines+=1
        if probe_lines<=8:
            print('R92_CAPS_PROBE_ROW '+row[:105],flush=True)
        if row==CAPS:
            verified=True
            print("R92_MONITOR_REAL_SCREEN_CAPS_VERIFIED",flush=True)
            break
        if row.startswith('@@DFSCREEN2 '):
            raise ScreenProtocolError('wrong_screen_caps')
    if not verified:raise ScreenProtocolError('screen_caps_not_supported')
    device.write(b'@@DFSCREEN2 CAPTURE\n');device.flush()
    started=time.monotonic()
    deadline=started+timeout
    lines=[]
    while len(lines)<COUNT+2:
        row=read(deadline)
        if '@@DFSCREEN2 ' in row and not row.startswith('@@DFSCREEN2 '):
            pre,_,rest=row.partition('@@DFSCREEN2 ')
            print('R92_SCREEN_LINE_HAS_CONSOLE_PREFIX length='+str(len(pre)),flush=True)
            # Only accept a single standard ESP-IDF log prefix, then still
            # require exact ordered packets and complete CRC32.
            import re
            if re.fullmatch(r'[DIWE] \( *[0-9]+\) [^\r\n]{0,180}',pre):
                row='@@DFSCREEN2 '+rest
        if row.startswith('@@DFSCREEN2 NACK'):
            raise ScreenProtocolError('device_refused:'+row.split(' ',2)[-1][:70])
        if row.startswith('@@DFSCREEN2 '):
            lines.append(row)
            if len(lines) in (1,2,101,301,601,602):
                print("R92_FRAME_RX_PROGRESS count="+str(len(lines))+
                      " sample="+row[:72],flush=True)
        if len(lines)==1 and not row.startswith('@@DFSCREEN2 BEGIN'):
            raise ScreenProtocolError('frame_begin_missing')
        if row=='@@DFSCREEN2 END count=600' and len(lines)!=COUNT+2:
            import re
            collected={int(x[1]) for x in (re.match(r'^@@DFSCREEN2 DATA index=([0-9]+)',line) for line in lines[1:]) if x}
            missing=[idx for idx in range(COUNT) if idx not in collected]
            raise ScreenProtocolError('missing_frame_packets_'+str(missing[:12]))
    raw=decode(lines)
    return raw,round(time.monotonic()-started,3)

def monitor(*,max_seconds=95,interval=9):
    if not 10<=max_seconds<=180 or not 3<=interval<=30:
        raise ValueError('bounded_monitor_schedule_required')
    if not os.path.exists(PORT):raise ScreenProtocolError('real_esp32_usb_not_found')
    # Screen pixels are a read-only physical USB capability and must not
    # depend on paid DSH availability or freshness of a cloud conversation.
    # Block only if a *fresh* native voice report declares active recording
    # or playback; inactive/stale DSH cannot prevent local pixel monitoring.
    try:
        state=json.loads((APP/'status.json').read_text())
    except (OSError,ValueError):
        state={}
    age=time.time()-state.get('updated_at_unix',0)
    if -5<=age<=30 and state.get('phase') in (
        'listening','transcribing','thinking','tool_pending',
        'approval_pending','voice_generating','speaking'):
        raise ScreenProtocolError('native_voice_busy_do_not_interrupt')
    print('R94_SCREEN_INDEPENDENT_OF_DSH_STATUS',flush=True)
    label=f'gui/{os.getuid()}/{NAME}'
    agent=HOME/f'Library/LaunchAgents/{NAME}.plist'
    if not agent.is_file() or agent.is_symlink():
        raise ScreenProtocolError('voice_launchagent_untrusted')
    # The app shows a visible warning before calling. Do not hijack the
    # USB owner if it can't be stopped; never bypass audio privacy gate.
    result=launchctl(['bootout',label])
    if result.returncode!=0:
        raise ScreenProtocolError('usb_voice_owner_busy')
    # Exact same ownership handoff that proved real, full-frame 480x480
    # ESP32 capture: allow launchd's old serial FD to close before reopening.
    time.sleep(1)
    received=0;last_crc=None;errors=0;start=time.monotonic()
    print('R92_MONITOR_USB_OWNED voice_paused=1',flush=True)
    try:
        import serial
        with serial.Serial(PORT,115200,timeout=.2,write_timeout=5,
                           exclusive=True,rtscts=False,dsrdtr=False) as usb:
            usb.dtr=False;usb.rts=False
            # ESP32-S3 USB Serial/JTAG physically resets on an exclusive
            # reopen on this board. Wait for SD/LVGL/USB boot before CAPS.
            print('R92_MONITOR_BOOT_LOG_DRAIN_SECONDS=13',flush=True)
            boot_until=time.monotonic()+13
            saw_ready=False
            while time.monotonic()<boot_until and not STOP:
                # Some opens physically reset ESP32; others don't. Drain the
                # VFS log buffer either way but don't require a new boot log.
                raw=usb.readline()
                if b'Guru Meditation' in raw or b'Stack overflow' in raw:
                    raise ScreenProtocolError('esp32_reboot_or_crash_on_monitor_open')
                if b'H9_USB_CONTROL_READY' in raw:
                    saw_ready=True
            print('R92_MONITOR_BOOT_DRAIN_COMPLETE saw_fresh_usb_ready='+
                  str(saw_ready),flush=True)
            while not STOP and time.monotonic()-start<max_seconds:
                try:
                    raw,capture_s=screen_capture(usb)
                    import zlib
                    crc=zlib.crc32(raw)
                    changed=(crc!=last_crc)
                    if changed:
                        persist(raw,OUT,board_caps_verified=True)
                        last_crc=crc
                    received+=1;errors=0
                    print('R92_MONITOR_VERIFIED frame='+str(received)+
                          ' capture_s='+str(capture_s)+
                          ' crc='+f'{crc:08x}'+
                          ' changed='+str(changed),flush=True)
                except (ScreenProtocolError,OSError,ValueError) as e:
                    errors+=1
                    print('R92_MONITOR_FRAME_FAILED '+type(e).__name__+' '+str(e)[:110],flush=True)
                    if errors>=3:break
                delay=max(0.0,interval-(time.monotonic()-start)%interval)
                deadline=time.monotonic()+delay
                while not STOP and time.monotonic()<deadline:
                    time.sleep(min(.25,deadline-time.monotonic()))
    finally:
        restored=launchctl(['bootstrap',f'gui/{os.getuid()}',str(agent)])
        if restored.returncode==0:
            launchctl(['kickstart',label])
        print('R92_MONITOR_VOICE_AGENT_RESTORED='+str(restored.returncode==0)+
              ' frames='+str(received),flush=True)
    return received

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--duration',type=int,default=95)
    args=parser.parse_args()
    signal.signal(signal.SIGTERM,_signal)
    signal.signal(signal.SIGINT,_signal)
    try:
        count=monitor(max_seconds=args.duration)
        if not count:raise ScreenProtocolError('no_physical_pixels_received')
    except (ScreenProtocolError,OSError,ValueError) as e:
        print('R92_MONITOR_ABORTED '+type(e).__name__+' '+str(e)[:130],flush=True)
        raise SystemExit(2)
if __name__=='__main__':main()
