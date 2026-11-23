"""R37 opt-in real board PCM2, never infer support from code or USB presence.

USB link is owned by the existing verified physical-session process.
The board must explicitly ACK CAPS; no fallback to synthetic sound or second mic.
Producer can send the next Qwen segment while ES8311 consumes prior PCM.
"""
from __future__ import annotations
import base64
import re
import time
from app.h10_usb_pcm_player import PCMTransportError

RATE=24000
BLOCK_SAMPLES=960
MAX_SECONDS=180
CAPS="@@DFPCM2 READY rate=24000 block=960 mode=ring"

class PCM2Unavailable(PCMTransportError):pass

class PCM2UserStopped(PCMTransportError):
    """Physical STOP on ESP32, with verified board receipt."""

class PCM2ResourceUnavailable(PCM2Unavailable):
    """Only an explicit pre-acceptance BEGIN no_psram is safe to replay on PCM1."""

def _verified_line(raw):
    line=raw.decode("ascii","replace").strip()
    if line.startswith("@@DFPCM2 "):return line
    idx=line.find("@@DFPCM2 ")
    if idx>0 and idx<=200 and re.fullmatch(r"[DIWE] \(\s*\d+\) [^\r\n]{0,170}",line[:idx]):
        return line[idx:]
    return ""

def _line(port,expect,*,timeout=6,on_started=None):
    # Short serial timeouts may split a valid receipt anywhere, including ACK digits.
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        pending=getattr(port,"_dfpcm2_pending",b"")
        if b"\n" not in pending:
            try:raw=port.readline()
            except (ValueError,OSError) as exc:raise PCMTransportError("pcm2_usb_disconnected") from exc
            if not raw:continue
            if b"Guru Meditation" in raw or b"Stack overflow" in raw:
                raise PCMTransportError("pcm2_esp32_crash")
            pending+=raw
            if len(pending)>4096:
                setattr(port,"_dfpcm2_pending",b"")
                continue
            setattr(port,"_dfpcm2_pending",pending)
            if b"\n" not in pending:continue
        raw,remain=pending.split(b"\n",1)
        setattr(port,"_dfpcm2_pending",remain)
        if b"Guru Meditation" in raw or b"Stack overflow" in raw:
            raise PCMTransportError("pcm2_esp32_crash")
        line=_verified_line(raw)
        if not line:continue
        if line.startswith("@@DFPCM2 NACK "):
            reason=line[len("@@DFPCM2 NACK "):]
            if expect=="@@DFPCM2 ACCEPTED" and reason=="no_psram":
                raise PCM2ResourceUnavailable("pcm2_begin_no_psram")
            raise PCMTransportError("pcm2_nack_"+reason[:48])
        if line=="@@DFPCM2 USER_STOPPED":
            raise PCM2UserStopped("pcm2_physical_user_stopped")
        if line=="@@DFPCM2 FAILED":raise PCMTransportError("pcm2_hardware_failed")
        if line=="@@DFPCM2 STARTED":
            if on_started:on_started(True)
            continue
        if expect=="@@DFPCM2 PLAYED":
            if line==expect or re.fullmatch(r"@@DFPCM2 PLAYED underruns=\d{1,8} bytes=\d{1,10}",line):return line
        elif line==expect:return line
    raise PCMTransportError("pcm2_timeout_"+expect.replace(" ","_")[:40])

def _send(port,frame):
    try:
        if port.write(frame)!=len(frame):raise PCMTransportError("pcm2_partial_write")
        port.flush()
    except (OSError,ValueError) as err:raise PCMTransportError("pcm2_usb_write_failed") from err

def probe(port):
    # Fake or pre-R37 serial objects are never mistaken for PCM2 hardware.
    if not callable(getattr(port,"readline",None)):
        raise PCM2Unavailable("pcm2_requires_real_usb_readline")
    _send(port,b"@@DFPCM2 CAPS\n")
    try:_line(port,CAPS,timeout=2.5)
    except PCMTransportError as err:raise PCM2Unavailable(str(err)) from err
    return True

def _ensure_previous_pcm2_released(port, *, timeout=2.5):
    """R265: query *real* USB hardware before opening another codec stream.

    The board emits PLAYED before clearing worker/active/speaking flags. A
    new BEGIN at that exact boundary can race the old worker. Never resend
    a timed-out BEGIN/CHUNK; use a bounded read-only STATE instead. Tests'
    mock ports do not expose physical serial ownership and stay unchanged.
    """
    if not (getattr(port, "is_open", False) is True and
            isinstance(getattr(port, "port", None), str)):
        return
    deadline = time.monotonic() + timeout
    saw_state = False
    while time.monotonic() < deadline:
        _send(port, b"@@DFPCM2 STATE\n")
        query_until = min(deadline, time.monotonic() + .65)
        while time.monotonic() < query_until:
            pending = getattr(port, "_dfpcm2_pending", b"")
            if b"\n" not in pending:
                try:
                    raw = port.readline()
                except (ValueError, OSError) as exc:
                    raise PCMTransportError("pcm2_idle_usb_disconnected") from exc
                if not raw:
                    continue
                if b"Guru Meditation" in raw or b"Stack overflow" in raw:
                    raise PCMTransportError("pcm2_idle_esp32_crash")
                pending += raw
                if len(pending) > 4096:
                    setattr(port, "_dfpcm2_pending", b"")
                    continue
                setattr(port, "_dfpcm2_pending", pending)
                if b"\n" not in pending:
                    continue
            raw, remaining = pending.split(b"\n", 1)
            setattr(port, "_dfpcm2_pending", remaining)
            line = _verified_line(raw)
            match = re.fullmatch(
                r"@@DFPCM2 STATE active=([01]) worker=([01]) "
                r"speak=([01]) capture=([01]) h10=([01])", line)
            if match:
                saw_state = True
                if all(value == "0" for value in match.groups()):
                    return
                break
            if line.startswith("@@DFPCM2 NACK "):
                raise PCMTransportError("pcm2_idle_nack")
        if saw_state:
            time.sleep(.04)
    raise PCMTransportError("pcm2_previous_worker_busy" if saw_state
                            else "pcm2_idle_state_unavailable")


