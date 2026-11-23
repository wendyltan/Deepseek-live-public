"""Explicit-only future DFSD3 upload CLI for approved R83 devices.

Default --dry-run has zero serial calls. Physical installation requires the
user to stop the separate voice serial owner, stand by the ESP32, tap it after
a local ARM_REQUEST, and pass two deliberate CLI flags. No R79/DFSD2 fallback.
"""
from __future__ import annotations
import argparse,json,os,subprocess,time
from contextlib import contextmanager
from pathlib import Path
from scripts.r72_plan_motion_sync import plan,SyncPlanError
from scripts.r72_prepare_motion_candidate import ROOT,verify
from app.r82_motion_usb_transport import upload,FakeFutureDevice,TransferRejected,CAPS

class SerialExchange:
    def __init__(self,port,timeout=4.0):
        import serial
        self.ser=serial.Serial(port,115200,timeout=.25,write_timeout=timeout,
                               exclusive=True,rtscts=False,dsrdtr=False)
        self.ser.dtr=False;self.ser.rts=False
        self.timeout=timeout
        self._pending=bytearray()
        # R94 and R83 ESP32-S3 can reset upon USB Serial/JTAG reopen. Only
        # drain console bytes; do not start a microphone, SD write or model.
        deadline=time.monotonic()+13
        while time.monotonic()<deadline:
            row=self.ser.readline()
            if b"Guru Meditation" in row or b"Stack overflow" in row:
                raise TransferRejected("board_boot_crash")
        self.ser.reset_input_buffer()
    def close(self):self.ser.close()
    def await_prefix(self,prefix:str,timeout:float|None=None)->str:
        deadline=time.monotonic()+(timeout or self.timeout)
        while time.monotonic()<deadline:
            while b"\n" in self._pending:
                raw,_,rest=self._pending.partition(b"\n")
                self._pending=bytearray(rest)
                if len(raw)>300:raise TransferRejected("oversized_device_reply")
                try:decoded=raw.decode("ascii").strip()
                except UnicodeError:continue
                if decoded.startswith(prefix):return decoded
            part=self.ser.readline()
            if part:self._pending.extend(part)
            if len(self._pending)>1024:raise TransferRejected("oversized_device_reply")
        raise TransferRejected("serial_reply_timeout")
    def request(self,message:str,prefix:str="@@DFSD3 ")->str:
        self.ser.write((message+"\n").encode("ascii"))
        self.ser.flush()
        return self.await_prefix(prefix)

@contextmanager
def pause_voice_owner_for_explicit_install(port:str):
    """Strict opt-in serial ownership handoff; never used for dry-run."""
    if not port.startswith("/dev/cu.usbmodem"):
        raise TransferRejected("unsupported_serial_port")
    from pathlib import Path
    status=Path.home()/"Library/Application Support/Deepseek-live/companion-native/status.json"
    try:
        board=json.loads(status.read_text())
        age=time.time()-board.get("updated_at_unix",0)
        if -5<=age<=30 and board.get("phase") in (
            "listening","transcribing","thinking","tool_pending",
            "approval_pending","voice_generating","speaking"):
            raise TransferRejected("live_audio_turn_busy_do_not_interrupt")
    except (OSError,ValueError,TypeError):
        # User explicitly requested installation, and stale state is not proof
        # of a live voice turn. The dedicated launchd owner is stopped below.
        pass
    label="local.deepseeklive.r29.voice"
    domain=f"gui/{os.getuid()}"
    plist=Path.home()/f"Library/LaunchAgents/{label}.plist"
    if not plist.is_file() or plist.is_symlink():
        raise TransferRejected("recognized_voice_service_plist_unavailable")
    # Stop only the named, user-owned voice service. A deliberately paused
    # service stays paused after upload; never restart it behind the user's back.
    label_path=f"{domain}/{label}"
    state=subprocess.run(["launchctl","print",label_path],
                         capture_output=True,text=True,timeout=12,check=False)
    was_loaded=state.returncode==0
    if was_loaded:
        stopped=subprocess.run(["launchctl","bootout",label_path],
                               capture_output=True,text=True,timeout=12,check=False)
        if stopped.returncode!=0:
            raise TransferRejected("cannot_take_exclusive_usb_from_voice_service")
    try:
        time.sleep(1.0)
        yield
    finally:
        if was_loaded:
            restored=subprocess.run(["launchctl","bootstrap",domain,str(plist)],
                                    capture_output=True,text=True,timeout=12,check=False)
            if restored.returncode!=0:
                raise TransferRejected("voice_runtime_restore_failed")
            subprocess.run(["launchctl","kickstart",label_path],
                           capture_output=True,text=True,timeout=12,check=False)

