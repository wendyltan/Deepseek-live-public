"""Verified, deliberate ESP32 voice memory for owner-directed lightweight facts.

No automatic general conversation storage, private mic audio, billable model
requests, or unsanctioned third-party memory writes. An owner explicitly says
'记住' or '帮我记住这个' after the immediately previous verified fact.
"""
from __future__ import annotations
import re,time,uuid
from app import r38_memory_loop as vault

DIRECT=re.compile(r'^(?:嘿[，, ]*)?(?:大肥鱼[，, ]*)?(?:请|麻烦你)?(?:帮我)?(?:记住|记下|保存)(?:一下|这个)?[：:，, ]*(.{0,90})[。！! ]*$')
REFERENCE=re.compile(r'^(?:嘿[，, ]*)?(?:大肥鱼[，, ]*)?(?:请|麻烦你)?(?:帮我)?(?:记住|记下|保存)(?:一下)?(?:这个|刚刚那句|我刚才说的)[。！! ]*$')
NAME_QUERY=re.compile(r'^(?:嘿[，, ]*)?(?:大肥鱼[，, ]*)?(?:你知道|你还记得|告诉我)?我(?:的)?名字(?:是|叫)(?:什么|啥)(?:呀|呢|啊|吗)?[？?。！! ]*$')

def normalize_fact(text):
    if not isinstance(text,str):return None
    t=text.strip(' ，,。！! ')
    if t.startswith('我名字叫'):
        t='我的名字叫'+t[len('我名字叫'):]
    return vault.extract(t)

def explicit_target(transcript,*,previous=None,previous_age_s=None,verified_stt=False):
    if verified_stt is not True or not isinstance(transcript,str) or len(transcript)>115:return None
    t=transcript.strip()
    if REFERENCE.fullmatch(t):
        if previous_age_s is None or previous_age_s<0 or previous_age_s>180:return None
        return normalize_fact(previous)
    match=DIRECT.fullmatch(t)
    if not match or not match[1].strip():return None
    return normalize_fact(match[1])

def is_explicit_memory_command(transcript):
    return isinstance(transcript,str) and len(transcript)<=115 and DIRECT.fullmatch(transcript.strip()) is not None

def store_explicit_fact(fact,*,verified_stt=False,store=vault.AUTOSTORE,clock=time.time):
    if verified_stt is not True or not isinstance(fact,dict):return False
    if set(fact)!={'category','value','text'}:return False
    if fact!=normalize_fact({
        'name':'我叫','likes':'我喜欢','dislikes':'我不喜欢'
    }.get(fact['category'],'')+fact['value']):return False
    if store==vault.AUTOSTORE:
        from app.r308_unified_memory import enabled,remember_verified
        if enabled():
            return remember_verified(fact) in ("saved","already_saved")
    try:
        items=vault.read_store(store)
        # User explicitly re-stating a fact is an idempotent success.
        if any(i['category']==fact['category'] and i['value']==fact['value'] for i in items):
            return True
        if fact['category']=='name':items=[i for i in items if i['category']!='name']
        if len(items)>=vault.MAX_FACTS:return False
        record={'id':uuid.uuid4().hex,**fact,'created_at':int(clock()),
                'source':'verified_esp32_user_voice'}
        vault._write(store,[*items,record])
        return any(i['id']==record['id'] and i['text']==fact['text']
                   for i in vault.read_store(store))
    except (OSError,ValueError,TypeError,KeyError):
        return False

def answer_name_question(transcript,*,verified_stt=False,store=vault.AUTOSTORE):
    if verified_stt is not True or not isinstance(transcript,str) or not NAME_QUERY.fullmatch(transcript.strip()):
        return None
    if store==vault.AUTOSTORE:
        from app.r308_unified_memory import enabled,facts_for_query as unified_lookup
        if enabled():
            facts=unified_lookup("我的名字叫什么")
            names=[x[len("称呼："):] for x in facts if x.startswith("称呼：")]
            return ('哦，你叫'+names[-1]+'。') if names else '我还没有记住你的名字。你可以说，大肥鱼，记住我的名字叫 Wendy。'
    try:items=vault.read_store(store)
    except (OSError,ValueError,TypeError):return '我还没能读取已保存的名字，你可以再让我记住一次。'
    names=[x['value'] for x in items if x['category']=='name']
    return ('哦，你叫'+names[-1]+'。') if names else '我还没有记住你的名字。你可以说，大肥鱼，记住我的名字叫 Wendy。'
