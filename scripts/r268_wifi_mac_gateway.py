"""R268 experimental trusted Wi-Fi gateway for EXISTING official DSH + D10.

No LAN listener without explicit authorized device and TLS certificate.
Never run concurrently with the USB voice owner's DSH Session. No DSH
completion on startup, no secret in CLI or serial logs, no automatic fallback.
"""
from __future__ import annotations
import argparse,asyncio,json,os,re,ssl,stat,subprocess
from pathlib import Path

PAIRING=Path.home()/"Library/Application Support/Deepseek-live/lan-pairing/authorized-devices.json"
USB_OWNER=f"gui/{os.getuid()}/local.deepseeklive.r29.voice"

def read_paired():
    if not PAIRING.is_file() or PAIRING.is_symlink():
        raise RuntimeError("r268_no_explicitly_paired_device")
    st=PAIRING.stat()
    if st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077:
        raise RuntimeError("r268_pairing_file_permissions")
    obj=json.loads(PAIRING.read_text())
    if obj.get("schema")!=1 or not isinstance(obj.get("devices"),dict):
        raise RuntimeError("r268_pairing_file_invalid")
    devices=obj["devices"]
    if not 1<=len(devices)<=4:raise RuntimeError("r268_device_count_invalid")
    for key,value in devices.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}",key) or not isinstance(value,str) or len(value)<32:
            raise RuntimeError("r268_device_token_invalid")
    return devices

def refuse_parallel_usb_owner():
    proc=subprocess.run(["/bin/launchctl","print",USB_OWNER],
                        capture_output=True,text=True,timeout=7)
    if proc.returncode==0 and re.search(r"\bpid = [1-9]\d*",proc.stdout):
        raise RuntimeError("r268_usb_owner_active_switch_transport_before_starting_lan")

def r301_ws_ping_settings(environ=None):
    """Isolate ESP-IDF WS control-frame compatibility in an opt-in test.

    Default is the historical 10s/15s server-origin Ping watchdog.
    A specifically authorized R301 run may disable server-origin protocol
    Ping while retaining authenticated, per-turn application state pulses.
    It never changes device login, TLS, pairing, DSH, or Qwen behavior.
    """
    if environ is None:
        environ=os.environ
    # R441: paired R436/R441 KWS WSS uses continuous 60ms mic/speaker
    # frames and 2s authenticated application state pulses while thinking.
    # Server-origin RFC6455 Ping is an independent compatibility variable;
    # suppress it only for the explicitly user-enabled R439 release path.
    # Keep legacy default for unconfigured/ineligible devices and tests.
    if (environ.get("DF_LAN_DISABLE_PROTOCOL_PING")=="1" or
        environ.get("DF_R441_WSS_SAFE_CONTROL")=="1"):
        return None,None
    return 10,15


def make_tls(cert:Path|None,key:Path|None,bind:str):
    if cert is None or key is None:
        if bind not in ("127.0.0.1","::1"):
            raise RuntimeError("r268_refuse_unencrypted_LAN_audio")
        return None
    if not cert.is_file() or not key.is_file() or cert.is_symlink() or key.is_symlink():
        raise RuntimeError("r268_tls_files_missing")
    if key.stat().st_uid!=os.getuid() or stat.S_IMODE(key.stat().st_mode)&0o077:
        raise RuntimeError("r268_tls_key_permissions")
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version=ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert),str(key))
    return ctx

def build_backend():
    # Reuse the same native voice companion tab identity and original DSH
    # Bridge; never create another agent, bypass approvals, or change Qwen.
    from scripts.r18_h10_native_dialogue import (
        read_private_token,official_bridge_token_path,stable_local_conversation_tab_id,BRIDGE
    )
    from app.dsh_p1_adapter import DshP1Adapter
    from app.native_dsh_companion_session import NativeDshCompanionSession
    from app.r268_native_speech_backend import NativeSpeechBackend
    token=read_private_token(official_bridge_token_path())
    session=NativeDshCompanionSession(
        DshP1Adapter(BRIDGE,token,timeout=180),
        stable_local_conversation_tab_id())
    session.attach_authoritative_session() # read-only; no paid turn
    if not session.bound or not session.projector.state.get("session_verified"):
        raise RuntimeError("r268_official_dsh_session_not_verified")
    return NativeSpeechBackend(session)

