"""R509 fail-closed LAN streaming activation for a physically verified APP.

No USB, DSH, network, flash or side effects. The supervisor does not enable
zero-frame streaming unless a private owner-only policy AND one completed
R509 physical flash readback transaction agree on the exact candidate.
R487 boards without the signed client hello always retain legacy behavior.
"""
from __future__ import annotations
from pathlib import Path
from app.r640_release_archive import ROOT as R640_ARCHIVE, archive_valid as r640_archive_valid
from app.r652_legacy_recovery_archive import ROOT as R652_ARCHIVE, archive_valid as r652_archive_valid
import json,os

TRIAL=R640_ARCHIVE / "pcm/TRIAL.json"
MANIFEST=R640_ARCHIVE / "pcm/MANIFEST.json"
POLICY=Path.home()/'Library/Application Support/Deepseek-live/companion-native/r509-incremental-optin.json'
EXPECTED='882671f6270240e3fc237ae9320e6f71b84db35e8bd3ab9265729534d6d3e900'
EXPECTED_BOARD_MAC=os.environ.get('DAFEIYU_VERIFIED_BOARD_MAC','')
R510_TRIAL=R640_ARCHIVE / "pcm/R510_TRIAL.json"
R510_MANIFEST=R640_ARCHIVE / "pcm/R510_MANIFEST.json"
R510_EXPECTED='0195704addec2bee679e5695297e1e8412f326c672c8ffc429b57f3a40fdde51'
R511_TRIAL=R640_ARCHIVE / "pcm/R511_TRIAL.json"
R511_MANIFEST=R640_ARCHIVE / "pcm/R511_MANIFEST.json"
R511_EXPECTED='ccf992bfddd6537582a1c44d52ca908a3da21b7cd4545ded9f45854039f191e7'
R550_TRIAL=Path('private-runtime/'
                'r551-r550-guarded-app-only-20261116/transaction.json')
R550_MANIFEST=R652_ARCHIVE / "r550/manifest.json"
R550_APP=R652_ARCHIVE / "r550/app.bin"
# Filled from actual offline complete APP link after verified image_info.
R550_EXPECTED='331a211897e71a71b05e3e0f6f180bb97c24230723f0a42019d41ea79c113d5e'

R556_TRIAL=Path('private-runtime/'
                'r557-r556-guarded-app-only-20261117/transaction.json')
R556_MANIFEST=R652_ARCHIVE / "r556/manifest.json"
R556_APP=R652_ARCHIVE / "r556/app.bin"
# Replace only after the complete signed R556 APP link and esptool image_info.
# Exact physical candidate hash must be immutable; no dynamic manifest trust.
R556_EXPECTED='28fbf6e3e29fb376bbe699df9e03aa13cbf52caf96c81d238789e4e103251b8d'

# R558 keeps R557's immutable zero-write abort record. It replaces only
# long serial verification of unchanged storage with 7 independent 1MiB
# read-only digest checks; source image and APP write scope are the same.
R558_TRIAL=Path('private-runtime/'
                'r558-r556-guarded-app-only-20261117/transaction.json')

# New owner-only one-shot R562 transaction. Stale R557/R558 receipts cannot
# authorize the new firmware, even if their old R550 recovery was valid.
R562_TRIAL=Path('private-runtime/'
                'r562-r556-live-chunk-app-only-20261117/transaction.json')
# R597: exact guarded R587 derived from verified R556, never the older
# mistakenly labeled R487 source build. Promotion requires physical flash,
# readback, protected-region proofs and unchanged official DSH/other profiles.
R595_TRIAL=Path('private-runtime/'
                'r595-r587-from-r556-app-only-20261118/transaction.json')
R587_RELEASE=R640_ARCHIVE / "r587/R587_RELEASE.json"
R587_IMAGE=R640_ARCHIVE / "r587/R587_IMAGE.bin"
R587_EXPECTED='047cd2b27b842b25540fffcd519f87dc9c1104981be068812205afd3b4cce1e1'

R595_ZERO_WRITE_RECOVERY=R595_TRIAL.parent/'r598-verified-no-write-r556-continuity.json'

# R604 alternative physically exact region-hash release. This is separate
# from R595's two full serial-read evidence. Old R595 zero-write record
# remains active only until this exact new transaction is initiated.
R603_TRIAL=Path('private-runtime/'
                'r603-r587-md5-physical-app-only-20261119/transaction.json')
R603_FACTORY_1=R603_TRIAL.parent/'full-current-r556-factory-md5-pass-a.bin'
R603_FACTORY_2=R603_TRIAL.parent/'full-current-r556-factory-md5-pass-b.bin'
R603_STORAGE=R603_TRIAL.parent/'fresh-before-storage-7m-md5-proved.bin'

R603_ZERO_WRITE_RECOVERY=R603_TRIAL.parent/'r606-verified-no-write-r556-continuity.json'
R607_TRIAL=Path('private-runtime/'
                'r607-r587-md5-physical-app-only-20261119/transaction.json')
R607_FACTORY_1=R607_TRIAL.parent/'full-current-r556-factory-md5-pass-a.bin'
R607_FACTORY_2=R607_TRIAL.parent/'full-current-r556-factory-md5-pass-b.bin'
R607_STORAGE=R607_TRIAL.parent/'fresh-before-storage-7m-md5-proved.bin'
R615_TRIAL=Path('private-runtime/'
                'r615-r614-md5-app-only-20261119/transaction.json')
