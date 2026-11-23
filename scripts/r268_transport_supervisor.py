"""R268 optional Mac USB/LAN voice-owner supervisor.

A *single* official DSH Session owner is allowed. When the ESP32 USB/JTAG
host is absent, stop the old USB LaunchAgent then start the authenticated
WSS gateway. When USB returns, wait for LAN clients and DSH jobs to finish,
stop WSS, then restore the legacy USB owner. Never preempt an active turn.

Default is dry-run/status only. Do not enable as LaunchAgent before real
physical Wi-Fi and independent 5V verification.
"""
from __future__ import annotations
import argparse,json,os,re,signal,subprocess,time
from pathlib import Path
from dataclasses import dataclass

BASE=Path.home()/"Library/Application Support/Deepseek-live"
ROOT=Path(__file__).resolve().parents[1]  # portable checkout
PAIR=BASE/"lan-pairing/authorized-devices.json"
STATE=BASE/"lan-pairing/lan-gateway-status.json"
USB_JOB=f"gui/{os.getuid()}/local.deepseeklive.r29.voice"
PLIST=Path.home()/"Library/LaunchAgents/local.deepseeklive.r29.voice.plist"
TLS_CERT=BASE/"lan-pairing/gateway.crt.pem"
TLS_KEY=BASE/"lan-pairing/gateway.key.pem"
GATEWAY=ROOT/"scripts/r268_start_lan_gateway.sh"
LOG=BASE/"lan-pairing/r268-supervisor-lan.log"

@dataclass(frozen=True)
class Snapshot:
    usb_present:bool
    usb_job_loaded:bool
    lan_alive:bool
    lan_clients:int
    pending_dsh:int
    paired:bool
    voice_busy:bool
    # Authenticated Mac KWS audio is not a DSH turn. A USB cable returning
    # must be able to reclaim the single owner without waiting forever for
    # a 24/7 authenticated prewake_streaming connection to disconnect.
    lan_prewake_only:bool=False

def decide(s:Snapshot)->str:
    if s.usb_present:
        if s.lan_alive:
            return ("wait_lan_turn" if
                    (s.pending_dsh or (s.lan_clients and not s.lan_prewake_only))
                    else "stop_lan")
        if not s.usb_job_loaded:return "start_usb"
        return "usb_idle"
    if not s.paired:return "no_pair_no_wifi_owner_change"
    if s.voice_busy:return "wait_usb_dsh_turn"
    if s.usb_job_loaded:return "stop_usb"
    if not s.lan_alive:return "start_lan"
    return "lan_idle"

def call(*cmd):
    return subprocess.run(cmd,capture_output=True,text=True,timeout=12)
def usb_manually_disabled():
    """Respect the user's real launchctl switch, not a UI-only preference.

    Without this check the owner supervisor would retry bootstrap every two
    seconds after an intentional USB service shutdown.
    """
    state=call('/bin/launchctl','print-disabled',f'gui/{os.getuid()}')
    if state.returncode:
        return False  # never infer disabled from an unreadable setting
    return bool(re.search(r'(?m)^\s*"local\.deepseeklive\.r29\.voice"\s*=>\s*disabled\s*$',
                          state.stdout))
def usb_attached():
    # A physically absent usbmodem device is conclusive even when the
    # supervisor's Python lacks pyserial. With any usbmodem present, retain
    # strict VID/PID identification and fail closed on missing dependencies.
    if not any(Path('/dev').glob('cu.usbmodem*')):
        return False
    # Resolve the known ESP32-S3 USB Serial/JTAG port, never a random Mac USB
    # modem or a fixed serial path after USB re-enumeration.
    try:
        from app.esp_usb_serial_locator import resolve_esp32_port
        return Path(resolve_esp32_port()).exists()
    except ImportError:return True  # unknown USB state: preserve old owner
    except (RuntimeError,OSError,ValueError):return False
