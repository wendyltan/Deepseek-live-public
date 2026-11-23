"""Trust only an ESP32 WakeNet-origin post-wake PCM stream, not Mac audio.

DFVOICE2 is a future device protocol; current H10 firmware does NOT emit it.
No raw PCM is logged or persisted; 16kHz mono PCM16 is bounded to 12 seconds.
"""
from __future__ import annotations
import base64
import binascii
import re
import time

FRAME_BYTES=640
MAX_FRAMES=600
MIN_FRAMES=20
BEGIN='@@DFVOICE2 BEGIN rate=16000 max_samples=192000'
CHUNK=re.compile(r'^@@DFVOICE2 PCM (\d{1,3}) ([A-Za-z0-9+/=]{4,1000})$')
END=re.compile(r'^@@DFVOICE2 END samples=(\d{1,6})$')
class PhysicalCaptureError(RuntimeError):pass

def capture_verified_esp_wake(port,wake_receipt,*,clock=time.monotonic,
                              wait_seconds=20,output=None):
    """Only call after the ESP32 capability/boot/seq gate already passed."""
    if (not isinstance(wake_receipt,dict) or
        wake_receipt.get('source')!='esp32_wakenet_device_report' or
        wake_receipt.get('allow_mic_capture') is not True or
        wake_receipt.get('allow_model_request') is not False or
        type(wake_receipt.get('seq')) is not int):
        raise PhysicalCaptureError('ESP_WAKE_RECEIPT_REQUIRED')
    start=clock(); started=False; audio=bytearray();frame=0
    while clock()-start<wait_seconds:
        try:raw=port.readline()
        except (OSError,ValueError) as exc:
            raise PhysicalCaptureError('DEVICE_MIC_USB_INTERRUPTED') from exc
        if not raw:continue
        line=raw.decode('ascii','replace').strip()
        if 'Guru Meditation' in line or 'Rebooting...' in line:
            raise PhysicalCaptureError('DEVICE_REBOOT_DURING_MIC')
        if line==BEGIN and not started:
            started=True
            if output:output('DFVOICE2_MIC_BEGIN')
            continue
        if not started:continue
        end=END.fullmatch(line)
        if end:
            samples=int(end[1])
            if (not MIN_FRAMES<=frame<=MAX_FRAMES or
                samples!=frame*(FRAME_BYTES//2) or samples*2!=len(audio)):
                raise PhysicalCaptureError('DEVICE_MIC_END_MISMATCH')
            if output:output(f'DFVOICE2_COMPLETE frames={frame} sample_count={samples}')
            return bytes(audio)
        match=CHUNK.fullmatch(line)
        if match is None:
            raise PhysicalCaptureError('DEVICE_MIC_UNEXPECTED_PACKET')
        if frame>=MAX_FRAMES or int(match[1])!=frame:
            raise PhysicalCaptureError('DEVICE_MIC_FRAME_SEQUENCE')
        try:data=base64.b64decode(match[2],validate=True)
        except (binascii.Error,ValueError) as exc:
            raise PhysicalCaptureError('DEVICE_MIC_PCM_CORRUPT') from exc
        if len(data)!=FRAME_BYTES:
            raise PhysicalCaptureError('DEVICE_MIC_FRAME_LENGTH')
        audio.extend(data);frame+=1
    raise PhysicalCaptureError('DEVICE_MIC_BEGIN_TIMEOUT' if not started else 'DEVICE_MIC_END_TIMEOUT')
