"""User-controlled persistent, physical-release-bound onboard wake policy.

Only the already paired ESP32 can stream the authenticated KWS input. This
setting neither listens through the Mac microphone nor starts DSH/ASR/TTS.
Opt-in is pinned to the physically verified R436 APP; any release mismatch
fails closed. A private explicit OFF overrides legacy expiring experiment flags.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from pathlib import Path
from app.r640_release_archive import ROOT as R640_ARCHIVE, archive_valid as r640_archive_valid

ROOT = Path(__file__).resolve().parents[1]
PAIR = Path.home() / "Library/Application Support/Deepseek-live/lan-pairing"
PREF = PAIR / "r439-persistent-wake.json"
TX=R640_ARCHIVE / "wake/TX.json"
RECEIPT=R640_ARCHIVE / "wake/RECEIPT.json"
AUTHORIZED = PAIR / "authorized-devices.json"
EXPECTED_BOARD_MAC=os.environ.get('DAFEIYU_VERIFIED_BOARD_MAC','')
# New hardware release is accepted ONLY after this transaction's full physical
# APP verify, 65s boot gate and side-partition comparison succeed. Its existence
# while incomplete fails closed, so the old R436 signature is not reused.
R441_TX=R640_ARCHIVE / "wake/R441_TX.json"
R441_RECEIPT=R640_ARCHIVE / "wake/R441_RECEIPT.json"
R441_RECOVERY=R640_ARCHIVE / "wake/R441_RECOVERY.json"

# R476 physically guarded R461 APP-only transaction. Its mere presence causes
# unverified/partial release state to fail closed; no stale R441 ON signature.
R461_TX=R640_ARCHIVE / "wake/R461_TX.json"
R461_APP=R640_ARCHIVE / "wake/R461_APP.bin"


# R485: R483 menu release is a physically distinct APP-only transaction.
# R439 remains fail-closed until its EXACT image, readback, protected
# NVS/model/storage, boot and services are attested. A missing transaction
# means the current R461 pair-bound setting is unchanged.
R483_TX=R640_ARCHIVE / "wake/R483_TX.json"
R483_APP=R640_ARCHIVE / "wake/R483_APP.bin"
_R483_SHA="a83d35ea52305d5e9e749395532c9ff66ce3a23302669a0916bbd2e8d22a30ae"


# R488 guarded R487 APP-only deployment; partial/corrupt physical receipts
# MUST block old R483 KWS binding to avoid false trusted wake after a flash.
R487_TX=R640_ARCHIVE / "wake/R487_TX.json"
R487_APP=R640_ARCHIVE / "wake/R487_APP.bin"
_R487_SHA="6965a4c5bb9a7f3a3a2862b1d03915444dcbcb3b83f2e303d80d39e63ce4b039"
_R487_SIZE=5165568


def _r487_flash_state() -> tuple[str,str | None]:
    if not R487_TX.exists():
        return "absent",None
    try:
        import hashlib
        if R487_TX.is_symlink() or not 1<R487_TX.stat().st_size<24000:
            return "unverified",None
        tx=json.loads(R487_TX.read_text())
        if tx.get("stage")!="final":
            return "unverified",None
        common=(
            tx.get("physical_mac")==EXPECTED_BOARD_MAC
            and tx.get("verified_current_factory") is True
            and tx.get("model_untouched") is True
            and tx.get("nvs_protected_logical_keys_unchanged") is True
            and tx.get("two_independent_factory_reads_equal") is True
            and tx.get("services",{}).get("voice_verified") is True
            and tx.get("services",{}).get("supervisor_restored") is True
        )
        if not common:return "unverified",None
        if (tx.get("restored_r483_factory") is True
            and tx.get("r487_app_left_on_board") is False
            and isinstance(tx.get("original_full_factory_sha256"),str)
            and len(tx["original_full_factory_sha256"])==64):
            # The previous R483 physical receipt is separately verified by
            # _r483_flash_state() below. No R487 wake binding on rollback.
            return "verified_rollback",None
        if (tx.get("error") is not None
            or tx.get("r487_app_left_on_board") is not True
            or tx.get("restored_r483_factory") is not False
            or tx.get("boot_only_gate_passed") is not True
            or tx.get("r487_candidate_sha256")!=_R487_SHA
            or not R487_APP.is_file() or R487_APP.is_symlink()
            or R487_APP.stat().st_size!=_R487_SIZE):
            return "unverified",None
        if hashlib.sha256(R487_APP.read_bytes()).hexdigest()!=_R487_SHA:
            return "unverified",None
        return "r487_verified",_R487_SHA
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        return "unverified",None


def _r483_flash_state() -> tuple[str, str | None]:
    if not R483_TX.exists():
        return "absent", None
    try:
        import hashlib
        if (R483_TX.is_symlink() or not 1 < R483_TX.stat().st_size < 18000):
            return "unverified", None
        tx=json.loads(R483_TX.read_text())
        if tx.get("stage")!="final":
            return "unverified", None
        valid_common=(
            tx.get("physical_mac")==EXPECTED_BOARD_MAC
            and tx.get("verified_current_factory") is True
            and tx.get("model_untouched") is True
            and tx.get("nvs_protected_logical_keys_unchanged") is True
            and tx.get("services",{}).get("voice_verified") is True
            and tx.get("services",{}).get("supervisor_restored") is True
            and tx.get("two_independent_factory_reads_equal") is True
        )
        if not valid_common:return "unverified",None
        if (tx.get("restored_r461_factory") is True
            and tx.get("r483_app_left_on_board") is False
            and type(tx.get("original_full_factory_sha256")) is str
            and len(tx.get("original_full_factory_sha256"))==64
            and tx.get("model_untouched") is True):
            # A recorded flash error is expected on a correctly verified
            # rollback; the prior physically verified R461 remains valid.
            # Fallback will subsequently verify the previous R461 receipt.
            return "verified_rollback",None
        if (tx.get("error") is not None
            or tx.get("r483_app_left_on_board") is not True
            or tx.get("restored_r461_factory") is not False
            or tx.get("boot_only_gate_passed") is not True
            or tx.get("r483_candidate_sha256")!=_R483_SHA
            or not R483_APP.is_file() or R483_APP.is_symlink()
            or R483_APP.stat().st_size!=5038576):
            return "unverified",None
        if hashlib.sha256(R483_APP.read_bytes()).hexdigest()!=_R483_SHA:
            return "unverified",None
        return "r483_verified",_R483_SHA
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        return "unverified",None


def _r461_flash_state() -> tuple[str, str | None]:
    if not R461_TX.exists():
        return "absent", None
    try:
        if R461_TX.is_symlink() or not 1 < R461_TX.stat().st_size < 16000:
            return "unverified", None
        tx = json.loads(R461_TX.read_text())
        if tx.get("stage") != "final":
            return "unverified", None
        if (tx.get("restored_r441_factory") is True
                and tx.get("verified_current_factory") is True
                and tx.get("nvs_protected_logical_keys_unchanged") is True
                and tx.get("services", {}).get("voice_verified") is True
                and tx.get("services", {}).get("supervisor_restored") is True):
            return "verified_rollback", None
        sha = tx.get("r461_candidate_sha256")
        if (tx.get("error") is None
                and tx.get("r461_app_left_on_board") is True
                and tx.get("restored_r441_factory") is False
                and tx.get("verified_current_factory") is True
                and tx.get("model_untouched") is True
                and tx.get("nvs_protected_logical_keys_unchanged") is True
                and tx.get("boot_only_gate_passed") is True
                and tx.get("physical_mac") == EXPECTED_BOARD_MAC
                and tx.get("services", {}).get("voice_verified") is True
                and tx.get("services", {}).get("supervisor_restored") is True
                and type(sha) is str and len(sha) == 64
                and all(ch in "0123456789abcdef" for ch in sha)
                and R461_APP.is_file() and not R461_APP.is_symlink()
                and R461_APP.stat().st_size == 5036096):
            import hashlib
            h = hashlib.sha256()
            with R461_APP.open("rb") as f:
                for block in iter(lambda: f.read(1048576), b""):
                    h.update(block)
            if h.hexdigest() == sha:
                return "r461_verified", sha
        return "unverified", None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return "unverified", None



def _r441_flash_state() -> tuple[str, str | None]:
    if not R441_TX.exists():
        return "absent", None
    try:
        if R441_TX.is_symlink() or R441_TX.stat().st_size > 16000:
            return "unverified", None
        tx = json.loads(R441_TX.read_text())
        if tx.get("stage") != "final":
            return "unverified", None
        if tx.get("restored_r436_factory") is True and tx.get("verified_current_factory") is True:
            return "verified_rollback", None
        # The strict deploy transaction correctly failed when boot-time NVS
        # changed. Its rollback APP nevertheless passed full physical verify.
        # Keep the original transaction immutable; require an independent,
        # private exact-log attestation before restoring the R436 wake binding.
        if tx.get("error") is not None and R441_RECOVERY.exists():
            att=R441_RECOVERY.lstat()
            if (stat.S_ISREG(att.st_mode) and att.st_uid == os.getuid()
                    and stat.S_IMODE(att.st_mode) == 0o600
                    and att.st_size < 12000):
                proof=json.loads(R441_RECOVERY.read_text())
                if (proof.get("type") == "R441_R436_RECOVERY_INDEPENDENT_LOG_ATTESTATION"
                        and proof.get("source_transaction") == str(R441_TX)
                        and proof.get("physical_board_mac") == EXPECTED_BOARD_MAC
                        and proof.get("r441_left_on_board") is False
                        and proof.get("r436_original_factory_full_region_write_and_verify_passed") is True
                        and proof.get("two_independent_prewrite_factory_read_sha_equal") is True
                        and proof.get("model_physical_verify_after_rollback_passed") is True
                        and proof.get("storage_physical_verify_after_rollback_passed") is True
                        and proof.get("usb_voice_restored") is True
                        and proof.get("supervisor_restored") is True
                        and proof.get("original_full_factory_sha256") == tx.get("original_full_factory_sha256")
                        and proof.get("nvs_phy_before_after_equal") is False
                        and tx.get("services", {}).get("voice_verified") is True
                        and tx.get("services", {}).get("supervisor_restored") is True):
                    return "verified_rollback", None
        rec = json.loads(R441_RECEIPT.read_text())
        digest = rec.get("app_sha256")
        if (tx.get("error") is None and
                tx.get("r441_app_left_on_board") is True and
                tx.get("restored_r436_factory") is False and
                tx.get("verified_current_factory") is True and
                tx.get("model_untouched") is True and
                tx.get("nvs_protected_logical_keys_unchanged") is True and
                tx.get("boot_only_gate_passed") is True and
                tx.get("physical_mac") == EXPECTED_BOARD_MAC and
                tx.get("services", {}).get("voice_verified") is True and
                tx.get("services", {}).get("supervisor_restored") is True and
                rec.get("name") == "R441_WIRELESS_PCM_CONTINUITY_OFFLINE_CANDIDATE" and
                rec.get("board_written") is False and
                digest == tx.get("r441_candidate_sha256") and
                type(digest) is str and len(digest) == 64 and
                all(ch in "0123456789abcdef" for ch in digest)):
            return "r441_verified", digest
        return "unverified", None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return "unverified", None


def verified_app_sha() -> str | None:
    """Return physical-R436-bound SHA only with valid transaction and pairing."""
    try:
        # R641: genuine production history is private, code-pinned and sealed.
        # Test-injected paths remain injectable for the historical gate matrix.
        if TX == R640_ARCHIVE / "wake/TX.json" and not r640_archive_valid():
            return None
        tx = json.loads(TX.read_text())
        rec = json.loads(RECEIPT.read_text())
        paired = json.loads(AUTHORIZED.read_text())
        sha = rec.get("app_sha256")
        if (tx.get("stage") != "final" or tx.get("error") is not None
                or tx.get("r436_app_left_on_board") is not True
                or tx.get("restored_r435_factory") is not False
                or rec.get("name") != "R436_ACK_WAVE_OFFLINE_ONLY"
                or rec.get("board_written") is not False
                or sha != tx.get("r436_candidate_sha256")
                or type(sha) is not str or len(sha) != 64
                or any(ch not in "0123456789abcdef" for ch in sha)
                or paired.get("schema") != 1
                or not isinstance(paired.get("devices"), dict)
                or len(paired["devices"]) != 1):
            return None
        r487, newest = _r487_flash_state()
        if r487 == "unverified":
            return None
        if r487 == "r487_verified":
            return newest
        r483, installed = _r483_flash_state()
        if r483 == "unverified":
            return None
        if r483 == "r483_verified":
            return installed
        state, replacement = _r441_flash_state()
        if state == "unverified":
            return None
        if state == "r441_verified":
            newer, digest = _r461_flash_state()
            if newer == "r461_verified":
                return digest
            if newer == "unverified":
                return None
            # No R461 attempt, or physically verified R441 recovery.
            return replacement
        if _r461_flash_state()[0] not in ("absent", "verified_rollback"):
            return None
        # No R441 attempt, or verified recovery of original R436 factory.
        return sha
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _read() -> tuple[bool, dict | None]:
    """(exists, valid preference); corrupt/symlinked file fails OFF."""
    try:
        st = PREF.lstat()
    except FileNotFoundError:
        return False, None
    except OSError:
        return True, None
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) != 0o600 or not 4 < st.st_size < 700):
        return True, None
    try:
        row = json.loads(PREF.read_text())
        if (row.get("schema") != 1 or row.get("mode") not in ("on", "off")
                or not isinstance(row.get("app_sha256"), str)
                or len(row["app_sha256"]) != 64):
            return True, None
        return True, row
    except (OSError, ValueError, TypeError, AttributeError):
        return True, None


def decision() -> bool | None:
    """None=legacy temporary policy; true/false=explicit durable preference."""
    exists, row = _read()
    if not exists:
        return None
    if row is None:
        return False
    if row["mode"] == "off":
        return False
    return bool(verified_app_sha() and row["app_sha256"] == verified_app_sha())


def status() -> dict:
    exists, row = _read()
    expected = verified_app_sha()
    return {
        "schema": 1,
        "configured": exists,
        "requested_on": bool(row and row["mode"] == "on"),
        "enabled": decision() is True,
        "eligible": expected is not None,
        "reason": ("no_preference" if not exists else
                   "invalid_private_setting" if row is None else
                   "off" if row["mode"] == "off" else
                   "r436_receipt_or_version_unverified" if decision() is not True else
                   "r487_paired_persistent_on" if _r487_flash_state()[0] == "r487_verified" else
                   "r483_paired_persistent_on" if _r483_flash_state()[0] == "r483_verified" else
                   "r461_paired_persistent_on" if _r461_flash_state()[0] == "r461_verified"
                   else "r441_paired_persistent_on" if _r441_flash_state()[0] == "r441_verified"
                   else "r436_paired_persistent_on"),
    }


def set_enabled(enabled: bool) -> dict:
    if type(enabled) is not bool:
        raise ValueError("invalid_wake_setting")
    sha = verified_app_sha()
    if enabled and not sha:
        raise RuntimeError("r436_physical_transaction_or_pairing_unverified")
    # Never follow symlinks or rewrite a non-owned suspicious preference.
    exists, row = _read()
    if exists and row is None:
        raise RuntimeError("existing_private_wake_setting_invalid")
    PAIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if PAIR.is_symlink():
        raise RuntimeError("wake_setting_directory_symlink")
    mode = stat.S_IMODE(PAIR.stat().st_mode)
    if mode & 0o077:
        raise RuntimeError("wake_setting_directory_not_private")
    content = {
        "schema": 1, "mode": "on" if enabled else "off",
        "app_sha256": sha or (row["app_sha256"] if row else "0" * 64),
        "updated_at_unix": int(time.time()),
    }
    fd, path = tempfile.mkstemp(prefix=".r439-wake-", dir=PAIR)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(content, f, separators=(",", ":"))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(path, PREF)
    finally:
        if os.path.exists(path):
            os.unlink(path)
    result = status()
    if result["enabled"] is not enabled:
        raise RuntimeError("wake_setting_readback_mismatch")
    return result
