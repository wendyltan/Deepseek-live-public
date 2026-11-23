"""H7/H8 bounded human-triggered ESP32 microphone lab.

Only reacts to a physical long-press. Serial audio stays in memory until
Whisper processing, never written as PCM or base64 to a persistent logfile.
No automatic listening, no paid DSH, and no memory modifications.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import os
import tempfile
import re
import sys
import time
import wave
from pathlib import Path

from app.local_voice_preferences import LocalVoicePreferences
# Existing H7 native-device projector may still be in a parallel WIP tree.
# The real physical microphone/Whisper test must remain functional if the
# optional Mac-panel status adapter is temporarily unavailable.
try:
    from app.native_device_voice_snapshot import emit_device_voice_snapshot
except ImportError:
    emit_device_voice_snapshot = None
from app.preset_voice_commands import PresetVoiceSession
from app.stt_local import transcribe_bytes

PORT = os.environ.get("DAFEIYU_USB_SERIAL_PORT", "/dev/cu.usbmodem")
BEGIN = "@@DFVOICE1 BEGIN rate=16000 samples=48000"
END = "@@DFVOICE1 END samples=48000"
COMMAND = b"@@DFVOICE1 PLAY\n"
ARM_COMMAND = b"@@DFVOICE1 ARM\n"
ARM_ACK = "@@DFVOICE1 ARMED"
DISARM_COMMAND = b"@@DFVOICE1 DISARM\n"
FRAMES = 150
FRAME_BYTES = 640
CHUNK = re.compile(r"^@@DFVOICE1 PCM (\d{1,3}) ([A-Za-z0-9+/=]{4,1400})$")
PRIVATE_ROOT = Path("./app/runtime/h8-voice")

class VoiceLabError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code=code

def audio_wav(pcm: bytes) -> bytes:
    out=io.BytesIO()
    with wave.open(out, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(pcm)
    return out.getvalue()

def read_capture(device, *, limit_seconds: float, clock=time.monotonic,
                 output=print) -> bytes:
    """Expect one bounded real-user-origin BEGIN/150 contiguous PCM/END.

    Do not log audio bodies or block forever. Record typed hardware failures.
    Caller owns the already opened Serial object and may reuse it for playback.
    """
    start = clock()
    rows = 0
    pcm=bytearray()
    begun = False
    last_error = None
    # The total transfer includes ~128KiB Base64, so start a separate
    # 30-second transfer deadline only after actual user-initiated BEGIN.
    audio_deadline = None
    while clock()-start < limit_seconds:
        if audio_deadline is not None and clock() > audio_deadline:
            raise VoiceLabError("AUDIO_TRANSFER_TIMEOUT",
                                f"设备已开始录音，但USB传送未能在30秒内完成；收到{rows}/150块。")
        try:
            raw=device.readline()
        except (OSError, ValueError) as e:
            raise VoiceLabError("USB_READ_FAILED",
                                "USB连接中断；检查USB数据线与串口是否仍存在。") from e
        if not raw:
            continue
        # Ignore ESP-IDF ordinary console logs. Preserve only a concise,
        # redacted clue for human diagnostics; do not retain PCM text.
        line=raw.decode("ascii","replace").strip()
        if "Guru Meditation" in line or "stack overflow" in line or "Rebooting..." in line:
            raise VoiceLabError("DEVICE_REBOOT",
                                "录音时设备出现崩溃或重启；请保留硬件画面反馈。")
        if any(code in line for code in ("H7_MIC_INIT_FAILED","H7_MIC_OPEN_FAILED",
                                         "H7_MIC_FAILED","H8_MIC_INIT_FAILED",
                                         "H8_MIC_OPEN_FAILED","H8_MIC_FAILED",
                                         "@@DFVOICE1 FAIL")):
            last_error="MIC_DRIVER_FAILED"
            raise VoiceLabError(last_error,
                                "收到实体麦克风错误日志：初始化、读取或PCM上传未完成。")
        pos=line.find("@@DFVOICE1 ")
        if pos<0:
            continue
        line=line[pos:]
        if not begun:
            if line != BEGIN:
                # The host may have connected mid-stream; can't reconstruct.
                continue
            begun=True
            audio_deadline=clock()+30
            output("H8_CAPTURE_BEGIN · 已收到真实长按触发，开始接收3秒音频")
            continue
        if line == END:
            if rows != FRAMES or len(pcm) != FRAMES*FRAME_BYTES:
                raise VoiceLabError("INCOMPLETE_MIC_PCM",
                                   f"设备标记录音完成，但仅收到{rows}/150块。")
            output("H8_AUDIO_RECEIVED · 48000 samples / 3秒 / no audio retained")
            return bytes(pcm)
        # USB-JTAG carries both the PCM transfer and ordinary ESP-IDF
        # diagnostics. A complete console line BETWEEN two audio packets is
        # normal, not corrupted audio. Embedded/truncated PCM is still an
        # integrity failure and must not be silently skipped.
        if re.match(r"^[IWEDV] \(\d+\) ",line) and "@@DFVOICE1 PCM " not in line:
            continue
        match=CHUNK.fullmatch(line)
        if not match:
            # Only shape diagnostics. Never print/store Base64 payload.
            hint=("device_console_contamination" if "@@DFVOICE1 PCM " in line
                  else "unexpected_usb_record")
            raise VoiceLabError("INVALID_MIC_FRAME",
                               f"录音已开始，但第{rows+1}块不是完整PCM帧；"
                               f"类别={hint}，长度={len(line)}。")
        seq=int(match.group(1))
        if seq != rows:
            raise VoiceLabError("MIC_FRAME_GAP",
                                f"第{rows+1}块丢失或乱序，收到编号{seq}；可能是串口带宽/缓冲问题。")
        try:
            raw_pcm=base64.b64decode(match.group(2),validate=True)
        except (ValueError,binascii.Error) as e:
            raise VoiceLabError("MIC_BASE64_CORRUPT",
                                f"第{seq}块Base64数据损坏，检查USB串口。") from e
        if len(raw_pcm)!=FRAME_BYTES:
            raise VoiceLabError("MIC_FRAME_SIZE_MISMATCH",
                                f"第{seq}块PCM长度错误：{len(raw_pcm)}字节。")
        pcm.extend(raw_pcm)
        rows+=1
        if rows>FRAMES:
            raise VoiceLabError("MIC_FRAME_OVERFLOW","设备传输了超出预算的PCM。")
        if rows in (1,50,100,150):
            output(f"H8_AUDIO_TRANSFER {rows}/150")
    if not begun:
        raise VoiceLabError("NO_PHYSICAL_TRIGGER",
                            "监听窗口结束，但没有收到实体长按触发的录音起始信号。"
                            "先看见Mac显示 USB_LISTENER_READY，再长按人物并讲话。")
    raise VoiceLabError("CAPTURE_INCOMPLETE",
                        f"已收到实体录音开头，但只传回{rows}/150块，无法安全识别。")

def _status(**data):
    """Only bounded machine-readable diagnostics; no PCM, ASR text or names."""
    allow={"ok","stage","intent","code"}
    if any(k not in allow for k in data):
        raise ValueError("private_diagnostic_unapproved_field")
    payload={"schema":1,"unix":time.time(),**data}
    print("VOICE_TRIAL_EVENT "+json.dumps(payload,ensure_ascii=False),flush=True)
    PRIVATE_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    if PRIVATE_ROOT.is_symlink() or PRIVATE_ROOT.stat().st_mode & 0o077:
        raise VoiceLabError("PRIVATE_LOG_UNSAFE","本机实验诊断目录权限不安全；拒绝保存。")
    path=PRIVATE_ROOT/"last-trial.json"
    if path.is_symlink():
        raise VoiceLabError("PRIVATE_LOG_UNSAFE","诊断日志不允许为符号链接。")
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=PRIVATE_ROOT,
                                         prefix=".last-trial-",delete=False) as f:
            tmp=Path(f.name)
            os.fchmod(f.fileno(),0o600)
            json.dump(payload,f,ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)

def _emit(*,transcript:str, reply:str|None,phase:str,preset:bool):
    if emit_device_voice_snapshot is None:
        print("MAC_PANEL_STATUS_UNAVAILABLE · optional WIP connector not installed",flush=True)
        return
    try:
        emit_device_voice_snapshot(transcript=transcript,reply=reply,
                                   phase=phase,confirmed_stt=True,
                                   confirmed_preset=preset)
    except Exception as e:
        print("MAC_PANEL_STATUS_UNAVAILABLE",type(e).__name__,flush=True)

def arm_physical_mic(device, *, wait_seconds:float=12,
                     clock=time.monotonic, output=print):
    """Do not invite user to press until ESP32 itself confirms RX and arm."""
    try:
        device.write(ARM_COMMAND)
        device.flush()
    except (OSError,ValueError) as e:
        raise VoiceLabError("USB_ARM_WRITE_FAILED",
                            "Mac无法向ESP32发送麦克风准备指令。") from e
    start=clock()
    while clock()-start < wait_seconds:
        try:
            data=device.readline()
        except (OSError,ValueError) as e:
            raise VoiceLabError("USB_ARM_READ_FAILED",
                                "等待设备准备回执时USB中断。") from e
        if not data:
            continue
        line=data.decode("ascii","replace").strip()
        if ARM_ACK in line:
            output("USB_LISTENER_READY · ESP32已确认Mac握手；现在长按人物并立即讲话")
            return
        if "Guru Meditation" in line or "Rebooting..." in line or "stack overflow" in line:
            raise VoiceLabError("ARM_DEVICE_REBOOT",
                                "Mac准备录音期间ESP32崩溃或重启。")
    raise VoiceLabError("USB_ARM_NOT_ACKED",
                        "Mac串口已经打开，但未收到ESP32的ARM确认。"
                        "请先检查设备屏幕是否显示H8，再确认USB线与唯一监听进程。")

def test_once(*,port:str=PORT,timeout:int=180, serial_factory=None,
              transcriber=transcribe_bytes):
    if port!=PORT:
        raise VoiceLabError("PORT_NOT_APPROVED","拒绝连接未经项目确认的串口路径。")
    if serial_factory is None:
        try:
            import serial
        except ImportError as e:
            raise VoiceLabError("PYSERIAL_MISSING","Mac私有Python尚未安装pyserial。") from e
        serial_factory=serial.Serial
    try:
        device=serial_factory(port,115200,timeout=.3)
    except (OSError,ValueError) as e:
        raise VoiceLabError("USB_OPEN_FAILED",
                            "无法打开ESP32串口：设备未连接，或被其他监听程序占用。") from e
    try:
        # Existing board uses USB Serial/JTAG. Keep default signals deasserted.
        if hasattr(device,"dtr"): device.dtr=False
        if hasattr(device,"rts"): device.rts=False
        print("USB_PORT_OPEN · 正在确认ESP32麦克风准备状态...",flush=True)
        arm_physical_mic(device)
        pcm=read_capture(device,limit_seconds=timeout)
        wav=audio_wav(pcm)
        try:
            result=transcriber(wav,"audio/wav",PRIVATE_ROOT/"stt-tmp")
        except Exception as e:
            # Only type of failure is shown, never raw PCM or uploaded audio.
            raise VoiceLabError("WHISPER_FAILED",
                                f"已收到48000采样，但Mac本地Whisper识别失败（{type(e).__name__}）。") from e
        if not isinstance(result,dict) or not isinstance(result.get("text"),str):
            raise VoiceLabError("WHISPER_INVALID","本地语音识别返回格式错误。")
        utterance=result["text"].strip()
        print("WHISPER_RESULT "+json.dumps({"engine":result.get("engine"),
            "text":utterance,"audio_seconds":result.get("audio_seconds"),
            "stt_seconds":result.get("stt_seconds")},ensure_ascii=False),flush=True)
        if not utterance:
            raise VoiceLabError("WHISPER_NO_SPEECH","收到了录音，但Whisper未识别出有效语句。")
        # One physical PTT = one bounded local test conversation. This test
        # never writes actual long-term memory or calls a paid DSH agent.
        session=PresetVoiceSession("physicalusbH8test",LocalVoicePreferences())
        decision=session.handle(utterance,session_id=session.session_id,
                                verified_stt=True)
        print("PRESET_CLASSIFIED "+json.dumps({"intent":decision.intent,
            "origin":decision.source,"model_needed":decision.live_model_needed,
            "reply":decision.reply},ensure_ascii=False),flush=True)
        _emit(transcript=utterance,reply=decision.reply,phase="idle",
              preset=not decision.live_model_needed and bool(decision.reply))
        if decision.intent!="wake":
            print("NO_DEVICE_PLAYBACK · 仅唤醒词会触发当前固定Qwen样本；未调用真实DSH。",flush=True)
            return {"result":"recognized_without_playback","intent":decision.intent}
        try:
            device.write(COMMAND)
            device.flush()
        except (OSError,ValueError) as e:
            raise VoiceLabError("USB_PLAY_SEND_FAILED","识别到唤醒词，但USB播放指令发送失败。") from e
        print("ESP32_PRESET_PLAY_REQUESTED · 等待设备真实扬声器回执",flush=True)
        started=False
        wrote=False
        until=time.monotonic()+17
        while time.monotonic()<until:
            try:
                line=device.readline().decode("utf-8","replace")
            except (OSError,ValueError) as e:
                raise VoiceLabError("USB_PLAY_READ_FAILED","播放期间USB串口断开。") from e
            if "VOICE_PLAY_BEGIN" in line:
                started=True
                _emit(transcript=utterance,reply=decision.reply,
                      phase="speaking",preset=True)
                print("ESP32_SPEAKER_STARTED_CONFIRMED",flush=True)
            elif "VOICE_PCM_WRITTEN" in line:
                wrote=True
                print("ESP32_SPEAKER_PCM_WRITTEN · 仍须人耳确认响度",flush=True)
                _emit(transcript=utterance,reply=decision.reply,
                      phase="idle",preset=True)
                break
            elif any(x in line for x in ("VOICE_WRITE_FAILED","VOICE_CODEC_")):
                raise VoiceLabError("ESP32_PLAYBACK_FAILED","板载Codec/I²S回放报错。")
        if not (started and wrote):
            raise VoiceLabError("ESP32_PLAYBACK_NO_ACK",
                                "已发送USB播放请求，但未收到完整实体扬声器回执。")
        return {"result":"physical_pcm_written","intent":"wake"}
    finally:
        # A previously completed/aborted test must never leave the physical
        # avatar armed for a surprise long-press.
        try:
            device.write(DISARM_COMMAND)
            device.flush()
        except (OSError,ValueError):
            pass
        device.close()

def main():
    parser=argparse.ArgumentParser(description="human-triggered H7/H8 local PTT lab")
    parser.add_argument("--timeout",type=int,default=180)
    parser.add_argument("--port",default=PORT)
    opts=parser.parse_args()
    if not 30<=opts.timeout<=300:
        parser.error("--timeout must be 30..300")
    try:
        result=test_once(port=opts.port,timeout=opts.timeout)
        _status(ok=True,stage=result["result"],intent=result["intent"])
    except VoiceLabError as e:
        print(f"VOICE_TEST_FAILED [{e.code}]：{e}",file=sys.stderr,flush=True)
        _status(ok=False,code=e.code)
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("VOICE_TEST_CANCELLED 用户主动结束，未保存音频。",flush=True)
        raise SystemExit(130)

if __name__=="__main__":
    main()