R621_TRIAL=Path('private-runtime/'
                'r621-r619-md5-app-only-20261119/transaction.json')


def private_read(path:Path)->dict|None:
    try:
        p=Path(path)
        if p.is_symlink() or p.parent.is_symlink():return None
        s=p.stat()
        if not p.is_file() or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>20000:
            return None
        j=json.loads(p.read_text())
        return j if type(j) is dict else None
    except (OSError,ValueError,TypeError):return None

def _r509_enabled(*,policy:Path=POLICY,trial:Path=TRIAL,manifest:Path=MANIFEST)->bool:
    p=private_read(policy)
    t=private_read(trial)
    m=private_read(manifest)
    return bool(p and t and m and
        p.get('schema')==1 and p.get('enabled') is True and
        p.get('candidate_sha256')==EXPECTED and
        p.get('scope')=='r509_app_only_incremental_wss' and
        t.get('stage')=='final' and t.get('error') is None and
        t.get('r509_app_left_on_board') is True and
        t.get('old_r487_restored') is False and
        t.get('model_storage_nvs_verified') is True and
        t.get('physical_mac')==EXPECTED_BOARD_MAC and
        t.get('r509_app_sha256')==EXPECTED and
        type(t.get('services')) is dict and
        t['services'].get('voice_verified') is True and
        t['services'].get('supervisor_restored') is True and
        m.get('app_sha256')==EXPECTED and m.get('project_version')=='R509' and
        m.get('build_ok') is True)

def r510_enabled(*, policy:Path=POLICY, trial:Path=R510_TRIAL,
                 manifest:Path=R510_MANIFEST)->bool:
    p=private_read(policy);t=private_read(trial);m=private_read(manifest)
    return bool(p and t and m and
        p.get('schema')==1 and p.get('enabled') is True and
        p.get('candidate_sha256')==R510_EXPECTED and
        p.get('scope')=='r510_app_only_incremental_wss' and
        t.get('stage')=='final' and t.get('error') is None and
        t.get('r510_app_left_on_board') is True and
        t.get('old_r509_restored') is False and
        t.get('model_storage_nvs_verified') is True and
        t.get('physical_mac')==EXPECTED_BOARD_MAC and
        t.get('r510_app_sha256')==R510_EXPECTED and
        type(t.get('services')) is dict and
        t['services'].get('voice_verified') is True and
        t['services'].get('supervisor_restored') is True and
        m.get('app_sha256')==R510_EXPECTED and m.get('project_version')=='R510' and
        m.get('build_ok') is True)


def r511_enabled(*,policy:Path=POLICY,trial:Path=R511_TRIAL,
                 manifest:Path=R511_MANIFEST)->bool:
    # Only enable WSS incremental on a verified current R511 factory APP.
    p=private_read(policy);t=private_read(trial);m=private_read(manifest)
    return bool(p and t and m and
        p.get('schema')==1 and p.get('enabled') is True and
        p.get('candidate_sha256')==R511_EXPECTED and
        p.get('scope')=='r511_app_only_incremental_wss' and
        t.get('stage')=='final' and t.get('error') is None and
        t.get('r511_app_left_on_board') is True and
        t.get('r510_restored') is False and
        t.get('model_storage_nvs_verified') is True and
        t.get('physical_mac')==EXPECTED_BOARD_MAC and
        t.get('r511_app_sha256')==R511_EXPECTED and
        type(t.get('services')) is dict and
        t['services'].get('voice_verified') is True and
        t['services'].get('supervisor_restored') is True and
        m.get('app_sha256')==R511_EXPECTED and
        m.get('project_version')=='R511' and
        m.get('pixel_exact_test') is True)



def r550_enabled(*,policy:Path=POLICY,trial:Path=R550_TRIAL,
                 manifest:Path=R550_MANIFEST,app:Path=R550_APP)->bool:
    """Promoted R550 must be *this* physical APP, not stale R511 evidence."""
    if (Path(manifest)==R550_MANIFEST and Path(app)==R550_APP
        and not r652_archive_valid()):
        return False
    p=private_read(policy);t=private_read(trial);m=private_read(manifest)
    if not (p and t and m and
        p.get('schema')==1 and p.get('enabled') is True and
        p.get('candidate_sha256')==R550_EXPECTED and
        p.get('scope')=='r550_app_only_incremental_wss' and
        t.get('stage')=='final' and t.get('error') is None and
        t.get('r550_app_left_on_board') is True and
        t.get('r511_restored') is False and
        t.get('model_storage_nvs_verified') is True and
        t.get('physical_mac')==EXPECTED_BOARD_MAC and
        t.get('r550_app_sha256')==R550_EXPECTED and
        type(t.get('services')) is dict and
        t['services'].get('voice_verified') is True and
        t['services'].get('supervisor_restored') is True and
        m.get('schema')==1 and m.get('app_sha256')==R550_EXPECTED and
        m.get('project_version')=='R550' and m.get('complete_build') is True):
        return False
    try:
        import hashlib
        target=Path(app)
        if (target.is_symlink() or target.parent.is_symlink()
            or not target.is_file() or target.stat().st_uid!=os.getuid()
            or target.stat().st_mode&0o077
            or not 3000000<target.stat().st_size<0x5f0000
            or target.stat().st_size!=m.get('app_bytes')):
            return False
        return hashlib.sha256(target.read_bytes()).hexdigest()==R550_EXPECTED
    except (OSError,ValueError,TypeError):
        return False


