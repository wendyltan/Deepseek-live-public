"""ESP32-only optional, read-only MultiNet hardware capability probe.
An unrelated MCU, Mac mic, mock status or STT text cannot authorize a wake.
"""
import time
import re

# R228: Actual R225 answers DFWAKE3, without a trustworthy boot/seq.
# Future firmware emits a 64-bit per-boot identifier and monotonic sequence.
# Ready/enabled verifies ONLY the onboard WakeNet model, never a detection.
WAKE3_CAPS=b"@@DFWAKE3 CAPS\n"
WAKE3_STATE=re.compile(
    r'^@@DFWAKE3 STATE model=((?:wn[0-9]+_[a-z0-9_]+)|mn(?:4q8|5q8)_nihaodafeiyu) ready=([01]) enabled=([01]) '
    r'source=esp32_mic commands=0(?: boot=([0-9a-f]{16}))?$')
WAKE3_DETECTED=re.compile(
    r'^@@DFWAKE3 DETECTED model=((?:wn[0-9]+_[a-z0-9_]+)|mn(?:4q8|5q8)_nihaodafeiyu) '
    r'source=esp32_mic boot=([0-9a-f]{16}) seq=([1-9][0-9]{0,8})$')

class Wake3Capability:
    def __init__(self,model,boot=None):
        self.model=model
        self.boot=boot
        self.last_seq=0
    @property
    def sequenced(self):
        return self.boot is not None
    def consume(self,line):
        # Legacy "count=1" is explicitly NOT unique/replay-proof.
        if not self.boot:
            return None
        match=WAKE3_DETECTED.fullmatch(line.strip())
        if match is None or match[1]!=self.model or match[2]!=self.boot:
            return None
        seq=int(match[3])
        if seq<=self.last_seq:
            return None
        self.last_seq=seq
        return seq

def probe_wake3(port,*,clock=time.monotonic,timeout=2.5):
    try:
        if port.write(WAKE3_CAPS)!=len(WAKE3_CAPS):
            return None
        port.flush()
        deadline=clock()+timeout
        while clock()<deadline:
            raw=port.readline()
            if not raw:continue
            line=raw.decode('ascii','replace').strip()
            if line.startswith(('I (','W (','E (','D (')) and '@@DFWAKE3 ' in line:
                line=line[line.index('@@DFWAKE3 '):]
            if 'Guru Meditation' in line or 'Rebooting...' in line:
                return None
            match=WAKE3_STATE.fullmatch(line)
            if match:
                return Wake3Capability(match[1],match[4]) if match[2]=='1' and match[3]=='1' else None
            if line.startswith('@@DFWAKE3 UNAVAILABLE'):
                return None
    except (OSError,ValueError,UnicodeError,AttributeError):
        return None
    return None

READY="@@DFWAKE2 READY source=esp32_multinet mode=standalone_mic"
UNAVAILABLE="@@DFWAKE2 UNAVAILABLE model_or_codec_not_ready"
CAPS=b"@@DFWAKE2 CAPS\n"

def probe(port,*,clock=time.monotonic,timeout=2.5):
    try:
        if port.write(CAPS)!=len(CAPS):return False
        port.flush()
        end=clock()+timeout
        while clock()<end:
            raw=port.readline()
            if not raw:continue
            text=raw.decode('ascii','replace').strip()
            if text.startswith(('I (','W (','E (','D (')) and '@@DFWAKE2 ' in text:
                text=text[text.index('@@DFWAKE2 '):]
            if text==READY:return True
            if text==UNAVAILABLE:return False
            if 'Guru Meditation' in text or 'Rebooting...' in text:return False
    except (OSError,ValueError,UnicodeError,AttributeError):return False
    return False
