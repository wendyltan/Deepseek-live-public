"""Mono 60 ms native Opus packets for the P2.0-B loopback (no paid APIs)."""
from __future__ import annotations

import ctypes as C
import ctypes.util
from array import array

FRAME_MS = 60
UPSTREAM_RATE = 16000
DOWNSTREAM_RATE = 24000
MAX_PACKET = 4096


class OpusError(RuntimeError):
    pass


def _lib():
    path = ctypes.util.find_library("opus")
    if not path:
        raise OpusError("libopus unavailable; install libopus on the Gateway Mac")
    lib = C.CDLL(path)
    lib.opus_encoder_create.argtypes = [C.c_int, C.c_int, C.c_int, C.POINTER(C.c_int)]
    lib.opus_encoder_create.restype = C.c_void_p
    lib.opus_encoder_destroy.argtypes = [C.c_void_p]
    lib.opus_encode.argtypes = [C.c_void_p, C.POINTER(C.c_int16), C.c_int, C.POINTER(C.c_ubyte), C.c_int32]
    lib.opus_encode.restype = C.c_int
    lib.opus_decoder_create.argtypes = [C.c_int, C.c_int, C.POINTER(C.c_int)]
    lib.opus_decoder_create.restype = C.c_void_p
    lib.opus_decoder_destroy.argtypes = [C.c_void_p]
    lib.opus_decode.argtypes = [C.c_void_p, C.POINTER(C.c_ubyte), C.c_int32, C.POINTER(C.c_int16), C.c_int, C.c_int]
    lib.opus_decode.restype = C.c_int
    return lib


class OpusCodec:
    def __init__(self, sample_rate: int, mode: str):
        if sample_rate not in (UPSTREAM_RATE, DOWNSTREAM_RATE) or mode not in ("encode", "decode"):
            raise ValueError("unsupported codec configuration")
        self.rate = sample_rate
        self.frame_samples = sample_rate * FRAME_MS // 1000
        self.mode = mode
        self.lib = _lib()
        status = C.c_int(-1)
        if mode == "encode":
            # OPUS_APPLICATION_AUDIO=2049; quality-oriented speech and test tones.
            self.ptr = self.lib.opus_encoder_create(sample_rate, 1, 2049, C.byref(status))
        else:
            self.ptr = self.lib.opus_decoder_create(sample_rate, 1, C.byref(status))
        if not self.ptr or status.value != 0:
            raise OpusError(f"opus {mode} initialization failed: {status.value}")

    def close(self):
        if getattr(self, "ptr", None):
            if self.mode == "encode":
                self.lib.opus_encoder_destroy(self.ptr)
            else:
                self.lib.opus_decoder_destroy(self.ptr)
            self.ptr = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def encode(self, pcm: array) -> bytes:
        if self.mode != "encode" or pcm.typecode != "h" or len(pcm) != self.frame_samples:
            raise OpusError("expected one mono 60ms signed PCM16 frame")
        src = (C.c_int16 * len(pcm))(*pcm)
        dst = (C.c_ubyte * MAX_PACKET)()
        size = self.lib.opus_encode(self.ptr, src, self.frame_samples, dst, MAX_PACKET)
        if size <= 0:
            raise OpusError(f"encode failed: {size}")
        return bytes(dst[:size])

    def decode(self, packet: bytes) -> array:
        if self.mode != "decode" or not (1 <= len(packet) <= MAX_PACKET):
            raise OpusError("bad encoded Opus packet")
        src = (C.c_ubyte * len(packet)).from_buffer_copy(packet)
        dst = (C.c_int16 * self.frame_samples)()
        count = self.lib.opus_decode(self.ptr, src, len(packet), dst, self.frame_samples, 0)
        if count != self.frame_samples:
            raise OpusError(f"unexpected decoded frame size: {count}")
        return array("h", dst)


def upsample_16k_to_24k(pcm: array) -> array:
    """Deterministic linear interpolation; test audio only, not production resampling."""
    if len(pcm) != 960:
        raise OpusError("expected 60ms at 16kHz")
    last = len(pcm) - 1
    out = array("h")
    for i in range(1440):
        base, remainder = divmod(2 * i, 3)
        a, b = pcm[min(base, last)], pcm[min(base + 1, last)]
        out.append(int((a * (3 - remainder) + b * remainder) / 3))
    return out
