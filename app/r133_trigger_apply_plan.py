"""Compile an R121 offline proposal into a R133 on-site-only transaction.

This module never opens USB, sends bytes, writes NVS or approves a touch.
Runtime must verify the exact device CAPS and physically received TAP receipt.
"""
from __future__ import annotations
from dataclasses import dataclass
import re

CAPS='@@DFTRIGGER1 READY version=1 persistent=nvs local_confirmation=1 dynamic=1'
WAIT='@@DFTRIGGER1 WAIT_LOCAL_TOUCH seconds=30'
STAGING='@@DFTRIGGER1 STAGING'
READY=re.compile(r'^@@DFTRIGGER1 APPLIED count=35 crc32=([0-9a-f]{8})$')
READBACK=re.compile(r'^@@DFTRIGGER1 RULE id=(m\d{3}) group=(manual|tap|idle|bonus|work|drag|boot) crc32=([0-9a-f]{8})$')
ALLOWED={'tap','idle','bonus','work','manual','drag'}
FACTORY={0,1,2,3,8,10,11,13,14,15,16,18,19,20,23,24,25,26,27,28,30,61,62,67,70,71,72,73,75,80,81,83,97,99,105}
class TriggerPlanError(RuntimeError):pass
@dataclass(frozen=True)
class RuleTransaction:
    firmware_source_sha256:str
    commands:tuple[str,...]
    expected:dict[str,str]
    on_device:bool=False

def compile_offline(proposal:dict,*,trusted_r121_source_sha256:str)->RuleTransaction:
    if proposal.get('schema')!=1 or proposal.get('on_device') is not False or \
       proposal.get('status')!='offline_review_not_applied' or \
       proposal.get('preserve_all_original_motions') is not True or \
       proposal.get('firmware_source_sha256')!=trusted_r121_source_sha256:
        raise TriggerPlanError('source_mismatch_or_proposal_not_offline')
    expected={}
    for item in proposal.get('overrides',[]):
        if not isinstance(item,dict):raise TriggerPlanError('malformed_rule')
        key=item.get('id');kind=item.get('target_trigger')
        if not isinstance(key,str) or re.fullmatch('m[0-9]{3}',key) is None:
            raise TriggerPlanError('invalid_motion_id')
        if int(key[1:]) not in FACTORY or key=='m000' or kind not in ALLOWED or key in expected:
            raise TriggerPlanError('untrusted_or_duplicate_rule')
        expected[key]=kind
    commands=tuple(f'@@DFTRIGGER1 SET id={key} group={val}' for key,val in sorted(expected.items()))
    return RuleTransaction(trusted_r121_source_sha256,commands,expected)

def confirm_applied(transaction:RuleTransaction,applied_response:str,readback:dict[str,str])->bool:
    match=READY.fullmatch(applied_response)
    if match is None or set(readback)!=set(transaction.expected):
        return False
    crc=match[1]
    for key,wanted in transaction.expected.items():
        parsed=READBACK.fullmatch(readback[key])
        if not parsed or parsed[1]!=key or parsed[2]!=wanted or parsed[3]!=crc:
            return False
    return True
