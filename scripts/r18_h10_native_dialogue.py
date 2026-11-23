"""R18 explicit real human conversation: ESP32 MIC -> Whisper -> native DSH -> local Qwen3 -> H10 speaker.

Manual opt-in only. No automatic listening, no passive DSH charges,
no token on ESP32, no second Agent, no pretend hardware playback.
Existing DshP1Adapter keeps one genuine official Session for all rounds.
Private mic PCM never persisted; only the local Native Companion status
snapshot contains the explicitly uttered text and final verified answer.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import select
import sys
import stat
import time
from threading import Event,Thread
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.dsh_p1_adapter import DshP1Adapter,DshUnavailable,SpeechOnlyDshP1Adapter
from app.native_dsh_companion_session import NativeDshCompanionSession
from app.h10_usb_pcm_player import send_verified_pcm,PCMTransportError
from app.esp_pcm2_stream import probe as probe_pcm2,PCM2Reply,PCM2Unavailable,PCM2ResourceUnavailable,PCM2UserStopped
from app.voice_preset_pcm_cache import cached_pcm
from app.voice_spoken_text import prepare_spoken_text
from app.voice_preprocessor import spoken_only
from app.local_weather_chikan import accepts as accepts_local_weather,current_chikan_weather,WeatherUnavailable
from app.preset_voice_commands import classify
from app.companion_local_commands import command_for_transcript,execute_local_command
from app.voice_memory_candidates import offer_candidate
from app.r38_memory_loop import auto_remember
from app.r141_explicit_voice_memory import (
    explicit_target, is_explicit_memory_command, store_explicit_fact,
    answer_name_question, normalize_fact)
from app.r38_memory_retrieval import safe_context,facts_for_query
from app.r38_board_telemetry import query_telemetry
from app.r38_board_wake_proof import probe as probe_wake2, probe_wake3
from app.r39_pcm2_progressive import stream_sentence_to_pcm2
from app.voice_stable_pcm2 import play_buffered_short
from app.stt_local import transcribe_bytes, NoSpeechDetected
from scripts import r14_h8_voice_trial as recorder
from app.h11_checked_tts import synthesize as checked_tts, CheckedTTSError
from app.h11_motion_phase_preview import apply_verified_device_phase
from app.h12_explicit_memory_voice import explicit_query, lookup_explicit_memory, short_spoken_memory
from app.h13_postwake_capture import capture_verified_esp_wake,PhysicalCaptureError
from app.h28_hold_to_talk_capture import receive as capture_hold_mic, probe as probe_hold_mic, PhysicalHoldCaptureError
from app.h28_audio_tempo import adapt_pcm,AudioTempoError
from app.esp_mic_quality import pcm_level, normalize_for_asr
from app.r237_wake_speech_gate import wake_capture_block,wake_transcript_block
from app.native_session_search_control import apply_pending_search
from app.native_session_model_control import apply_pending_model
from app.r136_usb_owner_lines import OwnedLinePort
from app.r136_owner_screen_control import consume_screen_request
from app.r142_trigger_owner_apply import consume_request as consume_trigger_request
from app.r151_trigger106_owner import consume_request as consume_trigger106_request
from app.r172_trigger_snapshot_owner import consume_snapshot as consume_trigger_snapshot
from app.native_voice_model_command import handle_voice_model_command
from app.native_session_reconnect_control import apply_pending_reconnect
from app.voice_continuous_pcm2 import stream_phrases_to_pcm2
from app.r90_voice_prosody_plan import rebalance_phrases
from app.r141_voice_phrase_boundaries import natural_segments
from app.r252_stable_voice_phrases import stable_voice_plan
from app.r254_safe_board_rearm import recover_stale_board_idle, read_wake_status
from app.h12_esp_motion_link import H12MotionLink,ESPMotionUnavailable
from app.h11_device_event_gate import probe_device_wake, wait_for_device_wake, DeviceEventError

BRIDGE="http://127.0.0.1:3080"
QWEN="http://127.0.0.1:8906"
PORT=recorder.PORT
def stable_local_conversation_tab_id():
    """One owner-only 32-hex native tab across voice worker restarts.

    A new random tab on every launch used up all 64 in-memory Harness
    conversation bindings. This ID is NOT a DSH session or a model token.
    """
    from uuid import uuid4
    root=Path.home()/"Library/Application Support/Deepseek-live/companion-native"
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if root.is_symlink():raise ValueError("voice_owner_root_symlink")
    state=root/"voice-tab-identity.json"
    if state.is_symlink():raise ValueError("voice_owner_identity_symlink")
    if state.exists():
        info=state.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or info.st_uid!=os.getuid():
            raise ValueError("voice_owner_identity_permissions")
        data=json.loads(state.read_text("utf8"))
        ident=data.get("tab_id")
        if data.get("schema")!=1 or not re.fullmatch(r"[0-9a-f]{32}",str(ident)):
            raise ValueError("voice_owner_identity_invalid")
        return ident
    ident=uuid4().hex
    import tempfile
    with tempfile.NamedTemporaryFile(dir=root,mode="w",prefix=".voice-tab-",delete=False) as fp:
        os.fchmod(fp.fileno(),0o600)
        json.dump({"schema":1,"tab_id":ident},fp)
        fp.flush();os.fsync(fp.fileno())
        stage=Path(fp.name)
    # Never replace an existing valid session identity from another worker.
    try:
        if state.exists():raise ValueError("voice_tab_created_by_another_process")
        os.link(stage,state)
    finally:stage.unlink(missing_ok=True)
    return ident

# Private, read-only-to-app state. No token, audio, transcript or fake offline status.
DEVICE_LINK_FILE=Path.home()/"Library/Application Support/Deepseek-live/companion-native/device-link.json"

def write_trusted_device_link(session,*,board_probed:bool,collection_probed:bool):
    if not board_probed or not session.bound:
        raise ValueError("live_real_board_and_official_dsh_session_required")
    target=DEVICE_LINK_FILE
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if target.parent.is_symlink() or target.is_symlink():
        raise ValueError("device_link_file_symlink_not_allowed")
    data={"schema":1,"started_at_unix":time.time(),"session_id":session.projector.session_id,
          "esp32_verified":True,"selected35_verified":bool(collection_probed),"usb_port":"esp32_s3_usb_serial_jtag",
          "voice_source":"esp32_onboard_mic"}
    if not re.fullmatch(r"(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})",data["session_id"]):
        raise ValueError("device_link_session_unverified")
    import tempfile
    with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.device-link-',mode='w',
                                     encoding='utf-8',delete=False) as handle:
        os.fchmod(handle.fileno(),0o600)
        json.dump(data,handle,ensure_ascii=False)
        handle.flush();os.fsync(handle.fileno())
        staged=Path(handle.name)
    os.replace(staged,target)
    return target

VERIFIED_TOKEN_RE=re.compile(r"^[a-zA-Z0-9_\-]{8,128}$")

def read_private_token(file:Path):
    if not file.is_absolute() or file.is_symlink():
        raise ValueError("bridge_token_path_unsafe")
    info=file.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or info.st_uid!=os.getuid():
        raise ValueError("bridge_token_permissions_invalid")
    secret=file.read_text(encoding="utf-8").strip()
    if not 32<=len(secret)<=256:
        raise ValueError("bridge_token_invalid")
    return secret

def official_bridge_token_path():
    """Inspect the user's installed DSH Web profile, NOT a guessed token."""
    explicit=os.environ.get('DAFEIYU_DSH_BRIDGE_TOKEN_FILE')
    if explicit:
        token_path=Path(explicit)
        if not token_path.is_absolute() or token_path.is_symlink():
            raise ValueError('dafeiyu_bridge_token_path_invalid')
        return token_path
    dsh_home=os.environ.get('DAFEIYU_HOME','').strip()
    for cand_home in ([Path(dsh_home).expanduser()] if dsh_home else [])+[
        Path.home()/'Library/Application Support/Deepseek-live/my-companion',
        Path.home()/'Library/Application Support/Deepseek-live/companion-public',
    ]:
        for tok_name in ('bridge.token','deepseek-live-bridge.token'):
            cand_tok=cand_home/'secrets'/tok_name
            if cand_tok.is_file() and not cand_tok.is_symlink():
                return cand_tok
    profile=Path.home()/".dsh/profiles/web/cordis.patch.yml"
    if profile.is_symlink() or not profile.is_file() or profile.stat().st_uid!=os.getuid():
        raise ValueError("official_bridge_profile_unavailable")
    matches=[row.split(":",1)[1].strip().strip("\"'") for row in
             profile.read_text("utf-8").splitlines()
             if row.lstrip().startswith("bridgeTokenFile:")]
    if len(matches)!=1 or not matches[0].startswith("/"):
        raise ValueError("official_bridge_token_path_unavailable")
    return Path(matches[0])

from contextlib import contextmanager
from app.esp_usb_serial_locator import resolve_esp32_port