def artifact(root:Path,ident:str,slot:int):
    proposal=plan(root)
    items=[item for item in proposal["motions"] if item["id"]==ident]
    if len(items)!=1 or items[0]["assigned_device_id"]!=f"m{slot:03d}":
        raise SyncPlanError("unknown_or_reassigned_candidate")
    record=items[0]
    if record["action_class"] not in ("idle","work","reaction","bonus"):
        raise SyncPlanError("motion_role_not_assigned")
    file=root/"candidates"/(ident+".DFS")
    if file.is_symlink() or not file.is_file() or file.stat().st_size>8_000_000:
        raise SyncPlanError("unsafe_source_candidate")
    raw=file.read_bytes()
    decoded=verify(raw)
    if decoded["sha256"]!=record["sha256"]:
        raise SyncPlanError("candidate_file_not_matching_plan")
    return raw,record

def run(root:Path,ident:str,slot:int,port:str|None,
        physical_approval:bool=False,writing_approved:bool=False):
    content,record=artifact(root,ident,slot)
    if not (physical_approval and writing_approved):
        sim=FakeFutureDevice()
        receipt=upload(sim,slot=slot,contents=content,
                       role=record["action_class"],local_confirmation=True)
        return {"mode":"dry_run","device_written":False,
                "slot":receipt.slot,"chunks":receipt.chunks,
                "simulated_readback_verified":receipt.device_readback_verified}
    if port is None or not port.startswith("/dev/cu.usbmodem"):
        raise TransferRejected("explicit_macos_usb_serial_port_required")
    # The recognized voice service is already booted out by the enclosing
    # context. macOS UserEventAgent can retain a nonexclusive read-only FD,
    # so treating every lsof PID as a writer rejects every valid install.
    # pyserial exclusive=True obtains the actual single-owner TTY lock.
    link=SerialExchange(port,timeout=6)
    try:
        # A harmless device-only feature probe prevents waiting for a tap
        # on R94 or any firmware that has not implemented DFSD3.
        version=link.request("@@DFSD3 STATUS")
        if not version.startswith("@@DFSD3 STATE armed=0 writing=0 received=0"):
            raise TransferRejected("physical_firmware_not_dfSD3_ready")
        arm=link.request("@@DFSD3 ARM_REQUEST")
        if arm!="@@DFSD3 WAIT_LOCAL_TOUCH seconds=30":
            raise TransferRejected("firmware_not_advertising_physical_arm")
        # User must actually TAP the ESP32; host cannot inject approval.
        deadline=time.monotonic()+30
        ready=False
        while time.monotonic()<deadline:
            candidate=link.request("@@DFSD3 CAPS")
            if candidate==CAPS:
                ready=True;break
            if candidate!="@@DFSD3 UNAVAILABLE":
                raise TransferRejected("unexpected_device_arm_status")
            time.sleep(.7)
        if not ready:raise TransferRejected("physical_arm_not_confirmed")
        receipt=upload(link,slot=slot,contents=content,role=record["action_class"],
                       local_confirmation=True)
        # SD persistence is distinct from render success. Physical proof of
        # m200–m207 requires QUEUED and the actual first decoded LVGL frame.
        playback=False
        playback_error=None
        seq=int(time.time())%999999999
        try:
            queue=link.request(
                f"@@DFMOTION1 SELECT seq={seq} id={receipt.slot}",
                prefix="@@DFMOTION1 ")
            if queue!="@@DFMOTION1 QUEUED":
                raise TransferRejected("device_did_not_queue_motion")
            applied=link.await_prefix("@@DFMOTION1 APPLIED ",timeout=16)
            if applied!=f"@@DFMOTION1 APPLIED seq={seq} id={receipt.slot} frame=1":
                raise TransferRejected("device_motion_render_receipt_mismatch")
            playback=True
        except (TransferRejected,OSError,ValueError) as exc:
            playback_error=str(exc)[:80]
        return {"mode":"real_explicit","device_written":not receipt.already_present,
                "already_present":receipt.already_present,
                "slot":receipt.slot,"chunks":receipt.chunks,
                "sha256":receipt.sha256,"sd_readback_verified":receipt.device_readback_verified,
                "device_playback_first_frame_verified":playback,
                "playback_error":playback_error}
    finally:link.close()

