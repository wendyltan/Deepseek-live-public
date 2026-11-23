"""Versioned, fail-closed ESP32 new-motion SD upload client.

Protocol DFSD3 is a future *separate* firmware protocol. R61/R79 DFSD2
supports ONLY original 35, and cannot install custom motions. No automatic
USB discovery, service stops, unlocks, writes or fallback to DFSD2 allowed.
Caller must obtain sole ownership and physical user approval.
"""
from __future__ import annotations
import base64
import hashlib
import re
from dataclasses import dataclass

CHUNK_BYTES = 1536
USER_SLOTS = range(200, 208)
CAPS = ("@@DFSD3 READY version=1 slots=m200-m207 mode=transactional "
        "sha256=1 readback=1 local_confirm=1")
OPENED = re.compile(r"@@DFSD3 OPENED id=m(20[0-7]) chunk=1536\Z")
ACK = re.compile(r"@@DFSD3 ACK seq=(\d{1,7})\Z")
STAGED = re.compile(r"@@DFSD3 STAGED id=m(20[0-7]) sha256=([a-f0-9]{64})\Z")
VERIFIED = re.compile(r"@@DFSD3 VERIFIED id=m(20[0-7]) bytes=(\d{1,8}) sha256=([a-f0-9]{64}) role=(idle|work|reaction|bonus)\Z")
INSPECT_PRESENT = re.compile(r"@@DFSD3 PRESENT id=m(20[0-7]) bytes=(\d{1,8}) sha256=([a-f0-9]{64}) role=(idle|work|reaction|bonus)\Z")
INSPECT_MISSING = re.compile(r"@@DFSD3 MISSING id=m(20[0-7])\Z")
MAX_FILE = 8_000_000
ROLES = frozenset(("idle","work","reaction","bonus"))

class TransferRejected(ValueError):
    pass

@dataclass(frozen=True)
class Receipt:
    slot: str
    sha256: str
    bytes_written: int
    chunks: int
    device_readback_verified: bool
    factory_slots_modified: bool = False
    already_present: bool = False

def _exchange(io, command: str, *, expected: str | None = None) -> str:
    if len(command.encode("ascii")) > 2300 or "\n" in command or "\r" in command:
        raise TransferRejected("invalid_command_length")
    reply = io.request(command)
    if not isinstance(reply,str) or len(reply)>256 or not reply.startswith("@@DFSD3 "):
        raise TransferRejected("unexpected_reply_or_device_version")
    line=reply.strip()
    if "ERROR" in line or "NACK" in line or "REJECTED" in line:
        raise TransferRejected("device_rejected_operation")
    if expected is not None and line!=expected:
        raise TransferRejected("unexpected_or_replayed_reply")
    return line

def preflight(io) -> None:
    # Strict matching is intentional. Old 35-only DFSD2 can't be coerced
    # into writing a user-motion slot by changing a command string.
    _exchange(io, "@@DFSD3 CAPS", expected=CAPS)

def upload(io, *, slot: int, contents: bytes, role: str, local_confirmation: bool) -> Receipt:
    # Must be explicit per-session opt-in from physical device UI; caller
    # cannot auto-approve. Future firmware separately verifies local arm.
    if not local_confirmation:
        raise TransferRejected("physical_user_confirmation_required")
    if slot not in USER_SLOTS or role not in ROLES:
        raise TransferRejected("not_a_reserved_user_slot_or_role")
    if not 128 <= len(contents) <= MAX_FILE:
        raise TransferRejected("unapproved_file_size")
    from scripts.r72_prepare_motion_candidate import verify
    validated=verify(contents)
    if validated["max_compressed_packet"]>65536 or validated["frames"]>80:
        raise TransferRejected("unsupported_dfsp_frame")
    sha=hashlib.sha256(contents).hexdigest()
    preflight(io)
    target=f"m{slot:03d}"
    existing=_exchange(io,f"@@DFSD3 INSPECT id={target}")
    present=INSPECT_PRESENT.fullmatch(existing)
    missing=INSPECT_MISSING.fullmatch(existing)
    if present:
        if (present[1]!=str(slot) or int(present[2])!=len(contents) or
            present[3]!=sha or present[4]!=role):
            raise TransferRejected("user_slot_occupied_by_different_motion")
        return Receipt(slot=target,sha256=sha,bytes_written=0,chunks=0,
                       device_readback_verified=True,already_present=True)
    if missing is None or missing[1]!=str(slot):
        raise TransferRejected("device_inspect_failed_closed")
    command=(f"@@DFSD3 OPEN id={target} bytes={len(contents)} "
             f"sha256={sha} role={role} frames={validated['frames']}")
    opened=_exchange(io,command)
    match=OPENED.fullmatch(opened)
    if not match or match[1]!=str(slot):
        raise TransferRejected("unexpected_opened_slot")
    chunks=0
    try:
        for idx in range(0,len(contents),CHUNK_BYTES):
            block=contents[idx:idx+CHUNK_BYTES]
            encoded=base64.b64encode(block).decode("ascii")
            reply=_exchange(io,f"@@DFSD3 DATA seq={chunks} b64={encoded}")
            seq=ACK.fullmatch(reply)
            if seq is None or int(seq[1])!=chunks:
                raise TransferRejected("sequence_mismatch")
            chunks+=1
        staged=_exchange(io,"@@DFSD3 COMMIT")
        match=STAGED.fullmatch(staged)
        if match is None or match[1]!=str(slot) or match[2]!=sha:
            raise TransferRejected("staged_sha256_mismatch")
        readback=_exchange(io,f"@@DFSD3 VERIFY id={target}")
        actual=VERIFIED.fullmatch(readback)
        if (actual is None or actual[1]!=str(slot)
           or int(actual[2])!=len(contents) or actual[3]!=sha
           or actual[4]!=role):
            raise TransferRejected("device_sd_readback_or_role_mismatch")
    except BaseException:
        try:
            _exchange(io,"@@DFSD3 ABORT")
        except Exception:
            pass
        raise
    return Receipt(slot=target,sha256=sha,bytes_written=len(contents),
                   chunks=chunks,device_readback_verified=True)