@contextmanager
def open_physical_h10_serial():
    """Open without pyserial's default asserted DTR/RTS reset pulse.

    On ESP32-S3 USB-Serial/JTAG the old Serial(PORT,...) constructor first
    opened with both control lines asserted, and only later deasserted them.
    That can strand the chip at DOWNLOAD mode across repeated launchd starts.
    """
    import serial
    port=serial.Serial(port=None,baudrate=115200,timeout=.3,
                       write_timeout=1.0,rtscts=False,dsrdtr=False)
    try:
        port.dtr=False
        port.rts=False
        # Resolve each time, not once at service startup: changing a USB-C
        # cable, hub or socket changes the macOS modem suffix.
        # VID/PID and single-device checks prevent borrowing another modem.
        port.port=resolve_esp32_port()
        port.open()
        yield port
    finally:
        port.close()

H10_VERSION_ACK = "@@DFPCM1 VERSION=1 H10"
H10_READY_MARKERS = ("H9_USB_CONTROL_READY", "H10_USB_CONTROL_READY")
H10_KNOWN_LOG_PREFIXES = ("I (", "W (", "E (", "D (")


def _h10_acknowledgment(line: str) -> bool:
    """Accept exact ESP32 version reply, optionally prefixed by IDF console.

    On the real H10 USB-JTAG stream an IDF log tail was physically observed
    fused with the answer: 'I (3589) main_task@@DFPCM1 VERSION=1 H10'.
    Only a true suffix after a recognised IDF log prefix can qualify;
    unrelated text, incomplete values or the older H9 response cannot.
    """
    line = line.strip()
    if line == H10_VERSION_ACK:
        return True
    if not line.endswith(H10_VERSION_ACK):
        return False
    prefix = line[:-len(H10_VERSION_ACK)]
    return prefix.startswith(H10_KNOWN_LOG_PREFIXES) and 0 < len(prefix) <= 240


def confirm_h10_board(port, *, now=time.monotonic, output=print):
    """Bounded, read-only H10 protocol probe: no mic or model request.

    USB open can reset the board; don't send until driver ready or sufficient
    startup time elapsed. The version request is idempotent and retryable,
    unlike native DSH /submit and unlike microphone ARM.
    """
    begun = now()
    initialized = False
    # R266: after a USB replug an already-running ESP32 need not replay its
    # one-time boot banner. Don't force 12 seconds of silent waiting before
    # asking the exact read-only H10 VERSION question.
    while now() - begun < 1.2:
        line = port.readline().decode("ascii", "replace").strip()
        if any(marker in line for marker in H10_READY_MARKERS):
            initialized = True
            break
        if "Guru Meditation" in line or "stack overflow" in line:
            raise ValueError("H10_BOARD_CRASH_AT_STARTUP")
    if not initialized:
        output("R266_USB_FAST_REATTACH_CHECK · read-only version")
        # PySerial writes are unbuffered. tcdrain()/flush() may block forever
        # if USB-Serial/JTAG has stopped draining after a Mac host restart.
        # A bounded write plus exact ACK read avoids a zombie 'running' worker.
        if port.write(b"@@DFPCM1 VERSION\n") != len(b"@@DFPCM1 VERSION\n"):
            raise ValueError("H10_VERSION_WRITE_INCOMPLETE")
        fast_until = now() + 2.0
        fast_tail = ""
        while now() < fast_until:
            line = port.readline().decode("ascii", "replace")
            fast_tail = (fast_tail + line)[-512:]
            if any(_h10_acknowledgment(part)
                   for part in fast_tail.splitlines()[-4:]):
                output("H10_FIRMWARE_ACK_CONFIRMED · fast_reattach version=1")
                return True
            if "Guru Meditation" in line or "stack overflow" in line:
                raise ValueError("H10_BOARD_CRASH_DURING_HANDSHAKE")
        # Cold-boot safety: if the first probe was too early, wait for normal
        # board startup, then use the original three exact-version retries.
        while now() - begun < 12:
            line = port.readline().decode("ascii", "replace").strip()
            if any(marker in line for marker in H10_READY_MARKERS):
                initialized = True
                break
            if "Guru Meditation" in line or "stack overflow" in line:
                raise ValueError("H10_BOARD_CRASH_AT_STARTUP")
    if not initialized:
        output("H10_PREFLIGHT_BOOT_LOG_MISSED · checking explicit board version")
    for attempt in range(1, 4):
        if port.write(b"@@DFPCM1 VERSION\n") != len(b"@@DFPCM1 VERSION\n"):
            raise ValueError("H10_VERSION_WRITE_INCOMPLETE")
        deadline = now() + 3
        # A 0.3s serial readline timeout can fragment an otherwise valid ACK.
        # Accumulate bounded bytes, never loosen the H10 exact-version test.
        ack_tail = ""
        while now() < deadline:
            line = port.readline().decode("ascii", "replace")
            ack_tail = (ack_tail + line)[-512:]
            if any(_h10_acknowledgment(part)
                   for part in ack_tail.splitlines()[-4:]):
                output("H10_FIRMWARE_ACK_CONFIRMED · version=1")
                return True
            if "Guru Meditation" in line or "stack overflow" in line:
                raise ValueError("H10_BOARD_CRASH_DURING_HANDSHAKE")
        output(f"H10_VERSION_ACK_PENDING · harmless retry {attempt}/3")
    raise ValueError("H10_VERSION_ACK_MISSING_AFTER_3_RETRIES_DO_NOT_ARM_MIC")


def refresh_bound_session(native):
    """Refresh UI only from the SAME native DSH Session /session receipt.

    This is a read-only scoped request; it never requests a model, tool,
    microphone or memory write. A stale or replaced Session loses the green
    connected label rather than silently claiming it is still live.
    """
    receipt=native.adapter.inspect(native.tab_id)
    if (not isinstance(receipt,dict) or receipt.get("ok") is not True or
        receipt.get("session_id")!=native.projector.session_id or
        receipt.get("pending_resume") is True):
        native.projector.state["session_verified"]=False
        native.projector.record_step("error","官方DSH会话已断开，需要重新绑定")
        native.projector.write()
        raise DshUnavailable("native_dsh_session_no_longer_verified")
    choice=receipt.get("last_request") or receipt.get("selected")
    if not isinstance(choice,dict) or not isinstance(choice.get("model"),str):
        raise DshUnavailable("native_dsh_model_status_unverified")
    native.projector.state.update(
        model_id=choice["model"],model_confirmed=True,
        session_verified=True,
        search_supported=receipt.get("search_supported") is True,
        search_enabled=receipt.get("search_enabled") is True,
        # Writing a fresh file with an old JSON timestamp is not a heartbeat:
        # SwiftUI rejects it after 30s. Refresh ONLY after a real /session
        # receipt verifies the same native Session and model origin.
        updated_at_unix=native.projector.clock())
    native.projector.write()
    return receipt


def wait_for_explicit_turn(native,index,count,*,stdin=None,
                           readiness=select.select,poll_seconds=8,out=print):
    """Interactive TTY + verified DSH heartbeat while idle; never auto ARM."""
    if stdin is None:stdin=sys.stdin
    print(f"会话{index}/{count}：回车 ARM 后长按大肥鱼说话；输入q退出 > ",
          end="",flush=True)
    while True:
        readable,_,_=readiness([stdin],[],[],poll_seconds)
        if readable:
            line=stdin.readline()
            if not line:
                raise EOFError("dialogue_terminal_closed")
            return line.strip()
        refresh_bound_session(native)


def speech_segments(text:str,limit=64):
    """Lossless long-form speech planning with clause-safe Qwen boundaries."""
    if not isinstance(text,str) or not text.strip() or len(text)>8000:
        raise ValueError("voice_reply_text_invalid")
    raw=re.sub(r"\[([^\]]{1,120})\]\(https?://[^)]{1,500}\)",r"\1",text)
    raw=re.sub(r"https?://[^\s]{1,500}","（链接见Mac窗口）",raw)
    raw=re.sub(r"[*#`_~]","",raw).strip()
    return natural_segments(raw,limit=limit)

def real_local_pcm(sentence):
    """Only a complete verified local Qwen PCM or phrase-exact signed cache."""
    verified_cache=cached_pcm(sentence)
    if verified_cache is not None:
        print("R37_LOCAL_PRESET_PCM_CACHE_VERIFIED bytes="+str(len(verified_cache)),flush=True)
        return verified_cache
    result=checked_tts(sentence)
    # Report derived acoustics, never persist/reveal raw PCM or credentials.
    print("LOCAL_TTS_VERIFIED",json.dumps({
        "first_pcm_s":result.first_pcm_s,
        "complete_s":result.complete_s,
        "audio_s":round(len(result.pcm)/(2*24000),2),
        "peak":result.peak,"clipped_samples":result.clipped_samples,
    }),flush=True)
    return result.pcm

def recognize_wake_speech(recog,wav,runtime_root,origin):
    """R243: only a verified auto-wake plus genuine no-speech can auto-rearm.

    Keep all other ASR/codec failures visible and preserve tap/hold semantics.
    No PCM, transcript or paid-provider call is introduced by this adapter.
    """
    if origin=="wake" and recog is transcribe_bytes:
        try:
            return recog(wav,"audio/wav",runtime_root,require_vad=True)
        except NoSpeechDetected as exc:
            raise PhysicalHoldCaptureError("wake_no_speech_no_submit") from exc
    return recog(wav,"audio/wav",runtime_root)