# A physically detached USB worker can keep updating its old busy receipt.
# Age of updated_at alone is not a reliable proof of an active DSH task.
_r486_detached_taskfree_since=None
def voice_busy():
    global _r486_detached_taskfree_since
    p=BASE/"companion-native/status.json"
    try:
        row=json.loads(p.read_text())
        phase=row.get("phase")
        if phase in (None,"idle"):
            return False
        # The companion snapshot can remain at voice_generating after a
        # completed LAN turn. Once USB is absent, the USB owner is unloaded,
        # and the snapshot is old, it cannot represent an in-flight USB job.
        # Never override a recent snapshot or a live USB owner.
        stamp=row.get("updated_at_unix")
        detached=not usb_attached()
        taskfree=row.get("current_task_id") is None
        if not detached or not taskfree:
            _r486_detached_taskfree_since=None
        elif phase=="error":
            _r486_detached_taskfree_since=None
            return False  # No physical USB transport and no active DSH task.
        else:
            elapsed_clock=time.monotonic()
            if _r486_detached_taskfree_since is None:
                _r486_detached_taskfree_since=elapsed_clock
            elif elapsed_clock-_r486_detached_taskfree_since>=10.0:
                # Allow USB owner release even if its own status writer
                # refreshes old "voice_generating" every second.
                return False
        # A USB LaunchAgent can remain *loaded* (and its status stuck in an
        # old voice_generating phase) after the physical USB transport goes
        # away. Previously this required owner_loaded()==False, but decide()
        # cannot unload that owner until voice_busy() returns False: the
        # supervisor deadlocked in wait_usb_dsh_turn forever, so the paired
        # Wi-Fi wake gateway never started.
        #
        # Treat only an aged, task-free receipt as stale. Real active DSH
        # tasks and recently updated snapshots still fail closed; no action
        # is taken while USB is physically present.
        if (not usb_attached()
            and type(row.get("current_task_id")) is type(None)
            and type(stamp) in (int,float)
            and 120 < time.time()-stamp < 30*86400):
            return False
        # With battery-powered ESP32 unplugged, the legacy USB LaunchAgent
        # records a terminal transport error and may repeatedly try to spawn.
        # That stale error is not an in-flight DSH job. Permit handoff ONLY
        # when no task is active, USB is absent and the old worker has no PID.
        if (phase=="error" and row.get("current_task_id") is None
            and not usb_attached()):
            # A freshly reported terminal USB transport failure is not an
            # active DSH job even if KeepAlive briefly keeps the old worker
            # loaded. This allows prompt Wi-Fi wake after a board reboot.
            if (type(stamp) in (int,float)
                and 0<=time.time()-stamp<=60):
                return False
            status=call("/bin/launchctl","print",USB_JOB)
            if status.returncode!=0 or not re.search(
                    r"\bpid = [1-9]\d*",status.stdout):
                return False
        return True
    except (OSError,ValueError):return True
def _detached_usb_wait_diagnostic():
    """Only bounded status flags; never log actual task/session IDs or text."""
    path=BASE/"companion-native/status.json"
    try:
        row=json.loads(path.read_text())
        phase=row.get("phase","unknown")
        allowed={"idle","error","listening","transcribing","thinking",
                 "tool_pending","approval_pending","voice_generating","speaking"}
        if phase not in allowed:phase="unknown"
        ts=row.get("updated_at_unix")
        age=round(max(0.0,time.time()-ts),1) if type(ts) in (float,int) else -1
        return f"phase={phase} task_id_present={int(row.get('current_task_id') is not None)} status_age_s={age}"
    except (OSError,ValueError,TypeError,AttributeError):
        return "state_unavailable=1"

def owner_loaded():
    return call("/bin/launchctl","print",USB_JOB).returncode==0
def orphan_gateway_active():
    # A crashed/restarted supervisor must never start the USB DSH Session
    # while a detached but still-active WSS child owns the same DSH.
    try:
        row=json.loads(STATE.read_text())
        candidate=row.get("pid")
        if type(candidate) is not int or candidate<=1:return False
        os.kill(candidate,0)
        command=call("/bin/ps","-p",str(candidate),"-o","command=")
        return command.returncode==0 and (
            "r268_wifi_mac_gateway.py" in command.stdout)
    except (OSError,ValueError,TypeError):return False

def safe_lan_snapshot(proc):
    if proc is not None and proc.poll() is not None:return False,0,0
    if proc is None:
        if orphan_gateway_active():return True,1,1 # refuse second owner
        return False,0,0
    try:
        row=json.loads(STATE.read_text())
        if row.get("pid")!=proc.pid or time.time()-row["updated_at_unix"]>6:
            return True,1,1  # uncertain status: never kill active session
        return True,max(0,int(row["active_devices"])),max(0,int(row["pending_dsh_jobs"]))
    except (OSError,ValueError,TypeError,KeyError):return True,1,1
def verified_prewake_only(proc)->bool:
    """Only a fresh receipt from our exact child, with ZERO DSH work.

    A malformed, stale, or unidentified WSS owner must never be killed.
    This permits USB to reclaim the board from a passive wake monitor,
    not from an actual recording, reply, or streaming playback.
    """
    if proc is None or proc.poll() is not None:return False
    try:
        row=json.loads(STATE.read_text())
        age=time.time()-row["updated_at_unix"]
        return (row.get("pid")==proc.pid and 0<=age<6 and
                row.get("transport")=="trusted_mac_lan" and
                row.get("device_phase")=="prewake_streaming" and
                type(row.get("active_devices")) is int and
                row["active_devices"]==1 and
                type(row.get("pending_dsh_jobs")) is int and
                row["pending_dsh_jobs"]==0)
    except (OSError,ValueError,TypeError,KeyError):
        return False