def r556_enabled(*,policy:Path=POLICY,trial:Path=R556_TRIAL,
                 manifest:Path=R556_MANIFEST,app:Path=R556_APP)->bool:
    """R556 permitted ONLY after physical write+readback and policy approval."""
    if (Path(manifest)==R556_MANIFEST and Path(app)==R556_APP
        and not r652_archive_valid()):
        return False
    p=private_read(policy);t=private_read(trial);m=private_read(manifest)
    if not (p and t and m and
        p.get('schema')==1 and p.get('enabled') is True and
        p.get('candidate_sha256')==R556_EXPECTED and
        p.get('scope')=='r556_app_only_incremental_wss' and
        t.get('stage')=='final' and t.get('error') is None and
        t.get('r556_app_left_on_board') is True and
        t.get('r550_restored') is False and
        t.get('model_storage_nvs_verified') is True and
        t.get('physical_mac')==EXPECTED_BOARD_MAC and
        t.get('r556_app_sha256')==R556_EXPECTED and
        t.get('r550_app_sha256')==R550_EXPECTED and
        type(t.get('services')) is dict and
        t['services'].get('voice_verified') is True and
        t['services'].get('supervisor_restored') is True and
        m.get('schema')==1 and m.get('app_sha256')==R556_EXPECTED and
        m.get('project_version')=='R556' and m.get('complete_build') is True and
        m.get('base_r550_sha256')==R550_EXPECTED):
        return False
    try:
        import hashlib
        image=Path(app)
        if (image.is_symlink() or image.parent.is_symlink()
                or not image.is_file() or image.stat().st_uid!=os.getuid()
                or image.stat().st_mode&0o077
                or not 3000000<image.stat().st_size<0x5f0000
                or image.stat().st_size!=m.get('app_bytes')):
            return False
        return hashlib.sha256(image.read_bytes()).hexdigest()==R556_EXPECTED
    except (OSError,ValueError,TypeError):
        return False


def r562_enabled(*,policy:Path=POLICY,trial:Path=R562_TRIAL,
                 manifest:Path=R556_MANIFEST,app:Path=R556_APP)->bool:
    """R556 WSS requires fresh physical 7MiB before/after evidence as well."""
    t=private_read(trial)
    if not (t and t.get('stage')=='final' and t.get('error') is None
            and t.get('r556_app_left_on_board') is True
            and t.get('r550_restored') is False
            and t.get('model_storage_nvs_verified') is True
            and t.get('two_independent_factory_reads_equal') is True
            and t.get('storage_capture_blocks')==112
            and t.get('fresh_storage_bytes')==0x700000
            and t.get('verified_blocks')==112
            and t.get('post_model_verified_blocks')==48
            and t.get('post_storage_verified_blocks')==112
            and t.get('region')=='0x900000'
            and type(t.get('fresh_storage_sha256')) is str
            and len(t['fresh_storage_sha256'])==64
            and t.get('baseline_sha256')==t['fresh_storage_sha256']
            and type(t.get('smoke')) is dict
            and t['smoke'].get('boot_only_gate_passed') is True):
        return False
    return r556_enabled(policy=policy,trial=trial,manifest=manifest,app=app)


def r595_prewrite_abort_preserves_r556(t:dict|None)->bool:
    """Only an independently audited R595 abort with zero APP writes.

    USB read corruption is not an APP flash. A missing, active, or ambiguous
    transaction must keep the incremental WSS protocol disabled.
    """
    receipt=private_read(R595_ZERO_WRITE_RECOVERY)
    p=R595_TRIAL.parent/'esptool-operations.log'
    if not (receipt and t and
            t.get('stage')=='final' and
            t.get('error')=='RuntimeError:R562_READ64K_FAILED_0x9a0000' and
            t.get('r587_app_left_on_board') is False and
            t.get('r556_restored') is False and
            t.get('r556_app_sha256')==R556_EXPECTED and
            t.get('physical_mac')==EXPECTED_BOARD_MAC and
            receipt.get('schema')==1 and
            receipt.get('stage')=='r598_verified_r556_no_write_continuity' and
            receipt.get('r556_app_sha256')==R556_EXPECTED and
            receipt.get('r587_write_attempted') is False and
            receipt.get('original_r556_app_verified') is True and
            type(receipt.get('esptool_log_sha256')) is str and
            len(receipt['esptool_log_sha256'])==64 and
            p.is_file() and not p.is_symlink() and
            p.stat().st_uid==os.getuid() and not p.stat().st_mode&0o077):
        return False
    try:
        import hashlib
        text=p.read_text(errors='replace')
        operations=[z for z in text.splitlines() if z.startswith(
            ('R487_ESPT ','R562_CHUNK '))]
        if (not operations or any('write_flash' in op or 'erase_flash' in op
                                  for op in operations)
            or any(op.startswith('R487_ESPT ') and
                   not (' verify_flash ' in op or ' read_flash ' in op)
                   for op in operations)
            or any(op.startswith('R562_CHUNK ') and
                   not (' verify_flash ' in op or ' read_flash ' in op)
                   for op in operations)):
            return False
        return (hashlib.sha256(p.read_bytes()).hexdigest()==
                receipt['esptool_log_sha256'])
    except (OSError,TypeError,ValueError):
        return False


