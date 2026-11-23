"""R616 authenticated R614 physical APP-on-board policy gate.

No hardware I/O. Reject in-progress, forged, truncated or mismatched receipts.
"""
from __future__ import annotations
import hashlib,os
from pathlib import Path
from app import r509_incremental_gate as legacy

NEW_SHA="1c7e8ca4ebc008c23f6ce8da39ec8095c564ef558c590795a85d9060e6430526"
TRIAL=Path("private-runtime/r615-r614-md5-app-only-20261119/transaction.json")
# New R614 release uses the owner-only managed evidence store.
# Prior R439/R509 legacy test-folder decoupling is a separate phase.
CAND=Path.home()/"Library/Application Support/Deepseek-live/release-evidence/r614-physical-verified-20261119"
MANIFEST=CAND/"release-manifest.json"
IMAGE=CAND/"dafeiyu_r614_factory_app.bin"
BACKUP_A=TRIAL.parent/"full-current-r587-factory-md5-pass-a.bin"
BACKUP_B=TRIAL.parent/"full-current-r587-factory-md5-pass-b.bin"
STORE=TRIAL.parent/"fresh-current-storage-7m-md5-proved.bin"
BACKUP_STORAGE_SHA="c86caf5d3b06f80286008b872753adb5927254d74eed57eadf1301f1589fdfb6"

def checked(path:Path,size:int,digest:str)->bool:
    try:
        st=path.stat()
        return (path.is_file() and not path.is_symlink() and
                st.st_uid==os.getuid() and (st.st_mode & 0o077)==0 and
                st.st_size==size and
                hashlib.sha256(path.read_bytes()).hexdigest()==digest)
    except (OSError,ValueError,TypeError):return False

def r614_enabled(*,policy=legacy.POLICY,trial=TRIAL,manifest=MANIFEST,
                 app=IMAGE,factory_a=BACKUP_A,factory_b=BACKUP_B,storage=STORE)->bool:
    p=legacy.private_read(policy)
    t=legacy.private_read(trial)
    m=legacy.private_read(manifest)
    c=t.get("physical_integrity_counters") if t else None
    if not (p and t and m and isinstance(c,dict) and
            p.get("schema")==1 and p.get("enabled") is True and
            p.get("scope")=="r614_app_only_incremental_wss" and
            p.get("candidate_sha256")==NEW_SHA and
            t.get("stage")=="final" and t.get("error") is None and
            t.get("write_attempted") is True and
            t.get("r614_app_left_on_board") is True and
            t.get("r587_restored") is False and
            t.get("r614_app_sha256")==NEW_SHA and
            t.get("previous_r587_sha256")==legacy.R587_EXPECTED and
            t.get("physical_mac")==legacy.EXPECTED_BOARD_MAC and
            t.get("two_full_factory_md5_passes") is True and
            t.get("model_storage_nvs_verified") is True and
            t.get("no_model_storage_nvs_partition_writes") is True and
            t.get("dsh_3080_pid_unchanged") is True and
            t.get("other_profile_pid_unchanged") is True and
            c.get("factory_verified_pass_a_blocks512")==12 and
            c.get("factory_verified_pass_b_blocks512")==12 and
            c.get("storage_verified_pre_blocks512")==14 and
            c.get("storage_verified_pre_confirmation_blocks512")==14 and
            c.get("storage_verified_post_blocks512")==14 and
            c.get("model_verified_pre_blocks512")==6 and
            c.get("model_verified_post_blocks512")==6 and
            t.get("storage_capture_blocks")==112 and
            t.get("post_storage_verified_blocks")==112 and
            t.get("post_model_verified_blocks")==48 and
            isinstance(t.get("smoke"),dict) and
            t["smoke"].get("boot_only_gate_passed") is True and
            isinstance(t.get("services"),dict) and
            t["services"].get("voice_verified") is True and
            t["services"].get("supervisor_restored") is True and
            m.get("schema")==1 and m.get("candidate")=="R614" and
            m.get("project_version")=="R614" and
            m.get("base_app_sha256")==legacy.R587_EXPECTED and
            m.get("build_complete") is True and
            m.get("exact_source_diff_verified") is True and
            m.get("physical_flash_performed") is True and
            m.get("wss_policy_promoted") is True and
            m.get("stage")=="r618_verified_released_copy" and
            m.get("app_sha256")==NEW_SHA):
        return False
    full=t.get("full_factory_backup_sha256")
    try:
        if m.get("r615_transaction_sha256") != hashlib.sha256(
            Path(trial).read_bytes()).hexdigest():
            return False
        if not (isinstance(full,str) and len(full)==64 and
                checked(factory_a,0x5f0000,full) and
                checked(factory_b,0x5f0000,full) and
                checked(storage,0x700000,BACKUP_STORAGE_SHA) and
                checked(app,m.get("app_bytes"),NEW_SHA)):
            return False
        blob=Path(app).read_bytes()
        return (blob.find(bytes.fromhex("3254cdab"))==32 and
                blob[48:80].split(b"\0",1)[0]==b"R614")
    except (OSError,TypeError,ValueError):return False
