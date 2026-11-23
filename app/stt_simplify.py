"""macOS native ICU Traditional→Simplified conversion for local STT output.

No network service, third-party package, heuristic character substitutions, or
transmission of microphone transcript. Uses CoreFoundation CFStringTransform.
"""
from __future__ import annotations

import ctypes
import sys
from functools import lru_cache

UTF8 = 0x08000100  # kCFStringEncodingUTF8


@lru_cache(maxsize=1)
def _core_foundation():
    if sys.platform != "darwin":
        raise RuntimeError("macOS Chinese text normalization is unavailable")
    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    ptr = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ptr, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ptr
    cf.CFStringCreateMutableCopy.argtypes = [ptr, ctypes.c_long, ptr]
    cf.CFStringCreateMutableCopy.restype = ptr
    cf.CFStringTransform.argtypes = [ptr, ptr, ptr, ctypes.c_bool]
    cf.CFStringTransform.restype = ctypes.c_bool
    cf.CFStringGetLength.argtypes = [ptr]
    cf.CFStringGetLength.restype = ctypes.c_long
    cf.CFStringGetMaximumSizeForEncoding.argtypes = [ctypes.c_long, ctypes.c_uint32]
    cf.CFStringGetMaximumSizeForEncoding.restype = ctypes.c_long
    cf.CFStringGetCString.argtypes = [ptr, ptr, ctypes.c_long, ctypes.c_uint32]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFRelease.argtypes = [ptr]
    cf.CFRelease.restype = None
    return cf


def to_simplified(text: str) -> str:
    """Convert the locally recognized phrase, not the user message history."""
    if not isinstance(text, str) or len(text) > 1200 or "\0" in text:
        raise ValueError("invalid STT text")
    if not text:
        return text
    cf = _core_foundation()
    original = transformed = transform_name = None
    try:
        original = cf.CFStringCreateWithCString(None, text.encode("utf-8"), UTF8)
        if not original:
            raise ValueError("cannot create CFString")
        transformed = cf.CFStringCreateMutableCopy(None, 0, original)
        transform_name = cf.CFStringCreateWithCString(None, b"Traditional-Simplified", UTF8)
        if not transformed or not transform_name or not cf.CFStringTransform(
                transformed, None, transform_name, False):
            raise ValueError("cannot convert text to simplified Chinese")
        length = cf.CFStringGetMaximumSizeForEncoding(
            cf.CFStringGetLength(transformed), UTF8) + 1
        if length > 16_384:
            raise ValueError("normalized STT text exceeds safe buffer")
        buffer = ctypes.create_string_buffer(length)
        if not cf.CFStringGetCString(transformed, buffer, length, UTF8):
            raise ValueError("cannot encode normalized text")
        return buffer.value.decode("utf-8")
    finally:
        for value in (transform_name, transformed, original):
            if value:
                cf.CFRelease(value)