def r595_r587_enabled(*,policy:Path=POLICY,trial:Path=R595_TRIAL,
                     manifest:Path=R587_RELEASE,app:Path=R587_IMAGE)->bool:
    """Fail closed unless SAME exact new APP was read back and USB recovered.

    R562's R556 gate is preserved for verified rollback only. An old R556
    receipt never enables R587 without a fresh physical transaction.
    """
    p=private_read(policy);t=private_read(trial);m=private_read(manifest)
    if not (p and t and m and p.get('schema')==1 and p.get('enabled') is True
            and p.get('scope')=='r587_app_only_incremental_wss'
            and p.get('candidate_sha256')==R587_EXPECTED
            and t.get('stage')=='final' and t.get('error') is None
            and t.get('r587_app_left_on_board') is True
            and t.get('r556_restored') is False
            and t.get('r587_app_sha256')==R587_EXPECTED
            and t.get('r556_app_sha256')==R556_EXPECTED
            and t.get('physical_mac')==EXPECTED_BOARD_MAC
            and t.get('two_independent_factory_reads_equal') is True
            and t.get('storage_capture_blocks')==112
            and t.get('post_storage_verified_blocks')==112
            and t.get('post_model_verified_blocks')==48
            and t.get('model_storage_nvs_verified') is True
            and t.get('dsh_3080_pid_unchanged') is True
            and t.get('other_profile_pid_unchanged') is True
            and type(t.get('smoke')) is dict
            and t['smoke'].get('boot_only_gate_passed') is True
            and type(t.get('services')) is dict
            and t['services'].get('voice_verified') is True
            and t['services'].get('supervisor_restored') is True
            and m.get('schema')==1 and m.get('complete_build') is True
            and m.get('project_version')=='R587'
            and m.get('base_version')=='R556'
            and m.get('base_app_sha256')==R556_EXPECTED
            and m.get('app_sha256')==R587_EXPECTED
            and m.get('r556_preservation_changes')==[
                'CMakeLists.txt','main/main.c','main/r268_lan_transport.c']):
        return False
    try:
        import hashlib
        binary=Path(app)
        if (binary.is_symlink() or binary.parent.is_symlink() or
            not binary.is_file() or binary.stat().st_uid!=os.getuid() or
            binary.stat().st_mode&0o077 or
            not 3000000<binary.stat().st_size<0x5f0000 or
            binary.stat().st_size!=m.get('app_bytes')):
            return False
        blob=binary.read_bytes()
        return bool(hashlib.sha256(blob).hexdigest()==R587_EXPECTED and
                    blob.find(bytes.fromhex('3254cdab'))==32 and
                    blob[48:80].split(bytes([0]),1)[0]==b'R587')
    except (OSError,ValueError,TypeError):
        return False


def r603_r587_enabled(*,policy:Path=POLICY,trial:Path=R603_TRIAL,
                     manifest:Path=R587_RELEASE,app:Path=R587_IMAGE,
                     factory1:Path=R603_FACTORY_1,factory2:Path=R603_FACTORY_2,
                     storage:Path=R603_STORAGE)->bool:
    """Enable only signed R603 real chip-side proof of ALL physical regions.

    Serial backup copies are NOT misrepresented as two actual reads. Both
    factory backups must be complete, exact, separately chip-MD5-verified,
    with any mismatching flash cells read from the real board.
    """
    p=private_read(policy);t=private_read(trial);m=private_read(manifest)
    c=t.get('physical_integrity_counters') if t else None
    if not (p and t and m and isinstance(c,dict) and
            p.get('schema')==1 and p.get('enabled') is True and
            p.get('scope')=='r587_app_only_incremental_wss' and
            p.get('candidate_sha256')==R587_EXPECTED and
            t.get('stage')=='final' and t.get('error') is None and
            t.get('r587_app_left_on_board') is True and
            t.get('r556_restored') is False and
            t.get('r556_app_sha256')==R556_EXPECTED and
            t.get('r587_app_sha256')==R587_EXPECTED and
            t.get('physical_mac')==EXPECTED_BOARD_MAC and
            t.get('two_full_factory_md5_passes') is True and
            c.get('factory_verified_pass_a_blocks512')==12 and
            c.get('factory_verified_pass_b_blocks512')==12 and
            c.get('storage_verified_pre_blocks512')==14 and
            c.get('storage_verified_pre_confirmation_blocks512')==14 and
            c.get('storage_verified_post_blocks512')==14 and
            c.get('model_verified_pre_blocks512')==6 and
            c.get('model_verified_post_blocks512')==6 and
            t.get('storage_capture_blocks')==112 and
            t.get('post_storage_verified_blocks')==112 and
            t.get('post_model_verified_blocks')==48 and
            t.get('model_storage_nvs_verified') is True and
            t.get('no_model_storage_nvs_partition_writes') is True and
            t.get('dsh_3080_pid_unchanged') is True and
            t.get('other_profile_pid_unchanged') is True and
            isinstance(t.get('smoke'),dict) and
            t['smoke'].get('boot_only_gate_passed') is True and
            isinstance(t.get('services'),dict) and
            t['services'].get('voice_verified') is True and
            t['services'].get('supervisor_restored') is True and
            m.get('schema')==1 and m.get('complete_build') is True and
            m.get('project_version')=='R587' and
            m.get('base_version')=='R556' and
            m.get('app_sha256')==R587_EXPECTED and
            m.get('base_app_sha256')==R556_EXPECTED):
        return False
    try:
        import hashlib
        def acceptable(f,n,h):
            f=Path(f)
            return (f.is_file() and not f.is_symlink() and
                    f.stat().st_uid==os.getuid() and
                    not f.stat().st_mode&0o077 and
                    f.stat().st_size==n and
                    hashlib.sha256(f.read_bytes()).hexdigest()==h)
        full=t.get('full_factory_backup_sha256')
        storage_digest=t.get('fresh_storage_sha256')
        # The storage Path parameter and its expected SHA256 must remain
        # distinct. Do not accidentally use a hex digest as a filename.
        if not (isinstance(full,str) and len(full)==64 and
                isinstance(storage_digest,str) and len(storage_digest)==64 and
                acceptable(factory1,0x5f0000,full) and
                acceptable(factory2,0x5f0000,full) and
                acceptable(storage,0x700000,storage_digest)):
            return False
        binary=Path(app)
        if not (binary.is_file() and not binary.is_symlink() and
                not binary.stat().st_mode&0o077 and
                binary.stat().st_uid==os.getuid() and
                binary.stat().st_size==m.get('app_bytes') and
                3000000<binary.stat().st_size<0x5f0000):
            return False
        blob=binary.read_bytes()
        return (hashlib.sha256(blob).hexdigest()==R587_EXPECTED and
                blob.find(bytes.fromhex('3254cdab'))==32 and
                blob[48:80].split(bytes([0]),1)[0]==b'R587')
    except (OSError,ValueError,TypeError):return False


