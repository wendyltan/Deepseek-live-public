"""Insert gentle breathing pauses inside existing silence valleys of TTS PCM.

Preserves every voiced phoneme sample untouched (zero WSOLA time-stretching
or pitch warping) while softening overly brisk conversational pacing.
"""
from __future__ import annotations

import os
import warnings

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import audioop
except ImportError:
    audioop = None

SAMPLE_RATE = 24000
BYTES_PER_SAMPLE = 2
BLOCK_MS = 10
BLOCK_BYTES = SAMPLE_RATE * BYTES_PER_SAMPLE * BLOCK_MS // 1000  # 480 bytes
SILENCE_RMS_MAX = 420
MIN_VALLEY_BLOCKS = 9        # >= 90ms existing pause inside synthesized speech
MIN_GAP_BETWEEN_MS = 650     # do not insert breaths closer than 650ms
DEFAULT_BREATH_MS = 100      # extend each detected natural break by 100ms
DEFAULT_PHRASE_GAP_MS = 160  # calm breathing space between consecutive phrases


def _breath_ms() -> int:
    raw = os.environ.get("DAFEIYU_TTS_BREATH_MS", str(DEFAULT_BREATH_MS)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_BREATH_MS
    return max(0, min(260, value))


def extend_silence_valleys(pcm: bytes, *, extra_ms: int | None = None) -> tuple[bytes, int]:
    """Extend natural internal pause valleys with pure digital silence.

    Returns ``(new_pcm, added_ms)``. Never alters any voiced sample.
    """
    if not isinstance(pcm, bytes) or len(pcm) % 2:
        raise ValueError("pcm16le_required")
    added = DEFAULT_BREATH_MS if extra_ms is None else max(0, min(260, int(extra_ms)))
    if not pcm or added == 0 or audioop is None or len(pcm) < MIN_VALLEY_BLOCKS * BLOCK_BYTES:
        return pcm, 0
    if extra_ms is None:
        added = _breath_ms()
        if added == 0:
            return pcm, 0
    pad_bytes = (added // BLOCK_MS) * BLOCK_BYTES
    if pad_bytes <= 0:
        return pcm, 0

    blocks = [pcm[i:i + BLOCK_BYTES] for i in range(0, len(pcm), BLOCK_BYTES)]
    out: list[bytes] = []
    quiet_run = 0
    last_inserted_at_ms = -MIN_GAP_BETWEEN_MS
    elapsed_ms = 0
    total_added_ms = 0
    # Avoid padding leading silence before the first spoken syllable.
    seen_voice = False

    for idx, block in enumerate(blocks):
        full_block = len(block) == BLOCK_BYTES
        rms = audioop.rms(block, 2) if full_block else SILENCE_RMS_MAX + 1
        if full_block and rms <= SILENCE_RMS_MAX:
            if seen_voice:
                quiet_run += 1
        else:
            if (seen_voice and quiet_run >= MIN_VALLEY_BLOCKS and
                    elapsed_ms - last_inserted_at_ms >= MIN_GAP_BETWEEN_MS and
                    idx < len(blocks) - 2):
                out.append(b"\x00" * pad_bytes)
                last_inserted_at_ms = elapsed_ms
                total_added_ms += added
            seen_voice = True
            quiet_run = 0
        out.append(block)
        elapsed_ms += BLOCK_MS

    if total_added_ms == 0:
        return pcm, 0
    rendered = b"".join(out)
    return rendered, total_added_ms


def interphrase_breath_gap(
    *, previous_tail_ms: int, next_lead_ms: int, target_gap_ms: int = DEFAULT_PHRASE_GAP_MS
) -> bytes:
    """Return bounded 24kHz PCM16 silence so phrase transitions feel unhurried."""
    existing = max(0, int(previous_tail_ms)) + max(0, int(next_lead_ms))
    needed_ms = max(0, min(360, int(target_gap_ms) - existing))
    blocks = needed_ms // BLOCK_MS
    if blocks <= 0:
        return b""
    return b"\x00" * (blocks * BLOCK_BYTES)
