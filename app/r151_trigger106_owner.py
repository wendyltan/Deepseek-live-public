"""Physical-touch-authorized 106-motion R150 NVS map2 via sole voice USB owner.
No firmware/SD writes. The Mac action is explicit, SHA-bound, idle-gated, and
one-use. Never assumes a missing asset exists.
"""
from __future__ import annotations
import hashlib,json,os,re,time
from pathlib import Path
from app.r142_trigger_owner_apply import private,write_report,ApplyFailure
ROOT=Path.home()/'Library/Application Support/Deepseek-live'
REQUEST=ROOT/'companion-native/trigger106-apply-request.json'
PROPOSAL=ROOT/'motion-library/trigger-proposal-v2.json'
REPORT=ROOT/'companion-native/trigger106-apply-result.json'
CAPS='@@DFTRIGGER2 READY version=2 count=106 legacy_nvs_preserved=1 touch=1'
STATUS=re.compile(r'^@@DFTRIGGER2 STATE count=106 crc32=([0-9a-f]{8}) active=([01]) stage=([01]) armed=([01])$')
ALLOWED={'manual','tap','idle','bonus','work','drag'}
class Apply106Error(ApplyFailure):pass

def compile_rules(obj):
    if not (obj.get('schema')==2 and obj.get('status')=='local_pending_not_on_device'
            and obj.get('count')==106 and obj.get('protect_m000') is True):
        raise Apply106Error('proposal_schema_invalid')
    expected={}
    for item in obj.get('overrides',[]):
        ident=item.get('id');group=item.get('target_trigger')
        if (not isinstance(ident,str) or re.fullmatch(r'm[0-9]{3}',ident) is None or
            not 1<=int(ident[1:])<106 or group not in ALLOWED or ident in expected):
            raise Apply106Error('invalid_or_duplicate_rule')
        expected[ident]=group
    if not 1<=len(expected)<=105:raise Apply106Error('empty_or_oversized_rules')
    return expected

def request_reply(port,command,expect,timeout=4,clock=time.monotonic):
    body=(command+'\n').encode('ascii')
    if port.write(body)!=len(body):raise Apply106Error('partial_usb_write')
    port.flush()
    deadline=clock()+timeout
    while clock()<deadline:
        part=port.readline()
        if not part:continue
        line=part.decode('ascii','replace').strip()
        if line.startswith('@@DFVOICE3 '):
            if hasattr(port,'unread'):port.unread(part)
            raise Apply106Error('user_microphone_priority')
        if 'Guru Meditation' in line or 'Rebooting' in line:
            raise Apply106Error('device_restart')
        if line.startswith('@@DFTRIGGER2 '):
            if line.startswith('@@DFTRIGGER2 NACK'):raise Apply106Error(line[-100:])
            if callable(expect):
                if expect(line):return line
            elif line==expect:return line
            else:raise Apply106Error('unexpected_reply_'+line[:80])
    raise Apply106Error('device_ack_timeout')

def transact(port,expected,*,progress=lambda value:None,clock=time.monotonic):
    request_reply(port,'@@DFTRIGGER2 CAPS',CAPS)
    state=request_reply(port,'@@DFTRIGGER2 STATUS',lambda v: STATUS.fullmatch(v) is not None)
    if STATUS.fullmatch(state)[3]=='1':raise Apply106Error('another_transaction_open')
    request_reply(port,'@@DFTRIGGER2 ARM_REQUEST','@@DFTRIGGER2 WAIT_LOCAL_TOUCH seconds=30')
    progress('waiting_for_local_tap')
    deadline=clock()+29
    while clock()<deadline:
        time.sleep(.65)
        state=request_reply(port,'@@DFTRIGGER2 STATUS',lambda v: STATUS.fullmatch(v) is not None)
        if STATUS.fullmatch(state)[4]=='1':break
    else:raise Apply106Error('physical_touch_not_confirmed_in_30s')
    progress('touch_confirmed')
    begun=False;committed=False
    try:
        request_reply(port,'@@DFTRIGGER2 BEGIN','@@DFTRIGGER2 STAGING')
        begun=True
        for ident,group in sorted(expected.items()):
            request_reply(port,f'@@DFTRIGGER2 SET id={ident} group={group}',
                f'@@DFTRIGGER2 STAGED id={ident} group={group}')
        progress('commit_verifying')
        response=request_reply(port,'@@DFTRIGGER2 COMMIT',
             lambda v:re.fullmatch(r'@@DFTRIGGER2 APPLIED count=106 crc32=[0-9a-f]{8}',v) is not None,
             timeout=8)
        committed=True
        crc=response.rsplit('crc32=',1)[-1]
        for ident,group in sorted(expected.items()):
            request_reply(port,f'@@DFTRIGGER2 GET id={ident}',
                f'@@DFTRIGGER2 RULE id={ident} group={group} crc32={crc}')
        request_reply(port,'@@DFTRIGGER2 GET id=m000',
            f'@@DFTRIGGER2 RULE id=m000 group=boot crc32={crc}')
        state=request_reply(port,'@@DFTRIGGER2 STATUS',lambda v:STATUS.fullmatch(v) is not None)
        match=STATUS.fullmatch(state)
        if not match or match[1]!=crc or match[2]!='1':
            raise Apply106Error('status_crc_or_active_mismatch')
        progress('verified')
        return {'verified':True,'applied_count':len(expected),'crc32':crc,
                'device_map2_active':True}
    except Exception:
        if begun and not committed:
            try:request_reply(port,'@@DFTRIGGER2 ABORT','@@DFTRIGGER2 ABORTED',timeout=2)
            except Exception:pass
        raise

def consume_request(port,native,*,request=REQUEST,proposal=PROPOSAL,report=REPORT,
                    clock=time.time,apply=transact,log=print):
    if not request.exists():return False
    if not private(request,512):
        log('R151_V2_REQUEST_INSECURE_REJECTED');return False
    try:
        obj=json.loads(request.read_text())
        request.unlink()
        if (obj.get('schema')!=2 or obj.get('action')!='apply106_saved_rules'
             or obj.get('session_id')!=native.projector.session_id
             or not 0<=clock()-obj.get('at',-1)<=40):
            raise Apply106Error('session_not_authorized')
        if native.projector.state.get('phase')!='idle' or native.projector.turn_id is not None:
            raise Apply106Error('voice_turn_active')
        if not private(proposal,20000):raise Apply106Error('proposal_private_file_required')
        payload=proposal.read_bytes()
        if obj.get('proposal_sha256')!=hashlib.sha256(payload).hexdigest():
            raise Apply106Error('saved_proposal_changed')
        rules=compile_rules(json.loads(payload))
        def progress(phase):
            write_report({'status':phase,'verified':False,'rule_count':len(rules),
                          'proposal_sha256':obj['proposal_sha256']},report)
        progress('starting')
        result=apply(port,rules,progress=progress)
        write_report({'status':'verified',**result,
                      'proposal_sha256':obj['proposal_sha256']},report)
        log(f"R151_REAL_MAP2_106_VERIFIED count={len(rules)} crc32={result['crc32']}")
        return True
    except (Apply106Error,OSError,ValueError,KeyError,TypeError) as exc:
        write_report({'status':'failed','verified':False,'reason':str(exc)[:130]},report)
        log('R151_MAP2_NOT_VERIFIED '+str(exc)[:80])
        return False