def save_real_receipt(root:Path, result:dict) -> str:
    if (result.get("mode")!="real_explicit" or result.get("device_written") is not True
        or result.get("sd_readback_verified") is not True):
        raise TransferRejected("unverified_result_cannot_be_persisted")
    import uuid
    directory=root/"device-install-receipts"
    if directory.is_symlink():
        raise TransferRejected("unsafe_receipt_directory")
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    stamp=time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())
    path=directory/(stamp+"-"+uuid.uuid4().hex[:8]+".json")
    public={k:result[k] for k in (
        "mode","device_written","sd_readback_verified","slot","sha256","chunks")}
    public["device_playback_first_frame_verified"]=bool(
        result.get("device_playback_first_frame_verified"))
    with path.open("x",encoding="utf-8") as stream:
        os.fchmod(stream.fileno(),0o600)
        json.dump(public,stream,indent=2)
        stream.flush();os.fsync(stream.fileno())
    return str(path)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--id",required=True)
    ap.add_argument("--slot",type=int)
    ap.add_argument("--port")
    ap.add_argument("--manage-voice-agent",action="store_true")
    ap.add_argument("--confirm-physical-tap",action="store_true")
    ap.add_argument("--approve-user-slot-write",action="store_true")
    args=ap.parse_args()
    try:
        plan_data=plan(ROOT)
        candidates=[item for item in plan_data["motions"] if item["id"]==args.id]
        if len(candidates)!=1:raise SyncPlanError("selected_candidate_not_in_plan")
        expected=int(candidates[0]["assigned_device_id"][1:])
        if args.slot is not None and args.slot!=expected:
            raise SyncPlanError("selected_slot_does_not_match_versioned_plan")
        if args.confirm_physical_tap != args.approve_user_slot_write:
            raise TransferRejected("both_physical_approval_flags_required")
        real=args.confirm_physical_tap and args.approve_user_slot_write
        if real and not args.manage_voice_agent:
            raise TransferRejected("real_upload_requires_owned_voice_session_handoff")
        if real:
            if args.port is None:raise TransferRejected("port_required_for_real_install")
            with pause_voice_owner_for_explicit_install(args.port):
                result=run(ROOT,args.id,expected,args.port,True,True)
        else:
            result=run(ROOT,args.id,expected,args.port,False,False)
        if result.get("device_written") is True:
            result["receipt_file"]=save_real_receipt(ROOT,result)
        print(json.dumps(result,ensure_ascii=False))
    except (TransferRejected,SyncPlanError,ValueError,OSError) as exc:
        print(json.dumps({"ok":False,"device_written":False,"error":str(exc)},
                         ensure_ascii=False))
        raise SystemExit(2)
if __name__=="__main__":main()
