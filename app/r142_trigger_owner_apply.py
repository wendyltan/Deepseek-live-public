"""R142: exclusive ESP32 physical-touch-confirmed animation binding transaction.

The existing verified voice process is the only serial owner. User MUST click
Mac 'Apply' and physically tap the fish within 30s; NVS is changed only after
full 35-motion firmware CAPS, staged ACKs, and the physical-arm receipt.
No SD write, firmware flash, synthetic touch, or duplicate serial open.
"""
from __future__ import annotations
import hashlib,json,os,re,stat,tempfile,time
from pathlib import Path
from app.r133_trigger_apply_plan import CAPS,WAIT,STAGING,compile_offline,confirm_applied,TriggerPlanError
ROOT=Path.home()/'Library/Application Support/Deepseek-live'
REQUEST=ROOT/'companion-native/trigger-apply-request.json'
PROPOSAL=ROOT/'motion-library/trigger-proposal-r121.json'
REPORT=ROOT/'companion-native/trigger-apply-result.json'
TRUSTED_R121=Path('private-runtime/optional-motion-source.c')
STATUS=re.compile(r'^@@DFTRIGGER1 STATE count=35 crc32=([0-9a-f]{8}) stage=([01]) armed=([01]) nvs=1$')
class ApplyFailure(RuntimeError):pass

def private(path,max_bytes):
    try:
        st=path.lstat()
        return (stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid()
                and st.st_mode&0o077==0 and 0<st.st_size<=max_bytes
                and not path.is_symlink())
    except OSError:return False

def write_report(report,path=REPORT):
    raw=json.dumps(report,separators=(',',':'),ensure_ascii=False).encode()
    if len(raw)>5000:raise ApplyFailure('report_oversize')
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.is_symlink():raise ApplyFailure('unsafe_report')
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.trigger-report-',delete=False) as fh:
        fd=Path(fh.name);os.fchmod(fh.fileno(),0o600)
        fh.write(raw);fh.flush();os.fsync(fh.fileno())
    os.replace(fd,path)

def verified_reply(port,expected,*,timeout=3,on_idle=lambda:None):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        line=port.readline()
        if not line:
            on_idle();continue
        raw=line.decode('ascii','replace').strip()
        if '@@DFVOICE3 BEGIN' in raw or raw.startswith('@@DFVOICE3 PCM '):
            if hasattr(port,'unread'):port.unread(line)
            raise ApplyFailure('mic_priority_abort')
        if 'Guru Meditation' in raw or 'Rebooting' in raw:
            raise ApplyFailure('board_restart')
        if raw.startswith('@@DFTRIGGER1 '):
            if raw.startswith('@@DFTRIGGER1 NACK'):raise ApplyFailure('device_'+raw[12:105])
            if callable(expected):
                if expected(raw):return raw
            elif raw==expected:return raw
            else:raise ApplyFailure('unexpected_receipt_'+raw[:72])
    raise ApplyFailure('device_ack_timeout')

def command(port,cmd,expected,*,timeout=3,on_idle=lambda:None):
    payload=(cmd+'\n').encode('ascii')
    if port.write(payload)!=len(payload):raise ApplyFailure('partial_usb_write')
    port.flush()
    return verified_reply(port,expected,timeout=timeout,on_idle=on_idle)

