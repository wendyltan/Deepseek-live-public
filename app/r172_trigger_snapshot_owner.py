"""R172 genuine, single-USB-owner, read-only 106 binding snapshot.

Invoked only during physical microphone owner's verified idle loop. Does not
issue ARM/BEGIN/SET/COMMIT, open another serial connection, or touch audio.
"""
from __future__ import annotations
import json,re,time
from pathlib import Path
from app.r142_trigger_owner_apply import private,write_report
from app.r151_trigger106_owner import STATUS as V2_STATUS, CAPS, Apply106Error
ROOT=Path.home()/'Library/Application Support/Deepseek-live/companion-native'
REQUEST=ROOT/'trigger-readback-request.json'
RESULT=ROOT/'trigger-readback-result.json'
V1_STATUS=re.compile(r'^@@DFTRIGGER1 STATE count=35 crc32=([0-9a-f]{8}) stage=([01]) armed=([01]) nvs=1$')
V1_RULE=re.compile(r'^@@DFTRIGGER1 RULE id=(m\d{3}) group=(manual|tap|idle|bonus|work|drag|boot) crc32=([0-9a-f]{8})$')
V2_RULE=re.compile(r'^@@DFTRIGGER2 RULE id=(m\d{3}) group=(manual|tap|idle|bonus|work|drag|boot) crc32=([0-9a-f]{8})$')
FACTORY={0,1,2,3,8,10,11,13,14,15,16,18,19,20,23,24,25,26,27,28,30,61,62,67,70,71,72,73,75,80,81,83,97,99,105}
def query(port,command,expect,timeout=3):
    """Read only response of either DFTRIGGER1 or DFTRIGGER2, microphone first."""
    kind=command.split(' ',1)[0]
    payload=(command+'\n').encode('ascii')
    if port.write(payload)!=len(payload):raise Apply106Error('short_usb_write')
    port.flush()
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        raw=port.readline()
        if not raw:continue
        message=raw.decode('ascii','replace').strip()
        if message.startswith('@@DFVOICE3 '):
            if hasattr(port,'unread'):port.unread(raw)
            raise Apply106Error('mic_started_cancel_snapshot')
        if 'Guru Meditation' in message or 'Rebooting' in message:
            raise Apply106Error('device_reset_during_readback')
        if message.startswith(kind+' '):
            if 'NACK' in message:raise Apply106Error('device_rule_nack_'+message[:85])
            if callable(expect) and expect(message):return message
            if message==expect:return message
            raise Apply106Error('unexpected_rule_reply_'+message[:90])
    raise Apply106Error('rule_readback_timeout_'+command)


def physical_snapshot(port, session_id:str):
    query(port,'@@DFTRIGGER2 CAPS',CAPS,timeout=2.5)
    s2=query(port,'@@DFTRIGGER2 STATUS',lambda x:V2_STATUS.fullmatch(x) is not None,timeout=3)
    match=V2_STATUS.fullmatch(s2)
    if match[3]!='0':raise Apply106Error('device_stage_open')
    s1=query(port,'@@DFTRIGGER1 STATUS',lambda x:V1_STATUS.fullmatch(x) is not None,timeout=3)
    old=V1_STATUS.fullmatch(s1)
    if old[2]!='0':raise Apply106Error('legacy_stage_open')
    v2_crc=match[1];v1_crc=old[1]
    rules={}
    for idx in range(106):
        ident=f'm{idx:03d}'
        raw=query(port,f'@@DFTRIGGER2 GET id={ident}',
            lambda x:V2_RULE.fullmatch(x) is not None,timeout=3)
        row=V2_RULE.fullmatch(raw)
        if row[1]!=ident or row[3]!=v2_crc:raise Apply106Error('v2_readback_inconsistent_'+ident)
        rules[ident]=row[2]
    legacy={}
    for idx in sorted(FACTORY):
        ident=f'm{idx:03d}'
        raw=query(port,f'@@DFTRIGGER1 GET id={ident}',
            lambda x:V1_RULE.fullmatch(x) is not None,timeout=3)
        row=V1_RULE.fullmatch(raw)
        if row[1]!=ident or row[3]!=v1_crc:raise Apply106Error('legacy_readback_inconsistent_'+ident)
        legacy[ident]=row[2]
    if rules['m000']!='boot' or legacy['m000']!='boot':
        raise Apply106Error('boot_protection_failed')
    if match[2]=='0':
        for ident in legacy:
            if legacy[ident]!=rules[ident]:
                raise Apply106Error('inactive_v2_did_not_inherit_old_nvs_'+ident)
    again=query(port,'@@DFTRIGGER2 STATUS',lambda x:V2_STATUS.fullmatch(x) is not None,timeout=3)
    if V2_STATUS.fullmatch(again).groups()[:2]!=match.groups()[:2]:raise Apply106Error('device_v2_changed_during_read')
    return {'schema':1,'source':'real_esp32_usb_readback','session_id':session_id,
            'updated_at_unix':time.time(),'count':106,'v2_active':match[2]=='1',
            'v2_crc32':v2_crc,'legacy_crc32':v1_crc,
            'legacy_count':len(legacy),'legacy_rules':legacy,'rules':rules}

def consume_snapshot(port,native,*,request=REQUEST,report=RESULT,clock=time.time,reader=physical_snapshot,log=print):
    if not request.exists():return False
    if not private(request,512):
        log('R172_REJECT_INSECURE_READBACK_REQUEST');return False
    try:
        params=json.loads(request.read_text())
        request.unlink()
        if (params.get('schema')!=1 or params.get('action')!='read_current_rules'
          or params.get('session_id')!=native.projector.session_id
          or not isinstance(params.get('at'),(float,int))
          or not 0<=clock()-params['at']<=30):
            raise Apply106Error('wrong_or_expired_session')
        if not native.bound or native.projector.state.get('phase')!='idle' or native.projector.turn_id is not None:
            raise Apply106Error('audio_priority')
        result=reader(port,native.projector.session_id)
        if (result['count']!=106 or len(result['rules'])!=106 or result['legacy_count']!=35):
            raise Apply106Error('incomplete_rules_readback')
        write_report(result,report)
        log('R172_PHYSICAL_106_READBACK_VERIFIED active='+str(result['v2_active'])+
            ' legacy_crc='+result['legacy_crc32'])
        return True
    except (OSError,ValueError,TypeError,KeyError,Apply106Error) as exc:
        write_report({'schema':1,'source':'readback_failed','updated_at_unix':clock(),
                      'reason':str(exc)[:150]},report)
        log('R172_READBACK_FAILED '+str(exc)[:90])
        return False