def r603_signed_zero_write_recovers_r556(t:dict|None)->bool:
    """After a false-positive MD5 text check, verify original R556 on-chip.

    Requires independent R606 read-only physical operation and exact audit
    of all R603 subprocess commands. Never clears a real APP write record.
    """
    receipt=private_read(R603_ZERO_WRITE_RECOVERY)
    p=R603_TRIAL.parent/'commands-audit.log'
    if not (receipt and t and t.get('stage')=='final' and
            t.get('error')=='RuntimeError:R603_model_verified_pre_PHYSICAL_MD5_MISMATCH_0' and
            t.get('r587_app_left_on_board') is False and
            t.get('r556_restored') is False and
            t.get('r556_app_sha256')==R556_EXPECTED and
            t.get('physical_mac')==EXPECTED_BOARD_MAC and
            receipt.get('schema')==1 and
            receipt.get('stage')=='r606_verified_r556_zero_write_continuity' and
            receipt.get('on_chip_r556_app_verified') is True and
            receipt.get('new_app_write_attempted') is False and
            receipt.get('r556_app_sha256')==R556_EXPECTED and
            type(receipt.get('r603_audit_sha256')) is str and
            len(receipt['r603_audit_sha256'])==64 and
            p.is_file() and not p.is_symlink() and
            p.stat().st_uid==os.getuid() and not p.stat().st_mode&0o077):
        return False
    try:
        import hashlib
        data=p.read_bytes()
        lines=data.decode('utf8','replace').splitlines()
        if (not lines or any('write_flash' in x or 'erase_flash' in x
                             for x in lines) or
            any(not x.startswith(('ESP read_mac ', 'ESP read_flash ',
                                 'ESP verify_flash ')) for x in lines)):
            return False
        return hashlib.sha256(data).hexdigest()==receipt['r603_audit_sha256']
    except (OSError,ValueError,TypeError):return False


def r607_r587_enabled(*,policy:Path=POLICY)->bool:
    return r603_r587_enabled(
        policy=policy,trial=R607_TRIAL,
        factory1=R607_FACTORY_1,factory2=R607_FACTORY_2,
        storage=R607_STORAGE)