def apply_transaction(port,tx,*,on_progress=lambda *_:None,now=time.monotonic):
    if not tx.commands:raise ApplyFailure('empty_binding_changes')
    if command(port,'@@DFTRIGGER1 CAPS',CAPS)!=CAPS:
        raise ApplyFailure('hardware_caps_missing')
    status=command(port,'@@DFTRIGGER1 STATUS',lambda line:STATUS.fullmatch(line) is not None)
    if STATUS.fullmatch(status)[2]=='1':raise ApplyFailure('other_staging_already_open')
    command(port,'@@DFTRIGGER1 ARM_REQUEST',WAIT)
    on_progress('waiting_for_local_tap')
    # Physical avatar tap must set "armed=1" on the R136 board.
    deadline=now()+29
    while now()<deadline:
        time.sleep(.7)
        status=command(port,'@@DFTRIGGER1 STATUS',
             lambda line:STATUS.fullmatch(line) is not None,timeout=2)
        if STATUS.fullmatch(status)[3]=='1':break
    else:raise ApplyFailure('local_touch_not_confirmed_within_30s')
    on_progress('touch_confirmed')
    started=False;committed=False
    try:
        command(port,'@@DFTRIGGER1 BEGIN',STAGING)
        started=True
        for cmd in tx.commands:
            parsed=re.fullmatch(r'@@DFTRIGGER1 SET id=(m\d{3}) group=([a-z]+)',cmd)
            if not parsed:raise ApplyFailure('invalid_plan_command')
            command(port,cmd,'@@DFTRIGGER1 STAGED id='+parsed[1]+' group='+parsed[2])
        on_progress('commit_verifying')
        applied=command(port,'@@DFTRIGGER1 COMMIT',
                        lambda line:line.startswith('@@DFTRIGGER1 APPLIED count=35 crc32='),
                        timeout=5)
        committed=True
        read={}
        for ident in tx.expected:
            read[ident]=command(port,'@@DFTRIGGER1 GET id='+ident,
                 lambda line:line.startswith('@@DFTRIGGER1 RULE id='+ident+' '))
        boot=command(port,'@@DFTRIGGER1 GET id=m000',
            lambda line:line.startswith('@@DFTRIGGER1 RULE id=m000 group=boot '))
        if not boot.endswith(applied.split('crc32=')[-1]):
            raise ApplyFailure('boot_crc_differed')
        if not confirm_applied(tx,applied,read):raise ApplyFailure('device_readback_mismatch')
        on_progress('verified')
        return {'verified':True,'applied_count':len(tx.expected),
                'crc32':applied.split('crc32=')[-1]}
    except Exception:
        if started and not committed:
            try:command(port,'@@DFTRIGGER1 ABORT','@@DFTRIGGER1 ABORTED',timeout=2)
            except Exception:pass
        raise

def consume_request(port,native,*,request=REQUEST,proposal=PROPOSAL,
                    report=REPORT,clock=time.time,apply=apply_transaction,log=print):
    if not request.exists():return False
    if not private(request,512):
        log('R142_TRIGGER_REQUEST_REJECT_PRIVATE_PERMISSIONS');return False
    try:
        data=json.loads(request.read_text())
        request.unlink()
        if (data.get('schema')!=1 or data.get('action')!='apply_saved_rules' or
            data.get('session_id')!=native.projector.session_id or
            not 0<=clock()-data.get('at',-1)<=40):
            raise ApplyFailure('invalid_request_session')
        if native.projector.state.get('phase')!='idle' or native.projector.turn_id is not None:
            raise ApplyFailure('audio_active')
        if not private(proposal,15000):raise ApplyFailure('proposal_not_private')
        payload=proposal.read_bytes()
        if hashlib.sha256(payload).hexdigest()!=data.get('proposal_sha256'):
            raise ApplyFailure('proposal_modified_after_approval')
        base_hash=hashlib.sha256(TRUSTED_R121.read_bytes()).hexdigest()
        tx=compile_offline(json.loads(payload),trusted_r121_source_sha256=base_hash)
        if not tx.expected or len(tx.expected)>35:raise ApplyFailure('proposal_empty_or_too_many')
        def progress(value):
            write_report({'status':value,'verified':False,'rule_count':len(tx.expected),
                          'proposal_sha256':data['proposal_sha256']},report)
        progress('starting')
        result=apply(port,tx,on_progress=progress)
        write_report({'status':'verified',**result,
                      'proposal_sha256':data['proposal_sha256']},report)
        log('R142_PHYSICAL_NVS_RULES_READBACK_VERIFIED count='+str(len(tx.expected))+
            ' crc32='+result['crc32'])
        return True
    except (ApplyFailure,TriggerPlanError,OSError,ValueError,TypeError,KeyError) as err:
        reason=str(err)[:110]
        write_report({'status':'failed','verified':False,'reason':reason},report)
        log('R142_TRIGGER_NOT_VERIFIED '+reason)
        return False
