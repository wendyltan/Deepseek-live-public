"""R526: slow, attenuation-only smoothing of fully buffered R503 speech.

The complete R525-leveled phrase may have high local loudness even when
its whole-phrase RMS matches the other phrases. This code reduces only
sustained 200ms high-energy windows. On the Mac's Python 3.12 use the
built-in C audioops for 10ms-ramped output to avoid costly sample loops.
A pure-Python fallback remains for newer Python versions.
"""
from __future__ import annotations

from array import array
import math
import sys
import warnings

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import audioop
except ImportError:
    audioop = None

FRAME_SAMPLES = 4800  # 200ms at mono 24kHz
MINI_SAMPLES = 240    # 10ms; gain changes are only a fraction of a percent
# R635: measured real long replies repeatedly ducked 54/47 separate 200ms
# windows; a 50% step toward 0.64x can sound like a sudden quiet sentence.
# Keep attenuation-only protection but cap one 200ms change to <8%;
# avoid ducking normal spoken syllables near 4k RMS.
# Leave ordinary R503 speech and emphasis below 6400 RMS untouched.
START_DUCK_RMS = 6400
MIN_GAIN = 0.78
SMOOTH = 0.35


def _gain_for_level(rms: float) -> float:
    return max(MIN_GAIN, START_DUCK_RMS / rms) if rms > START_DUCK_RMS else 1.0


def _native_smooth(pcm: bytes) -> tuple[bytes, int]:
    frames = [pcm[i:i + FRAME_SAMPLES * 2]
              for i in range(0, len(pcm), FRAME_SAMPLES * 2)]
    levels = [_gain_for_level(audioop.rms(frame, 2)) for frame in frames]
    parts = []
    previous = 1.0
    corrected = 0
    for frame, wanted in zip(frames, levels):
        next_gain = previous + SMOOTH * (wanted - previous)
        if next_gain < 0.995:
            corrected += 1
        for at in range(0, len(frame), MINI_SAMPLES * 2):
            block = frame[at:at + MINI_SAMPLES * 2]
            mid = (at + len(block) / 2) / len(frame)
            gain = previous + (next_gain - previous) * mid
            parts.append(block if gain >= 0.999999 else audioop.mul(block, 2, gain))
        previous = next_gain
    return b"".join(parts), corrected


def _python_smooth(pcm: bytes) -> tuple[bytes, int]:
    values = array("h")
    values.frombytes(pcm)
    if sys.byteorder != "little":
        values.byteswap()
    count = len(values)
    levels = []
    for start in range(0, count, FRAME_SAMPLES):
        section = values[start:start + FRAME_SAMPLES]
        rms = math.sqrt(sum(x * x for x in section) / len(section))
        levels.append(_gain_for_level(rms))
    previous = 1.0
    corrected = 0
    for frame, wanted in enumerate(levels):
        next_gain = previous + SMOOTH * (wanted - previous)
        if next_gain < 0.995:
            corrected += 1
        start = frame * FRAME_SAMPLES
        end = min(start + FRAME_SAMPLES, count)
        for i in range(start, end):
            portion = (i - start + 1) / (end - start)
            gain = previous + (next_gain - previous) * portion
            values[i] = round(values[i] * gain)
        previous = next_gain
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes(), corrected


def smooth_buffered_r503(pcm: bytes) -> tuple[bytes, int]:
    """Return same-length PCM16LE; never amplify, alter text or change frames."""
    if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2:
        raise ValueError("r526_requires_even_nonempty_pcm")
    if audioop is not None and sys.byteorder == "little":
        return _native_smooth(pcm)
    return _python_smooth(pcm)