def single_turn(port,native,*,recog=transcribe_bytes,synth=real_local_pcm,
                out=print, device_wake=False,wake_receipt=None,motion_link=None,hold_mic=False,
                speech_rate=1.0,live_pcm2=False,wake3_capability=None):
    projector=native.projector
    def display_motion(phase,source):
        preview=apply_verified_device_phase(native,phase,source=source)
        if motion_link is None:return preview
        try:
            actual=motion_link.apply_verified(phase,preview["animation_id"])
            projector.state["esp32_frame_verified"]=actual["actual_esp32_frame_verified"]
            projector.state["esp32_frame_motion_id"]=actual["motion_id"]
            projector.state["motion_sd_verified"]=actual.get("sd_motion_verified") is True
            projector.write()
        except ESPMotionUnavailable as exc:
            projector.state["esp32_frame_verified"]=False
            projector.state["esp32_frame_motion_id"]=None
            projector.state["motion_sd_verified"]=False
            projector.record_step(phase,"ESP32动画暂不可核实，继续Mac预览")
            projector.write()
            out("ESP32_MOTION_NOT_VERIFIED "+str(exc)[:70])
        return preview
    projector.record_step("idle", "ESP32已检测真实设备唤醒，等待板载录音" if device_wake
                          else "ESP32等待用户点按麦克风；尚未录音")
    projector.write()
    capture_origin={"trigger":"touch"}
    heartbeat_stop=Event()
    heartbeat_thread=None
    if not device_wake:
        recorder.arm_physical_mic(port,output=out)
        # Device serial may wait on a real human finger for several minutes.
        # Check the *same* official DSH session via localhost every ~8s on a
        # separate thread: do not pause the USB PCM stream to do HTTP IO.
        def session_heartbeat():
            was_unavailable=False
            while not heartbeat_stop.wait(3.0):
                try:
                    # Manual reconnect always reuses the existing worker and
                    # is deferred while a native turn is active.
                    apply_pending_reconnect(native,refresh_bound_session,output=out,
                        on_rebind=lambda: write_trusted_device_link(
                            native,board_probed=True,collection_probed=(
                                motion_link is not None and motion_link.enabled)))
                    refresh_bound_session(native)
                    was_unavailable=False
                    apply_pending_search(native,output=out)
                    apply_pending_model(native,output=out)
                except (DshUnavailable,OSError,ValueError):
                    if not was_unavailable:
                        native.projector.state["session_verified"]=False
                        native.projector.record_step("error",
                            "DSH心跳暂不可用；等待人工点击连接（不重新提交旧请求）")
                        native.projector.write()
                        out("R65_DSH_HEARTBEAT_LOST_WAIT_MANUAL_RECONNECT")
                    was_unavailable=True
                    # Keep the physical USB worker alive to accept a
                    # user-clicked reconnect; never retry paid work.
        heartbeat_thread=Thread(target=session_heartbeat,daemon=True,name='dafeiyu-dsh-readonly-heartbeat')
        heartbeat_thread.start()
    def physical_frame_event(message):
        # Only first-frame ESP32-origin local touch/idle receipts may adjust
        # the Mac preview. Never fabricate a DSH fact, tool outcome or model.
        from app.h28_hold_to_talk_capture import VISUAL
        match=VISUAL.fullmatch(message)
        if match is None:return
        source={'TOUCH':'esp32_physical_touch','IDLE':'esp32_physical_idle'}[match[1]]
        item=next((v for v in native.mapping.values() if v['id']==match[2]),None)
        if item is None:return
        native.director.current=item['name']
        projector.state.update(animation=item['name'],animation_id=item['id'],
              animation_role=item['decision'],animation_source=source,
              esp32_frame_verified=True,esp32_frame_motion_id=item['id'])
        projector.write()
        out('REAL_ESP32_LOCAL_FRAME '+match[1]+' '+match[2])
    def device_event(message):
        out(message)
        if message.startswith(("H8_CAPTURE_BEGIN","H28_HOLD_MIC_BEGIN")):
            heartbeat_stop.set()  # no DSH heartbeat during USB microphone transfer
            projector.record_step("listening","ESP32已确认板载麦克风正在接收声音")
            # Physical microphone is streaming 150 USB PCM frames; consuming
            # device ACKs to switch a sprite here would corrupt the recording.
            # Mac may show the verified listening phase, but do NOT issue any
            # board USB animation commands until the full PCM has arrived.
            apply_verified_device_phase(native,"listening",source="esp32_pcm_begin")
    if device_wake:
        # Never issue an ARM command here: the ESP32 has autonomously detected
        # its real WakeNet word and is sending its own bounded post-wake audio.
        def wake_progress(message):
            out(message)
            if message=='DFVOICE2_MIC_BEGIN':
                projector.record_step("listening","ESP32板载唤醒后开始实际拾音")
                # Never steal a packet from device-owned post-wake PCM upload.
                apply_verified_device_phase(native,"listening",source="esp32_pcm_begin")
        pcm=capture_verified_esp_wake(port,wake_receipt,output=wake_progress)
    else:
        try:
            if hold_mic:
                owner_lines=OwnedLinePort(port)
                def on_voice3_origin(trigger,seq):
                    capture_origin["trigger"]=trigger
                    # Only real completed Voice3 PCM can be attributed; the
                    # detection event itself cannot submit any DSH request.
                    projector.state["capture_trigger"]=trigger
                    projector.state["capture_wake_seq"]=seq if trigger=="wake" else None
                    projector.record_step("listening",
                        "板载WakeNet9唤醒后的Voice3录音已核验" if trigger=="wake"
                        else "实体触摸发起的Voice3录音已核验")
                    projector.write()
                pcm=capture_hold_mic(owner_lines,limit_seconds=180,
                    output=device_event,on_physical_frame=physical_frame_event,
                    wake_gate=wake3_capability,on_capture_origin=on_voice3_origin,
                    idle_handler=lambda:(
                        consume_screen_request(owner_lines,native,log=out)
                        or consume_trigger_request(owner_lines,native,log=out)
                        or consume_trigger106_request(owner_lines,native,log=out)
                        or consume_trigger_snapshot(owner_lines,native,log=out)))
            else:
                pcm=recorder.read_capture(port,limit_seconds=180,output=device_event)
        finally:
            heartbeat_stop.set()
            # One physical arm cannot be reused, even if capture/STT fails.
            port.write(recorder.DISARM_COMMAND);port.flush()
    # A physical wake marker is not proof a user subsequently spoke. The
    # 1.02-1.04s captures observed tonight were phantom transcripts, not
    # valid requests. Reject before Whisper and certainly before paid DSH.
    origin=capture_origin["trigger"] if not device_wake else "wake"
    reason=wake_capture_block(len(pcm)/(2*16000),origin)
    if reason:
        out("R237_WAKE_NOT_SUBMITTED "+reason)
        raise PhysicalHoldCaptureError(reason)
    # Numerical quality diagnostics only; never retain private speech PCM.
    out("H30_REAL_BOARD_MIC_QUALITY "+json.dumps(pcm_level(pcm)))
    cleaned,level_adjustment=normalize_for_asr(pcm)
    out("R36_MIC_ASR_GAIN "+json.dumps(level_adjustment))
    projector.record_step("transcribing","实体麦克风录音已结束，正在用本机Whisper识别")
    projector.write()
    display_motion("transcribing",source="esp32_pcm_complete")
    # Only physical wake captures use the preinstalled local Silero VAD.
    # Keep test doubles and physical tap/hold ASR call signatures unchanged.
    recognized=recognize_wake_speech(recog,recorder.audio_wav(cleaned),
                                     recorder.PRIVATE_ROOT/"stt-tmp",origin)
    transcript=recognized["text"].strip()
    reason=wake_transcript_block(transcript,origin)
    if reason:
        out("R237_WAKE_NOT_SUBMITTED "+reason)
        raise PhysicalHoldCaptureError(reason)
    if not transcript or len(transcript)>600:
        raise ValueError("transcript_empty_or_oversized")
    projector.state["user_text"]=transcript[:600]
    projector.write()
    out("H30_ASR_CONTEXT_ADJUSTMENTS "+json.dumps(recognized.get("asr_context_corrections",[])))
    # Diagnostics record only bounded shape, never the user's recognized
    # speech. The active DSH/session projector keeps its own verified context.
    out("VERIFIED_MIC_ASR "+json.dumps({"chars":len(transcript)},ensure_ascii=False))
    previous_fact=getattr(native,"_r141_recent_verified_fact",None)
    explicit_fact=explicit_target(
        transcript,previous=previous_fact[0] if previous_fact else None,
        previous_age_s=time.monotonic()-previous_fact[1] if previous_fact else None,
        verified_stt=True)
    new_candidate=normalize_fact(transcript)
    native._r141_recent_verified_fact=(transcript,time.monotonic()) if new_candidate else None
    name_answer=answer_name_question(transcript,verified_stt=True)
    review_offered=offer_candidate(transcript,verified_stt=True)
    if review_offered:
        out("R37_MEMORY_CANDIDATE_READY_FOR_MANUAL_REVIEW")
    auto_saved=auto_remember(transcript,verified_stt=True)
    if auto_saved:
        out("R38_OPTED_IN_VERIFIED_VOICE_FACT_SAVED")
    intent=classify(transcript,verified_stt=True)
    local_action=command_for_transcript(transcript,verified_stt=True)
    requested_memory=explicit_query(transcript,verified_stt=True)
    # A confirmed explicit memory statement is handled locally. Never spend
    # an unrelated provider/model request just to acknowledge saving a fact.
    # A verified physical voice directive changes only the currently bound
    # DSH Session model. Do not waste a model completion to ask the LLM
    # to claim it switched. Plain questions still follow the chat route.
    model_command_reply=handle_voice_model_command(native,transcript,output=out)
    if model_command_reply is not None:
        reply=model_command_reply
        projector.preset_result(reply,same_session=True,verified=True)
        projector.write()
        label="local_verified_model_switch_feedback"
    elif is_explicit_memory_command(transcript):
        # In review mode even explicit voice commands must await human approval.
        from app.r305_wifi_memory_review import _mode
        from app.r38_memory_loop import CONFIG
        if _mode(CONFIG) == "review":
            reply=("已整理成待审核建议，请在Mac的我的记忆里确认。"
                   if review_offered else
                   "这句没有形成安全的记忆建议，可在Mac手动添加。")
            label=("local_verified_memory_review_pending" if review_offered
                   else "local_memory_review_no_candidate")
        elif explicit_fact is not None and store_explicit_fact(
                explicit_fact,verified_stt=True):
            reply="好的，记住啦。"
            label="local_verified_explicit_voice_memory_saved"
            out("R141_EXPLICIT_MEMORY_SAVED category="+explicit_fact["category"])
        else:
            reply="这句我没有找到可安全保存的明确称呼或喜好。你可以说，大肥鱼，记住我的名字叫 Wendy。"
            label="local_explicit_memory_not_saved"
            out("R141_EXPLICIT_MEMORY_NOT_SAVED")
        projector.preset_result(reply,same_session=True,verified=True)
        projector.write()
    elif name_answer is not None:
        reply=name_answer
        projector.preset_result(reply,same_session=True,verified=True)
        projector.write()
        label="local_verified_memory_name_lookup"
    elif auto_saved:
        reply="记住啦，我会在之后相关的对话中用到它。"
        projector.preset_result(reply,same_session=True,verified=True)
        projector.write()
        label="local_verified_auto_memory_saved"
    elif requested_memory is not None:
        auto_matches=facts_for_query(requested_memory)
        if auto_matches:
            reply="我记得你之前说过："+"；".join(auto_matches[:3])
            projector.preset_result(reply,same_session=True,verified=True)
            projector.write()
            label="local_verified_memory_recall"
        else:
            lookup=lookup_explicit_memory(requested_memory)
            reply=short_spoken_memory(lookup)
            projector.explicit_memory_result(reply,same_session=True,verified=True)
            projector.write()
            label="user_explicit_local_memory"
    elif accepts_local_weather(transcript):
        # Trusted verified local weather source; known blocked DSH web_fetch
        # pages must not cause repeated unsafe model/tool requests.
        try:
            reply=current_chikan_weather(transcript)
            projector.weather_result(reply,same_session=True,verified=True,available=True)
            label="verified_open_meteo_weather"
            out("R52_WEATHER_VERIFIED_SOURCE Open-Meteo")
        except WeatherUnavailable as exc:
            reply="暂时没能核实当前配置地区的实时天气，不能给你编一个温度。稍后可以再问我一次。"
            projector.weather_result(reply,same_session=True,verified=True,available=False)
            label="local_weather_source_unavailable"
            out("R52_WEATHER_UNAVAILABLE "+str(exc)[:64])
        projector.write()
    elif local_action is not None:
        reply=execute_local_command(local_action)
        projector.preset_result(reply,same_session=True,verified=True)
        projector.write()
        label="local_verified_"+local_action
    elif intent.intent in ("volume_up", "volume_down"):
        # A verified STT phrase is NOT proof that hardware volume changed.
        # R94 has a touch volume control but no acknowledged USB command for
        # this local voice action. Never delegate it to paid DSH chat.
        reply="口头调音量还没有接通 ESP32 硬件确认。请先在屏幕的音量调节页面设置，我不会假装已经调好了。"
        projector.preset_result(reply,same_session=True,verified=True)
        projector.write()
        label="local_volume_unsupported_no_hardware_receipt"
    elif ("记忆文件" in transcript and
          re.search(r"(?:记录|记住|保存|写入).{0,16}记忆文件",transcript)):
        # No verified name in this utterance. Never claim to have written a
        # memory or ask DSH to invent/use a nonexistent remote memory file.
        reply="这句没有包含要保存的具体信息。请再说完整一句，比如，我的名字叫温蒂。请看Mac文字识别是否准确，再确认本地记忆记录。"
        projector.preset_result(reply,same_session=True,verified=True)
        projector.write()
        label="local_memory_ambiguous_request_guidance"
    elif (not auto_saved and name_answer is None and
          any(phrase in transcript for phrase in ("我的名字叫","我名字叫","我叫","请叫我"))):
        # Bad ESP32 ASR sometimes invents an extra tail or dislocates the
        # wake-name punctuation. Never send this to a billable DSH tool that
        # could echo a wrong name or leave the board in 'processing'.
        reply=("我听到你在介绍名字，但语音识别还不够准确。这次没有保存。"
               "请在 Mac 最近会话检查识别文字，然后清楚地说："
               "大肥鱼，帮我记住我的名字叫 Wendy。")
        projector.preset_result(reply,same_session=True,verified=True)
        projector.write()
        label="local_unconfirmed_name_no_memory_write"
        out("R143_UNCONFIRMED_NAME_HELD_FOR_RETRY")
    elif intent.source=="preset" and intent.reply and intent.intent in (
        "wake","identity","help","persona","nothing_to_confirm"
    ):
        reply=intent.reply
        projector.preset_result(reply,same_session=True,verified=True)
        projector.write()
        label="local_verified_preset"
    else:
        display_motion("thinking",source="verified_esp32_transcript")
        context=safe_context(transcript)
        if context:out("R38_MEMORY_CONTEXT_ATTACHED len="+str(len(context)))
        if review_offered:
            # Same already-authorized DSH round, not an extra model request.
            # The proposed text stays only in Mac's private review queue.
            context=(context+"\n" if context else "")+(
                "【本机记忆回执】本轮只生成了待人审核建议，未进入长期记忆；"
                "正常回答提问，不要声称已经记住或每轮反复播报。")
        result=native.chat_once(transcript,memory_context=context) if context else native.chat_once(transcript)
        reply=result["reply"]
        label="official_dsh_verified"
    out("VERIFIED_REPLY_ORIGIN "+label+" chars="+str(len(reply)))
    # Short first phrase lowers time-to-first-voice. Prepare the NEXT local
    # TTS phrase concurrently with current ESP32 playback, without submitting
    # an extra DSH/model turn or discarding any text of the answer.
    # Fixed phrase cache must be checked BEFORE sentence splitting. The long
    # "help" preset exceeded 48 characters and previously missed its cache.
    complete_cached=cached_pcm(reply) is not None
    # R212: preserve original verified DSH reply and conversation UI.
    # Only the spoken copy of an actual native DSH answer can be shortened.
    # Distinct hidden Flash session; no model call for local commands or tests.
    speech_source=reply
    if (label=="official_dsh_verified" and not complete_cached and
            type(native.adapter) is DshP1Adapter):
        # Separate fixed-Flash no-tools Session. One additional model turn
        # only for verified long replies and only if the user enables it.
        # Short replies/presets and tests never enter this branch.
        flash=SpeechOnlyDshP1Adapter(BRIDGE,native.adapter.token,timeout=16)
        preproc_receipts=[]
        def preproc_log(line):
            if (line.startswith('R260_SPEECH_LOCAL_DIGEST ') or
                    line.startswith('R266_SPEECH_STRUCTURED_STEPS ')):
                preproc_receipts.append('LOCAL_DIGEST')
            elif line.startswith('R212_PREPROCESS '):
                preproc_receipts.append(line.split()[1])
            out(line)
        speech_source=spoken_only(reply,transcript,adapter=flash,output=preproc_log)
    spoken_reply=reply if complete_cached else prepare_spoken_text(speech_source)
    # Visible evidence, never confuse a checked box with a successful paid
    # Flash turn. This contains counts/status only, not the prompt or summary.
    from app.voice_preprocessor import settings as spoken_settings
    eligible=(label=="official_dsh_verified" and not complete_cached and
              len(reply)>=spoken_settings().get("min_chars",220) and
              spoken_settings().get("enabled") is True)
    projector.state["voice_preprocessor_last"]=(
        "local_digest" if eligible and 'LOCAL_DIGEST' in locals().get('preproc_receipts',[]) else
        "applied" if eligible and speech_source!=reply else
        "fallback" if eligible else "not_requested")
    projector.state["voice_preprocessor_original_chars"]=len(reply)
    projector.state["voice_preprocessor_spoken_chars"]=len(spoken_reply)
    projector.write()
    # R252: the 0.6B Qwen clone can fade during a single 20-30s request.
    # The same verified speaker reference is reused in short natural phrases.
    # Do not alter trusted DSH reply, sample rate or hardware speaker owner.
    voice_plan=stable_voice_plan(spoken_reply) if live_pcm2 and not complete_cached else None
    # Single continuous local Qwen request and a single physical Codec.
    if (live_pcm2 and not complete_cached and len(spoken_reply.strip())<=150 and
        speech_rate==1.0 and not voice_plan.guarded):
        projector.record_step("voice_generating",
            "本机 Qwen 预缓冲音频后增量播放，等待实体确认")
        projector.write()
        try:
            if probe_pcm2(port):
                def actual_start(is_started):
                    projector.device_playback(started=is_started,verified=True)
                    apply_verified_device_phase(native,"speaking" if is_started else "idle",
                        source="verified_esp32_speaker_start" if is_started else "verified_esp32_speaker_end")
                    projector.write()
                # R208: start after 8s of verified PCM rather than waiting
                # for the whole 15-30s phrase. Single Qwen request / codec,
                # existing PCM2 ACK, cancel and underrun reporting stay intact.
                received=stream_sentence_to_pcm2(
                    spoken_reply,port,on_started=actual_start,
                    startup_chunks=5,min_startup_audio_s=8.0,
                    lift_enabled=True)
                out("R208_SHORT_PCM2_BUFFERED_START seconds="+str(
                    received["audio_telemetry"]["startup_audio_s"]))
                actual_start(False)
                metrics=received["audio_telemetry"]
                projector.state["voice_audio_diagnostics"]=(
                    "短回复 · Qwen "+str(round(received["tts"].complete_s,1))+
                    "秒 · 预存 "+str(metrics["startup_audio_s"])+
                    "秒 · 最大USB发送 "+str(metrics["send_max_s"])+
                    "秒 · 板端下溢 "+str(received["physical"].get("underruns","未知")))
                projector.write()
                out("R119_REAL_PCM2_AUDIO_QUALITY "+
                    json.dumps({"origin":label,"chunks":received["chunks"],
                     "first_tts_s":received["tts"].first_audio_s,
                     "tts_complete_s":received["tts"].complete_s,
                     "hardware_underruns":received["physical"].get("underruns"),
                     "buffer":received["audio_telemetry"]},ensure_ascii=False))
                display_motion("idle",source="verified_esp32_speaker_end")
                return {"intent":intent.intent,"origin":label,"model_called":label=="official_dsh_verified",
                        "answer_chars":len(reply),"board_pcm_written":True}
        except PCM2ResourceUnavailable as exc:
            out("R50_LIVE_PCM2_NO_PSRAM_SAFE_PCM1 "+str(exc)[:65])
        except PCM2Unavailable as exc:
            out("R39_LIVE_PCM2_UNAVAILABLE_SAFE_FALLBACK "+str(exc)[:65])
        # Once real sound has started, errors fail and CANCEL; do not retry
        # or double-submit a model request.

    # R66: long replies use the SAME local reference voice and one physical
    # PCM2 codec, rather than waiting for each full 145-char file before speech.
    # A failed stream cancels in place; never re-send the official DSH turn.
    if (live_pcm2 and not complete_cached and speech_rate==1.0 and
        (len(spoken_reply.strip())>150 or voice_plan.guarded)):
        phrases=list(voice_plan.phrases)
        if 2<=len(phrases)<=16 and not voice_plan.guarded:
            phrases=rebalance_phrases(phrases,favor_consistency=True)
        if 2<=len(phrases)<=16 and all(1<=len(x)<=150 for x in phrases):
            projector.record_step("voice_generating",
                "本地同声线增量合成，长回复连续播放（无付费重试）")
            projector.write()
            try:
                if probe_pcm2(port):
                    def long_started(started):
                        projector.device_playback(started=started,verified=True)
                        apply_verified_device_phase(native,
                            "speaking" if started else "idle",
                            source="verified_esp32_speaker_start" if started
                                else "verified_esp32_speaker_end")
                        projector.write()
                    received=stream_phrases_to_pcm2(
                        phrases,port,on_started=long_started,
                        # R266: human audio failed; one actual five-phrase
                        # stream had 19 board underruns with just 7.04s
                        # of startup PCM. Guarded multi-phrase answers now
                        # prebuffer 10s. Legacy bit-exact long mode retains
                        # 7s; this never changes TTS text or speaker volume.
                        startup_chunks=6,min_startup_audio_s=(
                            10.0 if voice_plan.guarded else 7.0),
                        # Guarded short clauses share ONE gradual gain state
                        # across all clauses (no per-phrase reset/stacking).
                        # Existing legacy long reply stays bit-exact.
                        lift_enabled=voice_plan.guarded)
                    long_started(False)
                    if voice_plan.guarded:
                        out("R252_GUARDED_PCM2_NUMERIC "+json.dumps({
                            "phrase_lengths":[len(x) for x in phrases],
                            "source":received["phrase_source_metrics"],
                            "output":received["phrase_output_metrics"],
                            "gain":received["single_stage_lift"],
                            "hardware_underruns":received["physical"].get("underruns"),
                        },ensure_ascii=False))
                    projector.state["voice_audio_diagnostics"]=(
                        "长回复 · "+str(received["voice_segments"])+"段 · 预存 "+
                        str(received["startup_audio_s"])+"秒 · 最慢USB发送 "+
                        str(received["device_max_send_s"])+"秒 · 板端下溢 "+
                        str(received["physical"].get("underruns","未知")))
                    projector.write()
                    out("R66_LONG_PCM2_CONTINUOUS "+json.dumps({
                        "voice_segments":received["voice_segments"],
                        "chunks":received["chunks"],
                        "tts_wait_s":received["tts_wait_s"],
                        "hardware_underruns":received["physical"].get("underruns"),
                        "elapsed_s":received["elapsed_s"],
                        "startup_audio_s":received["startup_audio_s"],
                        "producer_audio_s":received["producer_audio_s"],
                        "producer_max_gap_s":received["producer_max_gap_s"],
                        "device_max_send_s":received["device_max_send_s"],
                        "first_pcm_ready_s":received["first_pcm_ready_s"],
                        "codec_start_s":received["codec_start_s"],
                        "physical_first_started_s":received["physical_first_started_s"],
                        "source_peak_pcm16":received["source_peak_pcm16"],
                        "source_rms_pcm16":received["source_rms_pcm16"],
                        "source_clipped_samples":received["source_clipped_samples"],
                        "output_bit_exact_source":received["output_bit_exact_source"],
                        "single_stage_lift":received["single_stage_lift"],
                        "phrase_source_metrics":received["phrase_source_metrics"],
                        "phrase_output_metrics":received["phrase_output_metrics"],
                        "max_pcm_boundary_jump":received["max_pcm_boundary_jump"]}))
                    display_motion("idle",source="verified_esp32_speaker_end")
                    return {"intent":intent.intent,"origin":label,
                            "model_called":label=="official_dsh_verified",
                            "answer_chars":len(reply),"board_pcm_written":True}
            except PCM2Unavailable as exc:
                out("R66_LONG_STREAM_NO_PCM2 "+str(exc)[:80])
            # If audio has already started, the controller cancels and
            # propagates errors. Do not replay the text on PCM1.
    # Fewer standalone TTS generations; short clauses too often finish
    # before the next synthesis is ready, causing real PCM2 underruns.
    phrases=[reply] if complete_cached else speech_segments(spoken_reply,limit=145)
    if not complete_cached:
        out("R51_TTS_PHRASE_PLAN "+json.dumps({
            "chars":len(reply),"segments":len(phrases),"max_chars":145}))
    if complete_cached:out("R38_PRESET_EXACT_CACHE_CHOSEN")
    first_audio_wait=time.monotonic()
    stream=None
    try:
        if probe_pcm2(port):
            stream=PCM2Reply(port)
            out("R37_PCM2_PHYSICAL_CAPS_CONFIRMED")
    except PCM2Unavailable as exc:
        out("R37_PCM2_FALLBACK_TO_PCM1 "+str(exc)[:70])
    try:
        with ThreadPoolExecutor(max_workers=1,thread_name_prefix="local-qwen-prefetch") as pool:
            upcoming=pool.submit(synth,phrases[0])
            for i,segment in enumerate(phrases,1):
                projector.record_step("voice_generating",
                    f"本机Qwen3正在合成第{i}段；完整回答显示在Mac")
                projector.write()
                if stream is None or i==1:
                    display_motion("voice_generating",source="verified_native_answer")
                before_tts=time.monotonic()
                samples=upcoming.result()
                out("H30_TTS_SEGMENT_READY index="+str(i)+" length="+str(len(samples)//2)
                    +" tts_wait_seconds="+str(round(time.monotonic()-before_tts,3)))
                if i<len(phrases):
                    upcoming=pool.submit(synth,phrases[i])
                can_level=speech_rate==1.0
                if speech_rate!=1.0:
                    original_length=len(samples)
                    try:
                        samples=adapt_pcm(samples,rate=speech_rate)
                        can_level=True
                        out("H28_PITCH_PRESERVING_TEMPO rate=1.12 duration_before="+
                            str(round(original_length/48000,2))+" duration_after="+
                            str(round(len(samples)/48000,2)))
                    except AudioTempoError as exc:
                        # Do not modify verified original audio if tempo fallback
                        # was required; preserves the R29 integrity contract.
                        out("H29_TEMPO_FALLBACK_FULL_PCM reason="+str(exc)[:70])
                if can_level:
                    # Preserve the single locally generated Qwen PCM waveform:
                    # no extra nonlinear leveler in the verified PCM fallback.
                    out("R208_QWEN_PCM_PASSTHROUGH bytes="+str(len(samples)))
                def hardware_started(started):
                    # IMPORTANT: Never send the speaking sprite before the *real*
                    # board codec reports H10_DYNAMIC_PLAY_BEGIN, not mere TTS
                    # readiness. This fixes mouth movement preceding any audio.
                    # Do not send SD motion commands while waiting on PCM codec
                    # receipts over this same USB port. The old callback blocked
                    # audio receipt on slow SD SHA/first-frame reads and caused
                    # audible segment gaps. Mac projector can change locally.
                    projector.device_playback(started=started,verified=True)
                    apply_verified_device_phase(native,"speaking" if started else "idle",
                        source="verified_esp32_speaker_start" if started else "verified_esp32_speaker_end")
                    projector.write()
                before_usb=time.monotonic()
                try:
                    if stream is not None:
                        if not stream.started:
                            stream.on_started=hardware_started
                            try:
                                stream.start()
                            except PCM2ResourceUnavailable:
                                out("R50_PCM2_BEGIN_NO_PSRAM_PCM1_SAME_AUDIO")
                                stream=None
                        if stream is not None:
                            stream.send(samples)
                            finished={"pcm_written":True,"samples":len(samples)//2}
                        else:
                            finished=send_verified_pcm(port,samples,on_start=hardware_started)
                    else:
                        finished=send_verified_pcm(port,samples,on_start=hardware_started)
                except PCM2UserStopped:
                    raise
                except (PCMTransportError,OSError):
                    if motion_link is not None:
                        display_motion("error",source="verified_voice_error")
                    raise
                if not finished["pcm_written"]:
                    raise PCMTransportError("no_verified_board_pcm_receipt")
                out("H30_PLAYBACK_SEGMENT_END index="+str(i)
                    +" usb_and_playback_seconds="+str(round(time.monotonic()-before_usb,3))
                    +" elapsed_since_first_voice_ready="+str(round(time.monotonic()-first_audio_wait,3)))
                if i==len(phrases) and stream is not None:
                    final=stream.finish(on_end=lambda:hardware_started(False))
                    out("R38_PCM2_REPLY_FINISHED "+json.dumps({
                        "bytes":final["samples"]*2,"hardware_underruns":final.get("underruns")}))
                if i==len(phrases) and motion_link is not None:
                    display_motion("idle",source="verified_esp32_speaker_end")
                out("H10_VERIFIED_PLAYBACK_SEGMENT "+str(i)+
                    " samples="+str(finished["samples"])+
                    " (human sound quality still unverified)")
    except Exception:
        # Streaming failure must stop the board's still-open codec/PCM ring.
        # Never continue a partial reply or claim the answer was played.
        if stream is not None and stream.started:
            stream.cancel()
        raise
    result_intent="explicit_memory_lookup" if requested_memory is not None else intent.intent
    return {"intent":result_intent,"origin":label,"model_called":label=="official_dsh_verified",
            "answer_chars":len(reply),"board_pcm_written":True}

def sync_board_clock(port,*,out=print,now=None,monotonic=time.monotonic):
    """Real Mac-local clock -> board, only when UART is not carrying PCM.

    A bounded ACK confirms it reached firmware; failures keep the board
    time unknown rather than showing a guess. The board only updates its
    volatile display reference, not RTC registers.
    """
    from datetime import datetime
    current=now or datetime.now()
    frame=("@@DFCLOCK1 SET hhmm="+current.strftime("%H%M")+chr(10)).encode("ascii")
    try:
        if port.write(frame)!=len(frame):return False
        port.flush()
        deadline=monotonic()+1.5
        while monotonic()<deadline:
            line=port.readline().decode("ascii","replace")
            if "@@DFCLOCK1 APPLIED" in line:
                out("R36_CLOCK_ACK_VERIFIED")
                return True
            if "@@DFCLOCK1 REJECTED" in line:break
    except (OSError,ValueError,AttributeError):pass
    out("R36_CLOCK_UNVERIFIED")
    return False


def sync_board_rtc(port, *, out=print, now=None, monotonic=time.monotonic):
    """Set local RTC using the original trusted USB owner; check hardware ACK."""
    from datetime import datetime
    current=now or datetime.now()
    weekday=(current.weekday()+1)%7
    packet=("@@DFCLOCK2 SET "+current.strftime("%y%m%d%H%M%S")+str(weekday)+"\n").encode("ascii")
    try:
        if port.write(packet)!=len(packet):return False
        port.flush()
        until=monotonic()+2
        while monotonic()<until:
            line=port.readline().decode("ascii","replace")
            if "@@DFCLOCK2 APPLIED rtc=1" in line:
                out("R61_BOARD_RTC_INDEPENDENT_TIME_VERIFIED")
                return True
            if "@@DFCLOCK2 APPLIED rtc=0" in line:
                out("R61_BOARD_RTC_UNAVAILABLE_VOLATILE_CLOCK_ONLY")
                return False
            if "@@DFCLOCK2 REJECTED" in line:break
    except (OSError,ValueError,AttributeError):pass
    out("R61_BOARD_RTC_UNVERIFIED")
    return False


def report_board_error_stage(port,exc,*,out=print):
    """Only sanitized stage codes reach ESP32: no transcripts or task IDs."""
    if isinstance(exc,DshUnavailable): stage="DSH"
    elif isinstance(exc,PCMTransportError): stage="PCM2"
    elif isinstance(exc,CheckedTTSError): stage="TTS"
    elif isinstance(exc,(recorder.VoiceLabError,PhysicalHoldCaptureError)): stage="MIC"
    elif "transcrib" in str(exc).lower() or "stt" in str(exc).lower(): stage="STT"
    else: stage="UNKNOWN"
    try:
        frame=f"@@DFLINK1 ERROR={stage}\n".encode("ascii")
        port.write(frame);port.flush()
        out("R50_BOARD_ERROR_STAGE "+stage)
    except (OSError,ValueError):
        out("R50_BOARD_ERROR_STAGE_UNAVAILABLE")
    return stage


def sync_board_recent_two(port,projector,*,out=print,full=False):
    """Only last two actual verified exchanges, ephemeral board RAM.

    Restrict plaintext to 105 UTF-8 bytes per cell; never send task IDs,
    tool contents, credentials, or complete session history.
    """
    history=projector.state.get("conversation_preview",[])
    if not isinstance(history,list):return False
    latest=[x for x in history[-2:] if isinstance(x,dict)]
    payload=[]
    for i in range(2):
        item=latest[i] if i<len(latest) else {}
        for j,key in enumerate(("user","assistant")):
            value=item.get(key,"")
            if not isinstance(value,str):value=""
            value=" ".join(value.replace("\x00","").split())
            raw=value.encode("utf-8")[:105].decode("utf-8","ignore").encode("utf-8")
            coded=base64.b64encode(raw).decode("ascii") if raw else "-"
            payload.append(f"@@DFCHAT1 slot={i*2+j} b64={coded}\n".encode("ascii"))
            if full and raw:
                # R62: UTF-8 codepoint-aligned fragments, bounded to 768B.
                # Transport is the existing trusted Mac->ESP32 session only.
                data=value.encode("utf-8")[:768].decode("utf-8","ignore")
                blocks=[];block=b""
                for char in data:
                    part=char.encode("utf-8")
                    if len(block)+len(part)>90:
                        blocks.append(block);block=b""
                    block+=part
                if block:blocks.append(block)
                for index,chunk in enumerate(blocks):
                    encoded=base64.b64encode(chunk).decode("ascii")
                    payload.append((f"@@DFCHAT2 slot={i*2+j} index={index} "
                                    f"final={int(index==len(blocks)-1)} b64={encoded}\n").encode("ascii"))
    try:
        for frame in payload:
            port.write(frame)
        port.flush()
        out("R57_BOARD_RECENT2_SYNC count="+str(len(latest)))
        return True
    except (OSError,ValueError) as exc:
        out("R57_BOARD_RECENT2_UNAVAILABLE "+type(exc).__name__)
        return False


def report_board_turn(port,verified:bool,*,out=print):
    """Minimal trusted status only, never a replay or transcript broadcast."""
    frame=b"@@DFTURN1 RESULT=ok\n" if verified else b"@@DFTURN1 RESULT=failed\n"
    try:
        port.write(frame);port.flush()
        out("R36_BOARD_TURN_REPORT "+("ok" if verified else "failed"))
    except (OSError,ValueError):
        out("R36_BOARD_TURN_REPORT_UNAVAILABLE")


def main():
    options=argparse.ArgumentParser(description=__doc__)
    options.add_argument("--bridge-token-file",type=Path,
                         help="owner-only file; defaults to the installed official DSH profile")
    options.add_argument("--rounds",type=int,default=6)
    options.add_argument("--esp-wake",action="store_true",
        help="only if ESP32 reports real on-device WakeNet capability; no Mac mic")
    options.add_argument("--esp-motion",action="store_true",
        help="selected35 optional for voice; SD animation commands remain fail-closed")
    options.add_argument("--touch-only",action="store_true",
        help="explicitly launched physical-touch session; no Enter per turn and no passive mic")
    options.add_argument("--hold-mic",action="store_true",
        help="require physical ESP Voice3 press/release capture; reject old 3-second firmware")
    options.add_argument("--auto-hold-mic",action="store_true",
        help="probe physical ESP and choose release-to-send, fallback to old long-hold")
    options.add_argument("--desktop-connect",action="store_true",
        help="publish real ESP32+official DSH bind receipt to private Mac app (no token)")
    options.add_argument("--live-pcm2",action="store_true",
        help="opt-in incremental Qwen PCM2 for single <=150-char reply at 1.0x with physical ACK")
    options.add_argument("--speech-rate",type=float,choices=[1.0,1.12],default=1.0,
        help="optional local pitch-preserving playback tempo, not TTS model generation speed")
    opts=options.parse_args()
    if not 1<=opts.rounds<=8:options.error("one to eight manual rounds only")
    if (opts.hold_mic or opts.auto_hold_mic) and not opts.touch_only:options.error("hold-mic requires physical touch-only")
    if opts.hold_mic and opts.auto_hold_mic:options.error("choose only one hold-mic mode")
    if opts.live_pcm2 and opts.speech_rate!=1.0:
        options.error("incremental codec requires 1.0x tempo; 1.12x stays complete-pitch-preserving")
    if opts.touch_only and opts.esp_wake:
        options.error("select physical touch-only OR genuine ESP WakeNet, not both")
    try:
        token_path=opts.bridge_token_file or official_bridge_token_path()
        token=read_private_token(token_path)
        adapter=DshP1Adapter(BRIDGE,token,timeout=180)
        with open_physical_h10_serial() as port:
            confirm_h10_board(port)  # cannot talk to current H9 by accident
            print("H10_REAL_BOARD_PROTOCOL_CONFIRMED · open_once no_auto_mic",flush=True)
            # Never assume a clock is synchronized solely from sending bytes.
            sync_board_clock(port)
            sync_board_rtc(port)
            session=NativeDshCompanionSession(adapter,stable_local_conversation_tab_id())
            # Bind official Session (no LLM request). No model call before the
            # explicit user press & verified microphone transcript.
            state=session.attach_authoritative_session()
            print("OFFICIAL_DSH_SESSION_BOUND model="+state["model_id"],flush=True)
            # Read-only localhost capability check; does not bind a speech
            # Agent, call a model, touch the microphone, or alter DSH selection.
            try:
                speech=SpeechOnlyDshP1Adapter(BRIDGE,token,timeout=16)
                session.projector.state["voice_preprocessor_supported"]=speech.capabilities()
            except (DshUnavailable,ValueError,OSError):
                session.projector.state["voice_preprocessor_supported"]=False
            session.projector.write()
            tele=query_telemetry(port)
            if tele is not None:
                session.projector.state.update(tele,board_telemetry_at_unix=time.time())
                session.projector.write()
                print("R38_BOARD_TELEMETRY_VERIFIED "+json.dumps(tele),flush=True)
            # User preference: enable search on every verified new DSH session.
            # Toggle receipt is authoritative, never imply extra tool access.
            if state.get("search_supported") is True and state.get("search_enabled") is not True:
                try:
                    enabled=session.adapter.switch_search(session.tab_id,True)
                    if enabled.get("supported") is True and enabled.get("enabled") is True:
                        session.projector.state["search_enabled"]=True
                        session.projector.write()
                        print("R37_SEARCH_DEFAULT_CONFIRMED_ON",flush=True)
                except (DshUnavailable,OSError,RuntimeError) as exc:
                    print("R37_SEARCH_DEFAULT_UNVERIFIED "+type(exc).__name__,flush=True)
            motion_link=H12MotionLink(port) if opts.esp_motion else None
            if motion_link is not None:
                try:
                    verified_motion=motion_link.probe()
                except ESPMotionUnavailable as exc:
                    # The trusted physical board and official DSH are already
                    # verified; unavailable SD *only* disables SD animations.
                    # Never issue/select unverified remote SD motion.
                    session.projector.state["esp32_frame_verified"]=False
                    session.projector.state["esp32_frame_motion_id"]=None
                    session.projector.state["motion_sd_verified"]=False
                    session.projector.record_step("idle","SD动画未就绪，继续触控语音与Flash备用图像")
                    session.projector.write()
                    print("ESP32_MOTION_DEGRADED_VOICE_AVAILABLE "+
                          str(exc)[:110],flush=True)
                    motion_link=None
                else:
                    session.projector.state["motion_sd_verified"]=False
                    session.projector.state["esp32_frame_verified"]=False
                    session.projector.write()
                    print("ESP32_SELECTED35_SD_CAPABILITY_ONLY",verified_motion,flush=True)
            if motion_link is not None:
                # While the verified official DSH stream is actually thinking
                # or invoking tools, push real work-state animations immediately.
                # The previous R27 path only changed motion AFTER DSH returned.
                session.physical_motion_sink=lambda phase,motion: motion_link.apply_verified(phase,motion)
            physical_hold=opts.hold_mic
            if opts.hold_mic or opts.auto_hold_mic:
                try:
                    probe_hold_mic(port,timeout=3 if opts.auto_hold_mic else 8)
                    physical_hold=True
                    print("ESP32_REAL_EXPLICIT_SCREEN_MIC_CONFIRMED (0.1..20 sec)",flush=True)
                except PhysicalHoldCaptureError as exc:
                    if not opts.auto_hold_mic:raise
                    print("ESP32_LEGACY_PHYSICAL_LONG_HOLD_3S",type(exc).__name__,flush=True)
            wake3_capability=None
            board_wake_ready=False
            if physical_hold:
                # The actual R225 firmwares use DFWAKE3. Old MultiNet
                # DFWAKE2 is compatibility only, never fake a Wake3 origin.
                wake3_capability=probe_wake3(port,timeout=4.0)
                board_wake_ready=wake3_capability is not None
                if not board_wake_ready:
                    board_wake_ready=probe_wake2(port,timeout=2.5)
            session.projector.state["wake_capability_verified"]=board_wake_ready
            session.projector.state["wake_sequenced_origin_supported"]=bool(
                wake3_capability is not None and wake3_capability.sequenced)
            verified_pcm2=False
            if opts.live_pcm2:
                try:verified_pcm2=probe_pcm2(port)
                except PCM2Unavailable:pass
            session.projector.state["voice_streaming_enabled"]=bool(opts.live_pcm2 and verified_pcm2)
            session.projector.write()
            # R254: real user STOP may leave the board display phase stuck at
            # voice_generating even though its physical codec is idle. Only
            # clear after the SAME verified USB owner checks no active media;
            # then verify WakeNet can actually listen again. No new SD frame.
            if motion_link is not None and wake3_capability is not None:
                try:
                    repair=recover_stale_board_idle(port,motion_link,output=print)
                    print("R254_STARTUP_WAKE_REARM",repair["reason"],flush=True)
                except (OSError,ValueError,RuntimeError,ESPMotionUnavailable,DeviceEventError) as repair_error:
                    print("R254_STARTUP_WAKE_REARM_UNVERIFIED",
                          type(repair_error).__name__,str(repair_error)[:80],flush=True)
            print("R39_PROGRESSIVE_CODEC_"+("VERIFIED" if verified_pcm2 else "NOT_ENABLED"),flush=True)
            print("R228_BOARD_WAKE_"+(
                "WAKE3_SEQUENCED" if wake3_capability and wake3_capability.sequenced
                else "WAKE3_LEGACY_UNSEQUENCED" if wake3_capability
                else "WAKE2_LEGACY" if board_wake_ready
                else "NOT_INSTALLED_TOUCH_FALLBACK"),flush=True)
            if opts.desktop_connect:
                # Physical board and DSH proof is independent of optional SD.
                sd_verified=bool(motion_link is not None and motion_link.enabled)
                write_trusted_device_link(session,board_probed=True,
                                          collection_probed=sd_verified)
                print("MAC_COMPANION_BOTH_LINKS_CONFIRMED sd_selected35="+
                      str(sd_verified),flush=True)
            gate=probe_device_wake(port) if opts.esp_wake else None
            if gate is not None:
                print("ESP32_ON_DEVICE_WAKENET_READY · no Mac audio capture",flush=True)
            finished_turns=0
            while opts.desktop_connect or finished_turns<opts.rounds:
                i=finished_turns
                if gate is not None:
                    hit=wait_for_device_wake(port,gate,
                            on_heartbeat=lambda:refresh_bound_session(session))
                    print("ESP32_PHYSICAL_WAKE_RECEIPT seq="+str(hit["seq"]),flush=True)
                else:
                    if opts.touch_only:
                        # Invocation of this finite-round test is the explicit
                        # session opt-in; only a real ESP32 screen long-hold
                        # can ever start the board microphone / model path.
                        turn_label=(str(i+1) if opts.desktop_connect else f"{i+1}/{opts.rounds}")
                        print(f"ESP32_TOUCH_ONLY_TURN {turn_label}: tap the on-board MIC to start, tap again to send" if physical_hold else f"ESP32_TOUCH_ONLY_TURN {turn_label}: long-hold avatar to speak; Mac mic prohibited",flush=True)
                    else:
                        key=wait_for_explicit_turn(session,i+1,opts.rounds)
                        if key.strip().lower() in ("q","quit","exit"):break
                        if key.strip():continue
                try:
                    if gate is None:
                        sync_board_clock(port)
                        sync_board_rtc(port)
                    item=single_turn(port,session,device_wake=gate is not None,
                                     wake_receipt=hit if gate is not None else None,
                                     motion_link=motion_link,hold_mic=physical_hold,
                                     speech_rate=opts.speech_rate,live_pcm2=opts.live_pcm2,
                                     wake3_capability=wake3_capability)
                    print("H10_REAL_DIALOGUE_TURN",json.dumps(item,ensure_ascii=False),flush=True)
                    report_board_turn(port,True)
                    sync_board_recent_two(port,session.projector,full=True)
                    finished_turns+=1
                except PCM2UserStopped:
                    # Confirmed user button: do not re-submit DSH/TTS, mark stopped
                    # rather than model failure, and allow next physical request.
                    try:
                        port.write(b"@@DFTURN1 RESULT=stopped\n")
                        port.flush()
                    except (OSError,ValueError):
                        pass
                    # The real PCM2 stop receipt arrives before the worker
                    # necessarily clears all audio flags. R253 previously
                    # left H11 phase=voice_generating indefinitely, which
                    # blocked the onboard WakeNet even with speaking=0.
                    # Phase-only ACK clears the actual BOARD gate; never
                    # infer re-arming from the Mac status or STOP receipt.
                    board_idle_verified=(motion_link is None)
                    if motion_link is not None:
                        try:
                            receipt=motion_link.apply_phase_only("idle")
                            board_idle_verified=receipt.get("display_ack") is True
                            print("R254_STOP_BOARD_IDLE_ACK",board_idle_verified,flush=True)
                            # A state ACK alone isn't proof the wake mic has
                            # already reacquired the codec. Report separately.
                            try:
                                wake_status=read_wake_status(port,duration=2.0)
                                print("R254_STOP_WAKE_READINESS",
                                      int(wake_status["can_listen"]),
                                      wake_status["phase"],flush=True)
                            except (OSError,ValueError,RuntimeError) as diag_error:
                                print("R254_STOP_WAKE_READINESS_UNVERIFIED",
                                      type(diag_error).__name__,flush=True)
                        except (ESPMotionUnavailable,DeviceEventError) as idle_exc:
                            print("R254_STOP_BOARD_IDLE_UNVERIFIED",
                                  str(idle_exc)[:90],flush=True)
                    session.projector.record_step("idle" if board_idle_verified else "error",
                        "用户停止播音，已收到设备待机状态回执" if board_idle_verified
                        else "播音已停止，实体待机回执尚未核实")
                    session.projector.write()
                    print("R51_PHYSICAL_USER_STOPPED",flush=True)
                    finished_turns+=1
                    continue
                except (ValueError,RuntimeError,OSError) as e:
                    # A desktop companion waiting for the user's finger must
                    # NEVER interpret 180s of silence as a broken USB cable,
                    # failed DSH answer, or a billable model retry. Re-ARM
                    # only after a fresh physical board ACK, still no mic.
                    if (opts.desktop_connect and opts.touch_only and
                        ((isinstance(e,recorder.VoiceLabError) and
                          e.code=="NO_PHYSICAL_TRIGGER") or
                         (isinstance(e,PhysicalHoldCaptureError) and
                          str(e)=="no_board_press_or_incomplete_hold_recording"))):
                        print("ESP32_STANDBY_NO_TOUCH · verified idle; rearming same session",flush=True)
                        refresh_bound_session(session)
                        continue
                    # A non-speech post-wake capture must return to idle:
                    # never ask DSH to answer Whisper hallucinations, never
                    # mark it a real tool/answer failure or play an error sound.
                    if (opts.desktop_connect and isinstance(e,PhysicalHoldCaptureError)
                        and str(e).startswith("wake_")
                        and str(e).endswith("_no_submit")):
                        session.projector.record_step(
                            "idle","唤醒有效，但尚未取得可靠的用户讲话，请再次唤醒")
                        session.projector.write()
                        print("R237_WAKE_SPEECH_REJECTED_IDLE",str(e),flush=True)
                        print("R244_WAKE_SILENCE_IDLE_REARM",str(e),flush=True)
                        # This follows a *real completed ESP32 Voice3 PCM* and
                        # a successful local ASR with zero human speech. Never
                        # manufacture a DSH turn/answer or success animation.
                        # Only board phase ACK can confirm that the lingering
                        # "正在识别语音" state has actually been cleared.
                        if motion_link is not None:
                            try:
                                receipt=motion_link.apply_phase_only("idle")
                                print("R244_WAKE_BOARD_IDLE_ACK",
                                      bool(receipt.get("display_ack")),flush=True)
                            except (ESPMotionUnavailable,DeviceEventError) as idle_exc:
                                print("R244_WAKE_BOARD_IDLE_UNVERIFIED",
                                      str(idle_exc)[:90],flush=True)
                        # A voice turn returning to idle must not require a
                        # new SD SELECT/multi-MB frame; the previous R243
                        # attempted an unrecognized provenance and crashed
                        # the whole voice service on every wake silence.
                        session.projector.write()
                        refresh_bound_session(session)
                        continue
                    code = e.code if isinstance(e,CheckedTTSError) else str(e)[:90]
                    print("H10_TURN_FAILED",type(e).__name__,code,flush=True)
                    # Failed/pending DSH tasks are NEVER resubmitted. Preserve
                    # the verified user transcript in the Mac conversation
                    # preview with an explicit failure origin, without inventing
                    # a response or granting a new tool approval.
                    report_board_error_stage(port,e)
                    report_board_turn(port,False)
                    session.projector.fail_current_turn(
                        "实体会话未取得可验证回复；旧任务不自动重试")
                    session.projector.write()
                    error_motion_verified=False
                    if motion_link is not None:
                        try:
                            receipt=motion_link.apply_verified('error','m023')
                            error_motion_verified=bool(receipt.get('actual_esp32_frame_verified'))
                        except ESPMotionUnavailable:
                            print('R34_ERROR_VISUAL_NOT_ACKNOWLEDGED',flush=True)
                    physical_usb_error=(
                        isinstance(e,recorder.VoiceLabError) and
                        e.code in ("USB_ARM_WRITE_FAILED","USB_ARM_READ_FAILED",
                                   "USB_ARM_NOT_ACKED","ARM_DEVICE_REBOOT"))
                    if physical_usb_error or isinstance(e,PCMTransportError) or "USB" in str(e):
                        print("H10_USB_NEEDS_RECHECK stopping",flush=True)
                        break
                    # Device previously rendered error then immediately idle,
                    # so the user never saw the animation. Only when the first
                    # error frame is truly acknowledged hold it briefly; no
                    # retry or fabricated success in this dwell.
                    if error_motion_verified:
                        time.sleep(2.2)
                        print('R60_ERROR_MOTION_VISIBLE_DWELL_S=2.2',flush=True)
                    if motion_link is not None:
                        try:
                            motion_link.apply_verified('idle','m000')
                        except ESPMotionUnavailable:
                            print('R34_IDLE_RECOVERY_UNVERIFIED',flush=True)
                    session.projector.record_step("idle","上一条请求失败，已恢复录音待机")
                    session.projector.write()
                    continue
    except (OSError,ValueError,DshUnavailable,DeviceEventError,ESPMotionUnavailable) as exc:
        print("H10_PREFLIGHT_BLOCKED",type(exc).__name__,str(exc)[:140],flush=True)
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("H10_USER_INTERRUPTED",flush=True)

if __name__=="__main__":main()