async def serve_gateway(*,bind:str,port:int,tls,paired,backend):
    from websockets.asyncio.server import serve
    from app.r268_lan_gateway import R268LanGateway
    from app.r279_lan_safe_receipts import SafeLanReceipt
    receipts=SafeLanReceipt(PAIRING.parent/"lan-last-turn-receipt.json")
    if hasattr(backend,"set_progress"):
        backend.set_progress(receipts.record)
    # Two-sided opt-in: R299 is inactive on ordinary supervisor starts.
    # Explicitly enable only during coordinated board+Mac physical acceptance.
    incremental_enabled=os.environ.get("DF_LAN_INCREMENTAL_PCM_ENABLED")=="1"
    # Deliberate two-sided opt-in: default runtime remains unchanged.
    # Prewake never runs without the existing explicit USB-owner handoff.
    prewake=None
    if os.environ.get("DF_LAN_PREWAKE_ENABLED")=="1":
        from app.r434_mac_prewake import R434MacPrewake
        prewake=R434MacPrewake()
    gateway=R268LanGateway(backend,paired,diagnostics=receipts.record,
                           incremental_enabled=incremental_enabled,
                           prewake_service=prewake)
    status_path=PAIRING.parent/"lan-gateway-status.json"
    async def emit_safe_status():
        from app.r439_persistent_prewake import decision
        while True:
            alive=sum(1 for job in gateway.backend_jobs.values() if not job.done())
            wake_choice=decision()
            wake_active=(gateway.prewake_service is not None if wake_choice is None
                         else wake_choice)
            state={"schema":1,"transport":"trusted_mac_lan",
                   "active_devices":len(gateway.active)+len(gateway.handshaking),
                   "pending_dsh_jobs":alive,
                   "completed_verified_dsh_offers":gateway.total_real_turns,
                   "device_phase":gateway.ui_phase,
                   "phase_changed_at_unix":gateway.ui_phase_changed_at_unix,
                   "pid":os.getpid(),"updated_at_unix":__import__("time").time(),
                   "server_protocol_ping_enabled":protocol_ping_interval is not None,
                   "prewake_enabled":wake_active,
                   # R489 debug-only counts; no transcript, SSID, keys, IDs.
                   "prewake_idle_reclaims":(
                       gateway.prewake_service.idle_reclaims
                       if gateway.prewake_service else 0),
                   # R533 numeric-only uptime diagnostics. No PCM, names,
                   # tokens, transcripts, MAC or local device identifiers.
                   "prewake_sessions":(
                       gateway.prewake_service.sessions
                       if gateway.prewake_service else 0),
                   "prewake_hits":(
                       gateway.prewake_service.hits
                       if gateway.prewake_service else 0),
                   "prewake_pcm_frames":(
                       gateway.prewake_service.total_pcm_frames
                       if gateway.prewake_service else 0),
                   "prewake_loud_pcm_frames":(
                       gateway.prewake_service.loud_pcm_frames
                       if gateway.prewake_service else 0),
                   "prewake_no_hit_sessions":(
                       gateway.prewake_service.no_hit_sessions
                       if gateway.prewake_service else 0),
                   "prewake_worker_errors":(
                       gateway.prewake_service.worker_errors
                       if gateway.prewake_service else 0),
                   "prewake_last_startup_ms":(
                       gateway.prewake_service.last_worker_startup_ms
                       if gateway.prewake_service else 0)}
            temp=status_path.with_suffix(".tmp")
            temp.write_text(json.dumps(state,separators=(",",":"))+"\n")
            os.chmod(temp,0o600)
            temp.replace(status_path)
            await asyncio.sleep(1.5)
    protocol_ping_interval,protocol_ping_timeout=r301_ws_ping_settings()
    async with serve(gateway.handler,bind,port,
                     process_request=gateway.authorize,ssl=tls,
                     compression=None,max_size=2048,max_queue=8,
                     ping_interval=protocol_ping_interval,
                     ping_timeout=protocol_ping_timeout) as server:
        status_task=asyncio.create_task(emit_safe_status())
        print("R268_TRUSTED_LAN_LISTENER_READY",
              "bind="+bind,"port="+str(port),
              "transport="+("wss" if tls else "localhost-ws"),
              "paired_devices="+str(len(paired)),
              "model_calls_at_startup=0",flush=True)
        try:await server.serve_forever()
        finally:
            status_task.cancel()
            try:await status_task
            except asyncio.CancelledError:pass

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bind",default="127.0.0.1")
    p.add_argument("--port",type=int,default=8877)
    p.add_argument("--tls-cert",type=Path)
    p.add_argument("--tls-key",type=Path)
    args=p.parse_args()
    if not 1024<=args.port<=65535:raise RuntimeError("invalid_r268_port")
    refuse_parallel_usb_owner()
    paired=read_paired()
    tls=make_tls(args.tls_cert,args.tls_key,args.bind)
    backend=build_backend()
    asyncio.run(serve_gateway(bind=args.bind,port=args.port,
                              tls=tls,paired=paired,backend=backend))

if __name__=="__main__":main()