def r550_prewrite_abort_proved_from_r557(t:dict|None)->bool:
    """Restore R550 activation ONLY after a verified *zero-write* abort.

    A failed APP write, missing RC, unknown tool command, partial log, or
    tampered receipt can never use the stale R550 proof.
    """
    if not (t and t.get('stage')=='final' and
            t.get('r556_app_left_on_board') is False and
            t.get('r550_restored') is False and
            t.get('r550_app_sha256')==R550_EXPECTED and
            t.get('physical_mac')==EXPECTED_BOARD_MAC and
            t.get('scope')=='factory_APP_only_0x10000_no_other_flash_regions' and
            type(t.get('error')) is str and
            t['error'].startswith('RuntimeError:ESPTOOL_verify_flash_FAILED_0x900000;') and
            'ROLLBACK_FAILED' not in t['error'] and
            type(t.get('services')) is dict and
            t['services'].get('voice_verified') is True and
            t['services'].get('supervisor_restored') is True):
        return False
    log=R556_TRIAL.parent/'esptool-operations.log'
    try:
        import hashlib
        if (log.is_symlink() or log.parent.is_symlink() or
                not log.is_file() or log.stat().st_uid!=os.getuid() or
                log.stat().st_size>250000):
            return False
        lines=[v.strip() for v in log.read_text().splitlines()
               if v.startswith('R487_ESPT ') or v.startswith('RC ')]
        expected=[
            'R487_ESPT read_flash 0x8000 before-partition.bin','RC 0',
            'R487_ESPT verify_flash 0x10000 dafeiyu_h4_audio_smoke.bin','RC 0',
            'R487_ESPT verify_flash 0x600000 fresh-r412-full-model.bin','RC 0',
            'R487_ESPT verify_flash 0x900000 fresh-original-storage-full-7m.bin','RC 2',
            'R487_ESPT verify_flash 0x10000 dafeiyu_h4_audio_smoke.bin','RC 0',
            'R487_ESPT verify_flash 0x600000 fresh-r412-full-model.bin','RC 0',
            'R487_ESPT verify_flash 0x900000 fresh-original-storage-full-7m.bin','RC 2']
        if lines!=expected:return False
        # The original APP was validated on-device *after* the abort, and no
        # write-flash command was ever issued. Keep exact R550 release proof.
        old=R550_APP
        return (old.is_file() and not old.is_symlink()
                and hashlib.sha256(old.read_bytes()).hexdigest()==R550_EXPECTED)
    except (OSError,ValueError,TypeError,UnicodeError):
        return False



def r550_prewrite_abort_proved_from_r558(t:dict|None)->bool:
    """Only a known R558 no-write UART abort may retain original R550 PCM.

    Do not interpret a streaming timeout as content mismatch; do not trust
    stdout alone, partial event lists, or a hypothetical rollback.
    """
    if not (t and t.get('stage')=='final' and
            t.get('r556_app_left_on_board') is False and
            t.get('r550_restored') is False and
            t.get('r550_app_sha256')==R550_EXPECTED and
            t.get('physical_mac')==EXPECTED_BOARD_MAC and
            t.get('scope')=='factory_APP_only_0x10000_no_other_flash_regions' and
            t.get('error')==(
                'RuntimeError:R558_STORAGE_CHUNK_VERIFY_FAILED_3;'
                'BASELINE_REVERIFY_FAILED:RuntimeError:ESPTOOL_verify_flash_FAILED_0x600000')
            and type(t.get('services')) is dict and
            t['services'].get('voice_verified') is True and
            t['services'].get('supervisor_restored') is True):
        return False
    log=R558_TRIAL.parent/'esptool-operations.log'
    try:
        import hashlib
        if (log.is_symlink() or log.parent.is_symlink() or not log.is_file()
                or log.stat().st_uid!=os.getuid()
                or log.stat().st_mode&0o077 or log.stat().st_size>250000):
            return False
        commands=[line.strip() for line in log.read_text().splitlines()
                  if line.startswith(('R487_ESPT ','R558_ESPT ','RC '))]
        expected=[
            'R487_ESPT read_flash 0x8000 before-partition.bin','RC 0',
            'R487_ESPT verify_flash 0x10000 dafeiyu_h4_audio_smoke.bin','RC 0',
            'R487_ESPT verify_flash 0x600000 fresh-r412-full-model.bin','RC 0',
            'R558_ESPT verify_storage_1MiB 0x900000 part=1/7','RC 0',
            'R558_ESPT verify_storage_1MiB 0xa00000 part=2/7','RC 0',
            'R558_ESPT verify_storage_1MiB 0xb00000 part=3/7','RC 1',
            'R487_ESPT verify_flash 0x10000 dafeiyu_h4_audio_smoke.bin','RC 0',
            'R487_ESPT verify_flash 0x600000 fresh-r412-full-model.bin','RC 2']
        return (commands==expected and
                R550_APP.is_file() and not R550_APP.is_symlink()
                and hashlib.sha256(R550_APP.read_bytes()).hexdigest()==R550_EXPECTED)
    except (OSError,ValueError,TypeError,UnicodeError):
        return False


def r550_recovered_from_r556(t:dict|None)->bool:
    return bool(t and t.get('stage')=='final' and
        t.get('r550_restored') is True and
        t.get('r556_app_left_on_board') is False and
        t.get('model_storage_nvs_verified') is True and
        t.get('physical_mac')==EXPECTED_BOARD_MAC and
        type(t.get('services')) is dict and
        t['services'].get('voice_verified') is True and
        t['services'].get('supervisor_restored') is True)


def r511_recovered_from_r550(t:dict|None)->bool:
    return bool(t and t.get('stage')=='final' and
        t.get('r511_restored') is True and
        t.get('r550_app_left_on_board') is False and
        t.get('model_storage_nvs_verified') is True and
        t.get('physical_mac')==EXPECTED_BOARD_MAC and
        type(t.get('services')) is dict and
        t['services'].get('voice_verified') is True and
        t['services'].get('supervisor_restored') is True)


def r510_recovered_from_r511(t:dict|None)->bool:
    return bool(t and t.get('stage')=='final' and
        t.get('r510_restored') is True and
        t.get('r511_app_left_on_board') is False and
        t.get('model_storage_nvs_verified') is True and
        t.get('physical_mac')==EXPECTED_BOARD_MAC and
        type(t.get('services')) is dict and
        t['services'].get('voice_verified') is True and
        t['services'].get('supervisor_restored') is True)


