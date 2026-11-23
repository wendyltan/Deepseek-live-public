"""Authenticated caller -> private USB Serial/JTAG -> H10 ES8311 voice playback.

H10 never sees DSH credentials. The caller must pass a verified reply from
NativeDshCompanionSession (and a local Qwen PCM). This object only transfers
16-bit signed 24 kHz mono bytes in bounded 12-second segments and waits for
per-chunk ACK plus actual codec receipt. No default microphone activation,
no filesystem PCM persistence, no hidden fallback to the Mac speaker.
"""
from __future__ import annotations
import base64
import os
import re
import time

BLOCK_SAMPLES=960
MAX_SEGMENT_SAMPLES=24_000*12
MAX_TOTAL_SECONDS=180
PORT=os.environ.get("DAFEIYU_USB_SERIAL_PORT","/dev/cu.usbmodem")
PFX=b"@@DFPCM1 "
ACK=re.compile(r"^@@DFPCM1 ACK (\d+)$")
def _send(device,msg:bytes):
    try:
        n=device.write(msg)
        device.flush()
    except (OSError,ValueError) as err:
        raise PCMTransportError("usb_write_failed") from err
    if n!=len(msg):
        raise PCMTransportError("usb_partial_write")

class PCMTransportError(RuntimeError):
    pass

def _protocol_reply(line: str, expected: str) -> bool:
    """The ESP32 sometimes fuses an IDF log tail and one ACK, as seen on
    real H10 VERSION. Never accept arbitrary prefixes, truncated codes or
    replies for another packet number.
    """
    line=line.strip()
    if line==expected:
        return True
    return (line.endswith(expected) and len(line)>len(expected) and
            len(line)-len(expected)<=240 and
            line.startswith(("I (","W (","E (","D (")))


def _read_expect(device,expected: str,*,timeout:float=8,now=time.monotonic):
    until=now()+timeout
    partial=""
    while now()<until:
        try:raw=device.readline()
        except (OSError,ValueError) as err:
            raise PCMTransportError("usb_read_failed") from err
        if not raw:continue
        # Serial.read_line() may return a partial line on an interrupted USB
        # read; preserve it until newline instead of discarding an ACK tail.
        part=raw.decode("ascii","replace")
        partial+=part
        if len(partial)>800:
            partial=""
            continue
        if "\n" not in partial:continue
        lines=partial.split("\n")
        partial=lines.pop()
        for line in lines:
            line=line.strip()
            if "Guru Meditation" in line or "Rebooting..." in line:
                raise PCMTransportError("esp32_reboot")
            if ("@@DFPCM1 NACK" in line and
                (line.startswith("@@DFPCM1 NACK") or
                 line.startswith(("I (","W (","E (","D (")))):
                raise PCMTransportError("device_rejected_"+line.split("NACK",1)[-1][:38].strip().replace(" ","_"))
            if _protocol_reply(line,expected):
                return
    context=expected.replace("@@DFPCM1 ","").replace(" ","_")
    raise PCMTransportError("device_ack_timeout_"+context)

def _play_single(device,pcm:bytes,*,timeout:float=8,on_start=None):
    if len(pcm)%2 or not 1<=len(pcm)//2<=MAX_SEGMENT_SAMPLES:
        raise PCMTransportError("invalid_segment_length")
    try:
        _send(device,f"@@DFPCM1 BEGIN samples={len(pcm)//2}\n".encode("ascii"))
        _read_expect(device,"@@DFPCM1 READY",timeout=timeout)
        seq=0
        for off in range(0,len(pcm),BLOCK_SAMPLES*2):
            block=pcm[off:off+BLOCK_SAMPLES*2]
            line=f"@@DFPCM1 CHUNK {seq} ".encode("ascii")+base64.b64encode(block)+b"\n"
            _send(device,line)
            _read_expect(device,f"@@DFPCM1 ACK {seq}",timeout=timeout)
            seq+=1
        _send(device,b"@@DFPCM1 END\n")
        _read_expect(device,"@@DFPCM1 RECEIVED",timeout=timeout)
        # A serial ACK is not a human-audible confirmation. Actual board
        # codec playback begins and finishes in its own IDF task.
        playback_started=False
        until=time.monotonic()+30
        while time.monotonic()<until:
            try:raw=device.readline()
            except (OSError,ValueError) as err:
                raise PCMTransportError("usb_playback_read_failed") from err
            if not raw:continue
            line=raw.decode("utf-8","replace")
            if "H10_DYNAMIC_PLAY_BEGIN" in line:
                playback_started=True
                if on_start is not None:on_start(True)
            if "H10_DYNAMIC_WRITE_FAILED" in line or "H10_DYN_TASK_FAILED" in line:
                raise PCMTransportError("board_codec_write_failed")
            if "H10_DYNAMIC_PCM_WRITTEN" in line:
                if not playback_started:
                    raise PCMTransportError("unverified_playback_start")
                if on_start is not None:on_start(False)
                return {"samples":len(pcm)//2,"chunks":seq,
                        "codec_pcm_written":True,"human_audio_quality_verified":False}
        raise PCMTransportError("hardware_playback_receipt_timeout")
    except PCMTransportError:
        # Abort only if the protocol has not already handed data to playback.
        try:_send(device,b"@@DFPCM1 CANCEL\n")
        except PCMTransportError:pass
        raise

def send_verified_pcm(device,pcm:bytes,*,on_start=None):
    if not isinstance(pcm,bytes) or not pcm or len(pcm)%2 or len(pcm)>MAX_TOTAL_SECONDS*24_000*2:
        raise PCMTransportError("invalid_full_reply_pcm")
    parts=[]
    size=MAX_SEGMENT_SAMPLES*2
    for offset in range(0,len(pcm),size):
        parts.append(_play_single(device,pcm[offset:offset+size],on_start=on_start))
    return {"segments":len(parts),"samples":sum(p["samples"] for p in parts),
            "pcm_written":all(p["codec_pcm_written"] for p in parts),
            "acoustic_quality_verified":False}