class PCM2Reply:
    def __init__(self,port,on_started=None):
        self.port=port;self.seq=0;self.total=0;self.started=False;self.ended=False
        self.on_started=on_started
        self.tail=b""
        self.codec_started=False
        # Local transport timing only; no additional packet, hardware command,
        # PCM gain or retry. Useful when ACK14 stalls on the real board.
        self.ack_roundtrip_s=[]
    def _codec_started(self,value):
        if value and not self.codec_started:
            self.codec_started=True
            if self.on_started:self.on_started(True)
    def start(self):
        if self.started:raise PCMTransportError("pcm2_already_started")
        _ensure_previous_pcm2_released(self.port)
        _send(self.port,b"@@DFPCM2 BEGIN\n")
        _line(self.port,"@@DFPCM2 ACCEPTED")
        self.started=True
        return self
    def send(self,pcm:bytes):
        if not self.started or self.ended:raise PCMTransportError("pcm2_not_active")
        if not isinstance(pcm,bytes) or len(pcm)%2:raise PCMTransportError("pcm2_invalid_samples")
        if (self.total+len(pcm))>MAX_SECONDS*RATE*2:
            raise PCMTransportError("pcm2_reply_too_long")
        self.total+=len(pcm)
        self.tail+=pcm
        while len(self.tail)>=BLOCK_SAMPLES*2:
            self._chunk(self.tail[:BLOCK_SAMPLES*2])
            self.tail=self.tail[BLOCK_SAMPLES*2:]
    def _chunk(self,pcm):
        if not pcm or len(pcm)>BLOCK_SAMPLES*2 or len(pcm)%2:
            raise PCMTransportError("pcm2_bad_chunk")
        frame=(f"@@DFPCM2 CHUNK {self.seq} ".encode("ascii")+
               base64.b64encode(pcm)+b"\n")
        began=time.monotonic()
        _send(self.port,frame)
        # Board can legitimately block up to five seconds on its ring write.
        # 12s is still below its 14s source watchdog; no blind resend of a
        # possibly committed PCM packet, which would break sequence integrity.
        _line(self.port,f"@@DFPCM2 ACK {self.seq}",timeout=12,
              on_started=self._codec_started)
        self.ack_roundtrip_s.append(max(0.,time.monotonic()-began))
        self.seq+=1
    def finish(self,*,on_end=None):
        if not self.started or self.ended:raise PCMTransportError("pcm2_finish_state")
        self.ended=True
        if not self.total:raise PCMTransportError("pcm2_empty")
        if self.tail:
            # Pad only final partial packet. At most 40ms silence; no new words.
            padded=self.tail+b"\0"*(BLOCK_SAMPLES*2-len(self.tail))
            self._chunk(padded)
            self.tail=b""
        _send(self.port,b"@@DFPCM2 END\n")
        _line(self.port,"@@DFPCM2 DRAINING",on_started=self._codec_started)
        # Playback overlaps transfer, but may still have 6s in ring.
        receipt=_line(self.port,"@@DFPCM2 PLAYED",timeout=35,on_started=self._codec_started)
        match=re.fullmatch(r"@@DFPCM2 PLAYED underruns=(\d{1,8}) bytes=(\d{1,10})",receipt)
        underruns=int(match[1]) if match else None
        expected_bytes=((self.total+BLOCK_SAMPLES*2-1)//(BLOCK_SAMPLES*2))*BLOCK_SAMPLES*2
        if not self.codec_started:
            raise PCMTransportError("pcm2_no_current_stream_started_receipt")
        if not match or int(match[2])!=expected_bytes:
            raise PCMTransportError("pcm2_physical_output_mismatch")
        if on_end:on_end()
        # Reuse actual per-packet ACK timings to separate a sporadic USB
        # stall from a consistently slow link. No new USB query or audio IO.
        acks=self.ack_roundtrip_s
        ranked=sorted(acks)
        p95=ranked[(95*len(ranked)+99)//100-1] if ranked else 0.
        slow_seq=max(range(len(acks)),key=acks.__getitem__) if acks else None
        return {"pcm_written":True,"samples":self.total//2,
                "segments":1,"continuous_codec":True,
                "underruns":underruns,
                "pcm2_ack_count":len(acks),
                "pcm2_ack_max_s":round(max(acks,default=0.),3),
                "pcm2_ack_p95_s":round(p95,3),
                "pcm2_ack_over_500ms":sum(t>=0.5 for t in acks),
                "pcm2_ack_slowest_sequence":slow_seq,
                "pcm2_ack_last_sequence":self.seq-1,
                "human_audio_quality_verified":False}
    def cancel(self):
        if not self.started:return
        try:_send(self.port,b"@@DFPCM2 CANCEL\n")
        except PCMTransportError:pass
        self.ended=True