class FakeFutureDevice:
    """Volatile USB protocol simulation; never opens hardware or touches SD."""
    def __init__(self, *,local_armed: bool = True, corrupt_readback: bool = False):
        self.local_armed=local_armed
        self.corrupt_readback=corrupt_readback
        self.files={}
        self.roles={}
        self.pending=None
        self.commands=[]
    def request(self,cmd):
        self.commands.append(cmd.split(" b64=")[0])
        if cmd=="@@DFSD3 CAPS":
            return CAPS if self.local_armed else "@@DFSD3 UNAVAILABLE"
        if cmd.startswith("@@DFSD3 INSPECT id="):
            match=re.fullmatch(r"@@DFSD3 INSPECT id=m(20[0-7])",cmd)
            if match is None:return "@@DFSD3 NACK"
            slot=f"m{match[1]}"
            if slot not in self.files:return f"@@DFSD3 MISSING id={slot}"
            data=self.files[slot]
            digest=hashlib.sha256(data).hexdigest()
            if self.corrupt_readback:digest="0"*64
            return (f"@@DFSD3 PRESENT id={slot} bytes={len(data)} "
                    f"sha256={digest} role={self.roles[slot]}")
        if cmd.startswith("@@DFSD3 OPEN "):
            if not self.local_armed:
                return "@@DFSD3 NACK"
            match=re.fullmatch(r"@@DFSD3 OPEN id=m(20[0-7]) bytes=(\d+) "
                r"sha256=([a-f0-9]{64}) role=(idle|work|reaction|bonus) frames=(\d+)",cmd)
            if not match:return "@@DFSD3 NACK"
            slot=f"m{match[1]}"
            if slot in self.files:return "@@DFSD3 NACK"
            self.pending=dict(slot=slot,size=int(match[2]),sha=match[3],
                              role=match[4],received=bytearray(),seq=0)
            return f"@@DFSD3 OPENED id={slot} chunk=1536"
        if cmd.startswith("@@DFSD3 DATA "):
            if self.pending is None:return "@@DFSD3 NACK"
            m=re.fullmatch(r"@@DFSD3 DATA seq=(\d+) b64=([A-Za-z0-9+/=]+)",cmd)
            if m is None or int(m[1])!=self.pending["seq"]:return "@@DFSD3 NACK"
            try:data=base64.b64decode(m[2],validate=True)
            except Exception:return "@@DFSD3 NACK"
            if len(data)>CHUNK_BYTES or len(self.pending["received"])+len(data)>self.pending["size"]:
                return "@@DFSD3 NACK"
            self.pending["received"].extend(data)
            seq=self.pending["seq"];self.pending["seq"]+=1
            return f"@@DFSD3 ACK seq={seq}"
        if cmd=="@@DFSD3 COMMIT":
            if self.pending is None:return "@@DFSD3 NACK"
            p=self.pending
            if len(p["received"])!=p["size"] or hashlib.sha256(p["received"]).hexdigest()!=p["sha"]:
                return "@@DFSD3 NACK"
            self.files[p["slot"]]=bytes(p["received"])
            self.roles[p["slot"]]=p["role"]
            self.pending=None
            return f'@@DFSD3 STAGED id={p["slot"]} sha256={p["sha"]}'
        if cmd.startswith("@@DFSD3 VERIFY id="):
            slot=cmd.rsplit("=",1)[-1]
            if slot not in self.files:return "@@DFSD3 NACK"
            data=self.files[slot]; digest=hashlib.sha256(data).hexdigest()
            if self.corrupt_readback:digest="0"*64
            return (f"@@DFSD3 VERIFIED id={slot} bytes={len(data)} "
                    f"sha256={digest} role={self.roles[slot]}")
        if cmd=="@@DFSD3 ABORT":
            self.pending=None
            return "@@DFSD3 ABORTED"
        return "@@DFSD3 NACK"
