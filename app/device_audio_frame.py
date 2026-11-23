"""Small ESP32-friendly Opus packet envelope for device v2 only.

Network byte order; 16 bytes total:
  magic "DF" (2), version 2 (1), direction (1), stream id (u64), seq (u32).
Direction 1=device microphone uplink; 2=Mac generated downlink.
NO plaintext transcripts or secrets in packet headers.
"""
import struct

MAGIC = b"DF"
VERSION = 2
MIC_UPLINK = 1
SPEAKER_DOWNLINK = 2
HEADER = struct.Struct("!2sBBQI")
HEADER_BYTES = HEADER.size
MAX_PAYLOAD_BYTES = 4096


class AudioFrameError(ValueError):
    pass


def pack_frame(direction: int, stream_id: int, seq: int, opus: bytes) -> bytes:
    if type(direction) is not int or direction not in (MIC_UPLINK, SPEAKER_DOWNLINK):
        raise AudioFrameError("bad direction")
    if type(stream_id) is not int or not (0 < stream_id < (1 << 64)):
        raise AudioFrameError("bad stream")
    if type(seq) is not int or not (0 <= seq < (1 << 32)):
        raise AudioFrameError("bad sequence")
    if not isinstance(opus, bytes) or not (1 <= len(opus) <= MAX_PAYLOAD_BYTES):
        raise AudioFrameError("bad opus payload")
    return HEADER.pack(MAGIC, VERSION, direction, stream_id, seq) + opus


def unpack_frame(packet: bytes, expected_direction: int) -> tuple[int, int, bytes]:
    if not isinstance(packet, bytes) or len(packet) <= HEADER_BYTES:
        raise AudioFrameError("short frame")
    if len(packet) > HEADER_BYTES + MAX_PAYLOAD_BYTES:
        raise AudioFrameError("oversized frame")
    magic, version, direction, stream_id, seq = HEADER.unpack_from(packet)
    if (magic != MAGIC or version != VERSION or direction != expected_direction
            or stream_id == 0 or direction not in (MIC_UPLINK, SPEAKER_DOWNLINK)):
        raise AudioFrameError("invalid frame header")
    return stream_id, seq, packet[HEADER_BYTES:]