def paired():
    try:
        row=json.loads(PAIR.read_text())
        return row.get("schema")==1 and len(row.get("devices",{}))==1 and (
            TLS_CERT.is_file() and TLS_KEY.is_file())
    except (OSError,ValueError):return False
def snapshot(proc):
    alive,clients,pending=safe_lan_snapshot(proc)
    present=usb_attached()
    return Snapshot(present,owner_loaded(),alive,
                    clients,pending,paired(),voice_busy(),
                    lan_prewake_only=(present and alive and pending==0 and
                                      verified_prewake_only(proc)))
def persistent_wake_reload_required(proc, s:Snapshot) -> bool:
    """Reload only an owned, verified-idle LAN child after a user setting change.

    A current ESP32 connection or official DSH job ALWAYS blocks restart.
    Never terminate an orphan process, an unknown PID, or a stale receipt.
    """
    if (proc is None or proc.poll() is not None or
        s.usb_present or s.usb_job_loaded or not s.lan_alive or
        s.lan_clients or s.pending_dsh or s.voice_busy):
        return False
    from app.r439_persistent_prewake import decision
    desired = decision()
    if desired is None:
        return False  # The old 30-minute experiment remains independently valid.
    try:
        row = json.loads(STATE.read_text())
        return bool(row.get("pid") == proc.pid and
                    0 <= time.time()-row["updated_at_unix"] < 6 and
                    row.get("active_devices") == 0 and
                    row.get("pending_dsh_jobs") == 0 and
                    row.get("prewake_enabled") is not desired)
    except (OSError, ValueError, TypeError, KeyError):
        return False

def start_lan():
    address=call("/usr/sbin/ipconfig","getifaddr","en0")
    if address.returncode or not address.stdout.strip():
        raise RuntimeError("mac_lan_ip_missing")
    LOG.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(LOG,os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
    try:
        command=[str(GATEWAY),"--bind",address.stdout.strip(),"--port","8877",
                 "--tls-cert",str(TLS_CERT),"--tls-key",str(TLS_KEY)]
        return subprocess.Popen(command,cwd=str(ROOT),stdout=fd,stderr=fd,
                                start_new_session=True)
    finally:os.close(fd)
def perform(action:str,proc):
    if action=="stop_usb":
        if call("/bin/launchctl","bootout",USB_JOB).returncode:
            raise RuntimeError("usb_service_bootout_failed")
    elif action=="start_usb":
        if call("/bin/launchctl","bootstrap",f"gui/{os.getuid()}",str(PLIST)).returncode:
            raise RuntimeError("usb_service_bootstrap_failed")
    elif action=="start_lan":
        proc=start_lan()
    elif action=="restart_lan" and proc is not None:
        # Only the supervisor's own child may be restarted, with no device
        # connection and no in-flight DSH request; preserve the sole owner.
        proc.terminate()
        try:proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            raise RuntimeError("lan_wake_reload_would_interrupt_owner")
        proc=start_lan()
    elif action=="stop_lan" and proc is not None:
        proc.terminate()
        try:proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            # Never SIGKILL DSH tasks: preserve the full in-flight turn.
            raise RuntimeError("lan_owner_did_not_exit_safely")
        proc=None
    return proc
def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--run",action="store_true",
                     help="actual owner switching (requires verified physical LAN acceptance)")
    cli.add_argument("--cycles",type=int,default=0,
                     help="0=continuous; positive=bounded for tests")
    args=cli.parse_args()
    proc=None;cycle=0;detached_wait_cycles=0
    while args.cycles==0 or cycle<args.cycles:
        s=snapshot(proc);action=decide(s)
        if (action=="start_usb" and usb_manually_disabled()):
            action="usb_explicitly_disabled"
        if action=="lan_idle" and persistent_wake_reload_required(proc,s):
            action="restart_lan"
        if action not in ("usb_idle","lan_idle","usb_explicitly_disabled"):
            print("R268_OWNER_PLAN",action,"USB_present="+str(s.usb_present),
                  "pending_DSH="+str(s.pending_dsh),flush=True)
        if s.usb_present is False and action=="wait_usb_dsh_turn":
            detached_wait_cycles+=1
            # R489: do not preempt a real official DSH turn. Record only
            # redacted evidence if detachment unexpectedly remains blocked.
            if detached_wait_cycles in (5,15,30) or detached_wait_cycles%60==0:
                print("R489_USB_DETACHED_STILL_BUSY",
                      "polls="+str(detached_wait_cycles),
                      _detached_usb_wait_diagnostic(),flush=True)
        else:
            detached_wait_cycles=0
        if not args.run:
            print("R268_SUPERVISOR_DRY_RUN no_service_changes=true")
            break
        proc=perform(action,proc)
        cycle+=1
        time.sleep(2.0)
if __name__=="__main__":main()