def r509_recovered_from_r510(t:dict|None)->bool:
    return bool(t and t.get('stage')=='final' and
        t.get('old_r509_restored') is True and
        t.get('r510_app_left_on_board') is False and
        t.get('model_storage_nvs_verified') is True and
        t.get('physical_mac')==EXPECTED_BOARD_MAC and
        type(t.get('services')) is dict and
        t['services'].get('voice_verified') is True and
        t['services'].get('supervisor_restored') is True)


def _production_source(trial:Path, manifest:Path)->bool:
    # Dynamic test fixtures and alternate release comparisons MUST NOT
    # inherit the host machine's unrelated latest physical flash transaction.
    # Only this immutable private historical source can select R619/R614.
    return (Path(trial)==R640_ARCHIVE/"pcm/TRIAL.json" and
            Path(manifest)==R640_ARCHIVE/"pcm/MANIFEST.json")


def enabled(*,policy:Path=POLICY,trial:Path=TRIAL,
            manifest:Path=MANIFEST)->bool:
    # Only production's genuine original trial switches to the newest APP.
    # Test fixtures may inject their own legacy paths without consulting
    # live board receipts. An incomplete new flash always disables WSS PCM.
    # R597: in-progress and failed R587 physical attempts revoke old R556
    # eligibility immediately. Restore old only after verified physical
    # rollback; never use a stale successful R562 record after an APP write.
    # New APP attempts supersede successful old R556 authorization.
    # Never fall back to R595 or R562 while R603 is in progress/ambiguous.
    # R621 physically supersedes R615. Once attempted, R614 evidence is
    # historical: no WSS PCM on pending/failed/ambiguous R619 flash.
    # R641: current R619 flash authorization stays with its own signed gate.
    # Historical fallback receipts must now be from the sealed private pack.
    # Test fixtures explicitly using alternate paths keep their own contract.
    if _production_source(trial,manifest) and not r640_archive_valid():
        return False
    if _production_source(trial,manifest) and (
        R621_TRIAL.exists() or R621_TRIAL.is_symlink()):
        current=private_read(R621_TRIAL)
        if (current and current.get('stage')=='final' and
            current.get('error') is None and
            current.get('r619_app_left_on_board') is True and
            current.get('r614_restored') is False):
            from app.r622_r619_physical_gate import r619_enabled
            return r619_enabled(policy=policy)
        if (current and current.get('stage')=='final' and
            current.get('r614_restored') is True and
            current.get('model_storage_nvs_verified') is True and
            current.get('no_model_storage_nvs_partition_writes') is True and
            current.get('physical_mac')==EXPECTED_BOARD_MAC):
            from app.r616_r614_physical_gate import r614_enabled
            return r614_enabled(policy=policy)
        return False
    # R615 is the newest APP-only transaction. An in-flight, partial, or
    # damaged R614 attempt MUST NOT inherit R607's successful R587 receipt.
    if _production_source(trial,manifest) and (
        R615_TRIAL.exists() or R615_TRIAL.is_symlink()):
        current=private_read(R615_TRIAL)
        if (current and current.get('stage')=='final' and
            current.get('error') is None and
            current.get('r614_app_left_on_board') is True and
            current.get('r587_restored') is False):
            from app.r616_r614_physical_gate import r614_enabled
            return r614_enabled(policy=policy)
        if (current and current.get('stage')=='final' and
            current.get('r587_restored') is True and
            current.get('model_storage_nvs_verified') is True and
            current.get('no_model_storage_nvs_partition_writes') is True and
            current.get('physical_mac')==EXPECTED_BOARD_MAC):
            return r607_r587_enabled(policy=policy)
        return False
    if _production_source(trial,manifest) and (
        R607_TRIAL.exists() or R607_TRIAL.is_symlink()):
        current=private_read(R607_TRIAL)
        if current and current.get('stage')=='final' and current.get('r587_app_left_on_board') is True:
            return r607_r587_enabled(policy=policy)
        if (current and current.get('stage')=='final' and
            current.get('r556_restored') is True and
            current.get('model_storage_nvs_verified') is True and
            current.get('physical_mac')==EXPECTED_BOARD_MAC and
            type(current.get('services')) is dict and
            current['services'].get('voice_verified') is True):
            return r562_enabled(policy=policy,trial=R562_TRIAL,
                                manifest=R556_MANIFEST,app=R556_APP)
        return False
    if _production_source(trial,manifest) and (
        R603_TRIAL.exists() or R603_TRIAL.is_symlink()):
        current=private_read(R603_TRIAL)
        if (current and current.get('stage')=='final' and
            current.get('r587_app_left_on_board') is True):
            return r603_r587_enabled(policy=policy)
        if r603_signed_zero_write_recovers_r556(current):
            return r562_enabled(policy=policy,trial=R562_TRIAL,
                                manifest=R556_MANIFEST,app=R556_APP)
        if (current and current.get('stage')=='final' and
            current.get('r556_restored') is True and
            current.get('model_storage_nvs_verified') is True and
            current.get('physical_mac')==EXPECTED_BOARD_MAC and
            type(current.get('services')) is dict and
            current['services'].get('voice_verified') is True):
            return r562_enabled(policy=policy,trial=R562_TRIAL,
                                manifest=R556_MANIFEST,app=R556_APP)
        return False
    if _production_source(trial,manifest) and (
        R595_TRIAL.exists() or R595_TRIAL.is_symlink()):
        latest=private_read(R595_TRIAL)
        if latest and latest.get('stage')=='final' and latest.get('r587_app_left_on_board') is True:
            return r595_r587_enabled(policy=policy)
        if r595_prewrite_abort_preserves_r556(latest):
            return r562_enabled(policy=policy,trial=R562_TRIAL,
                                manifest=R556_MANIFEST,app=R556_APP)
        if (latest and latest.get('stage')=='final' and
            latest.get('r556_restored') is True and
            latest.get('model_storage_nvs_verified') is True and
            latest.get('physical_mac')==EXPECTED_BOARD_MAC):
            return r562_enabled(policy=policy,trial=R562_TRIAL,
                                manifest=R556_MANIFEST,app=R556_APP)
        return False
    if _production_source(trial,manifest) and (
        R562_TRIAL.exists() or R562_TRIAL.is_symlink()):
        active=private_read(R562_TRIAL)
        if active and active.get('stage')=='final' and active.get('r556_app_left_on_board') is True:
            return r562_enabled(policy=policy,trial=R562_TRIAL,
                                manifest=R556_MANIFEST,app=R556_APP)
        if r550_recovered_from_r556(active):
            return r550_enabled(policy=policy,trial=R550_TRIAL,
                                manifest=R550_MANIFEST,app=R550_APP)
        # In-progress, failed, or unrecovered attempts cannot reuse stale
        # successful R550 evidence; fail closed while USB owner is uncertain.
        return False
    if _production_source(trial,manifest) and (
        R558_TRIAL.exists() or R558_TRIAL.is_symlink()):
        r558=private_read(R558_TRIAL)
        if r558 and r558.get('stage')=='final' and r558.get('r556_app_left_on_board') is True:
            return r556_enabled(policy=policy,trial=R558_TRIAL,
                                manifest=R556_MANIFEST,app=R556_APP)
        if (r550_recovered_from_r556(r558) or
                r550_prewrite_abort_proved_from_r558(r558)):
            return r550_enabled(policy=policy,trial=R550_TRIAL,
                                manifest=R550_MANIFEST,app=R550_APP)
        # A missing or partial chunk result is never a successful release.
        return False
    if _production_source(trial,manifest) and (
        R556_TRIAL.exists() or R556_TRIAL.is_symlink()):
        r556=private_read(R556_TRIAL)
        if r556 and r556.get('stage')=='final' and r556.get('r556_app_left_on_board') is True:
            return r556_enabled(policy=policy,trial=R556_TRIAL,
                                manifest=R556_MANIFEST,app=R556_APP)
        if (r550_recovered_from_r556(r556) or
                r550_prewrite_abort_proved_from_r557(r556)):
            return r550_enabled(policy=policy,trial=R550_TRIAL,
                                manifest=R550_MANIFEST,app=R550_APP)
        return False
    if _production_source(trial,manifest) and (
        R550_TRIAL.exists() or R550_TRIAL.is_symlink()):
        r550=private_read(R550_TRIAL)
        if r550 and r550.get('stage')=='final' and r550.get('r550_app_left_on_board') is True:
            return r550_enabled(policy=policy,trial=R550_TRIAL,
                                manifest=R550_MANIFEST,app=R550_APP)
        if r511_recovered_from_r550(r550):
            return r511_enabled(policy=policy,trial=R511_TRIAL,
                                manifest=R511_MANIFEST)
        # Any in-progress, corrupt or unverified R550 flash disables the
        # stream gate. Stale R511 transaction must not authorize R550.
        return False
    # Historical R511/R510 fixture comparisons must retain their own proof
    # chain, without consulting this Mac's newer R619 physical transaction.
    if Path(trial)==TRIAL and Path(manifest)==MANIFEST and (
        R511_TRIAL.exists() or R511_TRIAL.is_symlink()):
        r511=private_read(R511_TRIAL)
        if r511 and r511.get('stage')=='final' and r511.get('r511_app_left_on_board') is True:
            return r511_enabled(policy=policy,trial=R511_TRIAL,manifest=R511_MANIFEST)
        if r510_recovered_from_r511(r511):
            return r510_enabled(policy=policy,trial=R510_TRIAL,
                                manifest=R510_MANIFEST)
        # Any in-progress, interrupted, or unverified R511 write blocks
        # incremental PCM, even if an old R510 receipt remains valid.
        return False
    if Path(trial)==TRIAL and Path(manifest)==MANIFEST and (
        R510_TRIAL.exists() or R510_TRIAL.is_symlink()):
        current=private_read(R510_TRIAL)
        if current and current.get('stage')=='final' and current.get('r510_app_left_on_board') is True:
            return r510_enabled(policy=policy,trial=R510_TRIAL,
                                manifest=R510_MANIFEST)
        if r509_recovered_from_r510(current):
            return _r509_enabled(policy=policy,trial=trial,manifest=manifest)
        return False
    return _r509_enabled(policy=policy,trial=trial,manifest=manifest)

if __name__=='__main__':
    import sys
    if sys.argv!=[sys.argv[0],'--enabled']:raise SystemExit('USAGE --enabled')
    print('1' if enabled() else '0')
