"""Wi-Fi-only Pinky speech contract: verified task result must survive TTS shortening.

This is guidance for the bound official DSH, not evidence of tool success.
"""
from __future__ import annotations
import re

PINKY_TERMS=('pinky','手机','iphone','苹果手机','打开微信','打开淘宝','打开支付宝')
ACTION_TERMS=('帮我','替我','给我','操作','打开','查看','查一下','看看','点击','发送','发给','输入','设置','执行','连接','控制','完成','下单','添加','取消')
# R538 runs only a deliberately limited phone read-only trial. Never infer
# permission for a write by treating a broad "操作手机" request as read-only.
READ_ONLY_WORDS=('查看','查询','查一下','看看','看一下','看下','看一眼','列出','列表','手机状态','连接状态','电量','安装了哪些')
WRITE_OR_TAKEOVER_WORDS=('打开','启动','发送','发给','删除','修改','编辑','输入','点击','设置','下单','购买','付款','支付','安装','拨号','打电话','滑动','切换','重启','解锁','操作','控制','执行','取消','帮我做')
READ_ONLY_RESULT_TOOLS=frozenset({
    'mcp__pinky_dafeiyu__phone_apps',
    'mcp__pinky_dafeiyu__phone_task_list',
})
# Successful task_wait/status only proves that Pinky returned a reply;
# it can still say "running" and must not verify a completed query.
READ_ONLY_STATUS_TOOLS=frozenset({
    'mcp__pinky_dafeiyu__phone_task_status',
    'mcp__pinky_dafeiyu__phone_task_wait',
})
READ_ONLY_CONNECT_TOOLS=frozenset({
    'mcp__pinky_dafeiyu__phone_connect',
    'mcp__pinky_dafeiyu__phone_release',
})


def is_phone_task(transcript:str)->bool:
    if not isinstance(transcript,str) or len(transcript)>600:return False
    s=transcript.lower()
    if any(t in s for t in PINKY_TERMS) and any(t in s for t in ACTION_TERMS):
        return True
    # "打开我的淘宝" has an intervening 我的, so the old literal
    # "打开淘宝" phone-token check missed this natural explicit request.
    # Do not broaden generic shopping/search questions into phone commands.
    if re.search(r"(?:打开|启动)(?:(?:我(?:的)?|手机(?:上|里|里的|上的)?|"
                 r"我手机(?:上|里|里的|上的)?)){0,2}"
                 r"(?:淘宝|微信|支付宝)(?:app|应用)?",s):
        return True
    # Current screen questions are phone reads even without imperative verbs.
    personal=any(t in s for t in (
        '我手机','我的手机','我iphone','我的iphone','手机当前',
        '手机现在','手机前台','手机上现在','手机屏幕'))
    current=any(t in s for t in (
        '前台','当前打开','现在打开','正在显示','当前显示',
        '现在显示','正在运行','现在是什么','当前是什么'))
    ask=any(t in s for t in ('什么','哪个','哪一个','哪款','哪种','谁'))
    app=any(t in s for t in ('软件','应用','app','程序','屏幕','界面'))
    if personal and current and ask and app:
        return True
    # Explicitly inspect the person's current WeChat chat, not generic WeChat news.
    return ('微信' in s and
            any(t in s for t in ('帮我','替我','给我','请')) and
            any(t in s for t in ('查看','查一下','看看','看一下','看下','看一眼')) and
            any(t in s for t in ('现在','当前','正在')) and
            any(t in s for t in ('聊天','聊天窗口','联系人')))

def is_phone_search_only_request(transcript:str)->bool:
    """A user-issued no-purchase phone SEARCH, not a delegated shopping task.

    STT may omit punctuation. User prohibitions do not grant write authority;
    actual Pinky approval still governs every phone tool.
    """
    if not is_phone_task(transcript):return False
    t=transcript.lower()
    if not any(w in t for w in ('搜索','搜一下','搜一搜')):return False
    if not any(w in t for w in ('只看','只查看','只浏览','仅查看','仅浏览')):return False
    # Avoid promoting combined instructions, even if they also contain
    # a "just search" fragment.
    if any(w in t for w in (
            '然后购买','接着购买','并且购买','然后下单','帮我下单',
            '顺便下单','加进购物车','加入购物车','放进购物车',
            '然后发送','顺便发送','发送消息','转账','付款给',
            '修改地址','修改设置','删除记录','提交订单')):
        return False
    return True


def recovered_readonly_search_receipts_consistent(receipts)->bool:
    """Independent check of one failed observe followed by a settled reread.

    The authenticated Bridge additionally proves the failed call was rejected
    at schema validation and the last successful observe returned a real
    settled screen from the same app. Python cannot infer those from receipts.
    """
    if not isinstance(receipts,list) or not 6<=len(receipts)<=16:return False
    prefix='mcp__pinky_dafeiyu__phone_'
    rows=[]
    allowed={'connect','launch','tap','type','observe','release','wait_for'}
    for item in receipts:
        if (not isinstance(item,dict) or not isinstance(item.get('name'),str)
            or not item['name'].startswith(prefix)
            or item['name'][len(prefix):] not in allowed
            or item.get('receipt') not in ('success','failed')):
            return False
        rows.append((item['name'][len(prefix):],item['receipt']))
    kinds=[a for a,_ in rows]
    if (kinds[0]!='connect' or kinds[-1]!='release'
        or kinds.count('connect')!=1 or kinds.count('release')!=1
        or kinds.count('type')!=1 or 'tap' not in kinds):
        return False
    failed=[i for i,(name,status) in enumerate(rows) if status=='failed']
    if len(failed)!=1:return False
    at=failed[0]
    if (rows[at]!=('observe','failed') or kinds.index('type')>=at):
        return False
    return rows[at+1:]==[('observe','success'),('release','success')]


def completed_readonly_search_receipts_consistent(receipts)->bool:
    """A search result can be narrated after a direct same-turn observed screen.

    This is a secondary order/scope check; only the Bridge has access to the
    producer-owned observedApp, typedScreenApp and settled-screen evidence.
    """
    if not isinstance(receipts,list) or not 6<=len(receipts)<=16:return False
    prefix='mcp__pinky_dafeiyu__phone_'
    rows=[]
    allowed={'connect','launch','tap','type','observe','release','wait_for'}
    for item in receipts:
        if (not isinstance(item,dict) or not isinstance(item.get('name'),str)
            or not item['name'].startswith(prefix)
            or item['name'][len(prefix):] not in allowed
            or item.get('receipt')!='success'):
            return False
        rows.append(item['name'][len(prefix):])
    return (rows[0]=='connect' and rows[-1]=='release'
            and rows.count('connect')==1 and rows.count('release')==1
            and rows.count('type')==1 and 'tap' in rows
            and rows[rows.index('type')+1:]==['observe','release'])


def is_phone_readonly_request(transcript:str)->bool:
    if not is_phone_task(transcript):return False
    text=transcript.lower()
    # "查看已安装的应用" describes a read-only inventory. Distinguish
    # it from the WRITE command "帮我安装应用" without a broad exemption.
    safe_words=text.replace('安装了哪些','现有的').replace('已安装的','现有的')
    # Negative controls forbid actions, even if a read question names an app.
    for phrase in ('不要点击','别点击','不点击','不要切换','别切换',
                   '不要打开','别打开','不要操作','别操作','只查看','只看'):
        safe_words=safe_words.replace(phrase,'')
    if is_front_app_query(transcript):
        for phrase in ('现在打开的','当前打开的','目前打开的',
                       '已经打开的','现在显示的','当前显示的','正在使用的'):
            safe_words=safe_words.replace(phrase,'')
    return ((any(word in text for word in READ_ONLY_WORDS) or
             is_front_app_query(transcript))
            and not any(word in safe_words for word in WRITE_OR_TAKEOVER_WORDS))


def readonly_query_receipts_verified(receipts, *, enforced:bool)->bool:
    """Proof of a native read-only QUERY reply, NOT a phone business outcome.

    No synthesized DSH claims, mixed write calls, pending or failed receipts.
    Actual app/screen contents stay solely in DSH's original answer.
    """
    if enforced is not True or not isinstance(receipts,list) or not receipts:
        return False
    allowed=READ_ONLY_RESULT_TOOLS|READ_ONLY_CONNECT_TOOLS|READ_ONLY_STATUS_TOOLS
    if not all(isinstance(item,dict)
               and item.get('name') in allowed
               and item.get('receipt')=='success' for item in receipts):
        return False
    return any(item['name'] in READ_ONLY_RESULT_TOOLS for item in receipts)


def is_front_app_query(transcript:str)->bool:
    s=transcript.lower() if isinstance(transcript,str) else ''
    # "我手机上现在打开的是什么软件" is a status question, NOT
    # "帮我打开某软件". An explicit launch request stays a write task.
    if not is_phone_task(transcript):
        return False
    if re.search(r'(?:帮我|替我|给我|请)(?:先|直接)?打开(?!的|了)',s):
        return False
    return (any(w in s for w in ('前台','当前屏幕','现在屏幕',
                                 '当前打开','现在打开','目前打开',
                                 '现在显示','当前显示','正在使用',
                                 '正在运行')) and
            any(w in s for w in ('软件','应用','app','程序','界面')) and
            any(w in s for w in ('什么','哪个','哪一个','哪款','哪种')))


def is_phone_screen_query(transcript:str)->bool:
    """Read-only questions about *what the phone currently shows*.

    Natural phrases such as "微信现在和哪个联系人在聊天" are screen
    observations too. Do not mistake a successful phone_connect/release for
    the requested observation, and never promote a write intent to read-only.
    """
    if not is_phone_readonly_request(transcript):
        return False
    if is_front_app_query(transcript):
        return True
    s=transcript.lower()
    return any(word in s for word in (
        '当前屏幕','现在屏幕','屏幕上','当前页面','正在显示','现在显示',
        '前台','正在聊天','在聊天','聊天窗口','聊天内容','哪个联系人',
        '哪位联系人','微信里','微信上','微信现在','当前微信','手机界面',
        '当前界面','现在界面'))


def screen_observation_verified(transcript:str,receipts)->bool:
    """Only successful native phone_observe, no mutation or model assertions."""
    if not is_phone_screen_query(transcript) or not isinstance(receipts,list):
        return False
    safe={'mcp__pinky_dafeiyu__phone_connect',
          'mcp__pinky_dafeiyu__phone_observe',
          'mcp__pinky_dafeiyu__phone_release',
          'mcp__pinky_dafeiyu__phone_wait_for'}
    return (all(isinstance(r,dict) and r.get('name') in safe and
                r.get('receipt')=='success' for r in receipts) and
            any(r.get('name')=='mcp__pinky_dafeiyu__phone_observe'
                for r in receipts))


def front_app_observation_verified(transcript:str,receipts)->bool:
    """A verified observation scoped to a real foreground-app question."""
    return (is_front_app_query(transcript) and
            screen_observation_verified(transcript,receipts))


def tool_context(transcript:str)->str:
    if not is_phone_task(transcript):return ''
    screen=is_phone_screen_query(transcript)
    # Pinky native loop guidance. This is not an execution or approval receipt.
    base=('本次用户要求通过Pinky操作手机，来自本人板载麦克风。仅使用当前Agent的真实Pinky工具；'
          'Pinky原生规则和本人审批始终有效，不可代批、越权或重复提交。'
          '手机离线、锁屏、忙碌、拒绝时如实说失败或等待。'
          '每个工具严格使用其真实参数schema，特别是phone_observe不增加'
          '未声明的intent参数；若参数校验失败，只修正这一调用，'
          '不得重新执行之前已经成功的手机步骤。')
    if screen:
        extra=('本轮只读屏幕：phone_connect须传read_only:true并核对返回屏幕；'
               '必须在同一个手机任务中实际调用phone_observe并读取其结果，'
               '最后phone_release。不能只连接就释放；不能凭连接成功或模型猜测'
               '屏幕内容。不得启动、点击或切换应用；如前台因连接改变，'
               '或只见锁屏/授权页，明确无法确认。')
    else:
        extra=('按Pinky流程：phone_connect取当前屏幕，依次依据真实页面'
               '调用phone_launch/phone_tap/phone_type/phone_swipe，'
               '每一步核对真实响应，写入后phone_observe复查最终页面，再phone_release。'
               '不能只连接就释放，也不能用工具调用成功代替业务结果。'
               'phone_task_run使用Pinky自己的模型，不得擅自追加费用；'
               '没有本人明确委托授权不要调用。若获授权并调用，'
               '须phone_task_wait核验最终结果，running不等于完成。'
               '指定专门频道先读实际入口，不可只见到同名主应用就当进入频道；找不到不能改用相邻频道。')
    unclear_price=(('二十块钱以上二十块钱以下' in transcript or
                    '20块钱以上20块钱以下' in transcript) and
                   any(w in transcript for w in ("购物车","购买","买","商品","面包")))
    if unclear_price:
        extra+='价格上下限自相矛盾，先向用户询问预算，不猜测或下单。'
    return (base+extra+'最终依据真实工具结果，直接回答用户要的名称、数值、'
            '执行前后状态及未完成部分；不得只说去Mac端查看。'
            '未经工具回执确认，不得声称已经完成、已发送或已点击。')


def phone_tool_stage(receipts)->str:
    """Progress derived from trusted tool names and receipt statuses only.

    The native bridge does not expose Pinky's actual done/running result
    or phone screen data. Even a successful task_wait cannot confirm
    a finished phone business task. Fail closed.
    """
    if not isinstance(receipts,list) or not receipts:
        return 'none'
    names=[]
    for row in receipts:
        if (not isinstance(row,dict) or
            not isinstance(row.get('name'),str) or
            not row['name'].startswith('mcp__pinky_dafeiyu__phone_') or
            row.get('receipt') not in ('success','failed')):
            return 'mixed_or_unverifiable'
        names.append(row['name'].removeprefix('mcp__pinky_dafeiyu__phone_'))
    if any(row.get('receipt')=='failed' for row in receipts):
        return 'step_failed'
    if any(x in names for x in ('task_run','task_wait','task_status','task_list','task_steer')):
        return 'delegated_unconfirmed'
    if any(x in names for x in ('tap','launch','type','swipe','key','pinch','drag',
                                'request_approval','device','handoff')):
        return 'actions_unconfirmed'
    if any(x in names for x in ('observe','read_list','apps')):
        return 'observed_only'
    return 'connected_only'


def official_reply_confirms_unsent_draft(reply:str)->bool:
    """One more independent guard: the same official answer must describe
    non-submission. A native typed-screen alone cannot prove send semantics.
    """
    if not isinstance(reply,str) or not 1<=len(reply)<=5000:return False
    normalized=reply.replace('*','').replace('_','')
    if not any(x in normalized for x in (
            '没有发送','没发送','未发送','并未发送','不曾发送',
            '未点发送','没有点击发送','没有点发送',
            '没有发出去','未发出去','没有按回车','仍在输入框')):
        return False
    if any(x in normalized for x in (
            '已经发送','发送成功','已发出去','已经发出去','已按发送')):
        return False
    return True


def unsent_draft_receipts_consistent(receipts)->bool:
    """Independent Python check of Bridge proof shape; not itself proof."""
    if not isinstance(receipts,list) or not 3<=len(receipts)<=64:return False
    prefix='mcp__pinky_dafeiyu__phone_'
    items=[]
    for x in receipts:
        if (not isinstance(x,dict) or
            not isinstance(x.get('name'),str) or
            not x['name'].startswith(prefix) or x.get('receipt')!='success'):
            return False
        items.append(x['name'][len(prefix):])
    if items[0]!='connect' or items[-1]!='release':return False
    allowed={'connect','apps','observe','launch','tap','type',
             'swipe','key','wait_for','release'}
    if any(x not in allowed for x in items):return False
    at=len(items)-1-items[::-1].index('type') if 'type' in items else -1
    return at>0 and all(x=='observe' for x in items[at+1:-1])


def direct_action_receipts_consistent(receipts)->bool:
    """Independent tool-order check of a native *direct* phone turn.

    This cannot prove a final screen or a business result by itself.
    Only the Bridge's same-call-ID settled-screen proof can attest those.
    """
    if not isinstance(receipts,list) or not 3<=len(receipts)<=64:
        return False
    prefix='mcp__pinky_dafeiyu__phone_'
    # R686: native phone_handoff can restore a dropped Wi-Fi phone
    # connection before the actual action; it never counts as completion.
    allowed={'connect','handoff','apps','observe','launch','tap','type',
             'swipe','key','wait_for','release'}
    modifiers={'launch','tap','type','swipe','key'}
    names=[]
    for r in receipts:
        if (not isinstance(r,dict) or not isinstance(r.get('name'),str)
            or not r['name'].startswith(prefix) or
            r.get('receipt')!='success'):
            return False
        names.append(r['name'][len(prefix):])
    if (any(x not in allowed for x in names) or names[0]!='connect'
        or names[-1]!='release' or names.count('connect')!=1
        or names.count('release')!=1):
        return False
    last=max((i for i,k in enumerate(names) if k in modifiers),default=-1)
    return last>=1 and last<len(names)-1 and all(
        x in {'observe','wait_for'} for x in names[last+1:-1])


def preserve_task_report(reply:str, transcript:str)->bool:
    """Avoid lossy 320-char Wi-Fi digest for phone task receipts."""
    return is_phone_task(transcript) and isinstance(reply,str) and bool(reply.strip())


def simple_app_launch_requested(transcript:str,app_name:str)->bool:
    """One explicit app-open request, without follow-on actions."""
    if not isinstance(transcript,str) or not isinstance(app_name,str) or not (
        1<=len(transcript)<=160 and 1<=len(app_name)<=48):return False
    name=app_name.casefold()
    text=re.sub(r"[，。！？!?、,.：:\\s]+","",transcript.casefold())
    if any(x in text for x in ("接着","然后","并且","同时","购买","下单",
        "付款","支付","删除","发消息","发送","搜索","加入购物车","点击",
        "填写","查看订单","浏览商品","登录","退出","切换")):
        return False
    if name not in text or len(text)>100:return False
    pat=(r"^(?:请|麻烦|可以|能不能|你)?(?:帮我|替我|给我)?"
         r"(?:在手机上|在我的手机上|用pinky)?(?:打开|启动)"
         r"(?:我手机上的|手机上的|我的|一下)?"
         +re.escape(name)+
         r"(?:这个软件|这个应用|应用|app|软件)?(?:一下|吧|就行|可以吗)?$")
    return re.fullmatch(pat,text) is not None


def is_unsent_draft_request(transcript:str)->bool:
    """Explicit instruction to type text while NOT sending it.
    Negation applies to the SEND operation, not to typing itself.
    """
    if not isinstance(transcript,str) or len(transcript)>600:return False
    text=transcript.lower()
    if not is_phone_task(text):return False
    typing=any(w in text for w in ('输入','打字','写入','写上','填入','填写','编辑','草稿'))
    # R620: actual R618 microphone ASR says "不要点击发送", which differs
    # from both "不点击发送" and "不要点发送". Enumerate precise negated
    # button instructions; do NOT interpret a generic send mention as no-send.
    unsent=any(w in text for w in ('不发送','别发送','不要发送',
                   '不点击发送','不要点击发送','别点击发送',
                   '不需要点击发送','无需点击发送','不用点击发送',
                   '不点发送','不要点发送','别点发送','先不发',
                   '先别发','暂不发送','不要按发送','不要按下发送',
                   '不要按回车','别按回车','不按回车','不发出去',
                   '只输入不发','输入但不发','输入后不发'))
    return typing and unsent and not any(w in text for w in (
           '然后发送','接着发送','再发送','自动发送','发送出去','发给他',
           '发给她','付款','支付','下单','删除'))


def verified_phone_search_item(reply:str)->str|None:
    """Extract one explicitly labelled item from an official agent result.

    A bounded source-backed string, never a guessed item from generic prose.
    Its authorization is handled by the authenticated phone-proof flags.
    """
    if not isinstance(reply,str) or not 5<=len(reply)<=5000:return None
    headers=(
        r'(?:搜索结果|结果列表)(?:第[一二三四五六七八九十\d]+(?:个|条|件)?)?'
        r'(?:商品|结果)?(?:是|为|[:：])[:：]?',
        r'(?:先给你|给你|找到了|找到|搜到|其中)?(?:一个|一款|一件|首个|第一件|首件)?商品(?:名称|名)?[:：]'
    )
    for header in headers:
        m=re.search(header,reply)
        if not m:continue
        # "没有找到商品名称" is a negative report, not a listing.
        preamble=reply[max(0,m.start()-16):m.start()].split('\n')[-1]
        if any(w in preamble for w in ('没有','未找到','找不到','暂无','无法','未能')):
            continue
        tail=reply[m.end():].lstrip('\n\r\t 　*：:')
        if not tail:continue
        line=tail.splitlines()[0].strip()
        line=re.sub(r'^[-•]\s*', '',line)
        line=re.sub(r'\*{1,2}|__','',line)
        # Shopping listing attributes are not part of the product NAME.
        line=re.split(
            r'，\s*(?:[￥¥]\s*)?\d+(?:\.\d+)?\s*元'
            r'|，\s*\d+(?:\.\d+)?\s*元'
            r'|，\s*\d+\s*(?:万|人)\+?人?付款'
            r'|[。；（(]',line,maxsplit=1)[0].strip(' ，。；：:*_')
        if (5<=len(line)<=105 and not
            any(x in line for x in ('http://','https://','\u0000',
                                    '未找到','找不到','没有商品','无法确认',
                                    '请在电脑','去电脑','请查看'))):
            return line
    # R684: An actual search listing is often a Markdown-bold product row
    # preceded by free-form prose, not a fixed "商品名称：" label.
    # Only take a priced listing inside an official result that says it
    # searched/viewed results. A bare bold brand or explanatory phrase
    # cannot become a product name.
    if any(w in reply for w in ('搜索结果','结果页','搜过','搜到','商品名','商品名称')):
        for found in re.finditer(r'\*\*([^\n*]{5,180})\*\*',reply):
            raw=found.group(1)
            if not re.search(r'(?:[￥¥]\s*)?\d+(?:\.\d+)?\s*元',raw):
                continue
            item=re.split(r'，\s*(?:[￥¥]\s*)?\d+(?:\.\d+)?\s*元'
                          r'|[。；（(]',raw,maxsplit=1)[0].strip(' ，。；：:*_')
            if (5<=len(item)<=105 and
                not any(w in item for w in ('未找到','无法','没有商品','查看电脑','比如','例如'))
                and 'http://' not in item and 'https://' not in item):
                return item
    return None


def verified_phone_speech(reply:str, *,pinky_tool_verified:bool,
                          action:str|None=None,readonly_query_verified:bool=False,
                          front_app_observed:bool=False,
                          screen_observed:bool=False,task_stage:str|None=None,
                          delegation_state:str|None=None,
                          confirmed_launch_app:str|None=None,
                          confirmed_unsent_draft:bool=False,
                          direct_actions_finalized:bool=False,
                          readonly_search_recovered:bool=False,
                          readonly_search_completed:bool=False,
                          transcript:str|None=None)->str:
    """Do not voice an unsupported model claim as a verified iPhone action."""
    # R685: source of the spoken result is the *same official Pinky answer*.
    # No product-name regex, no shopping/app-specific success templates.
    # Hard failures are handled below; safe producer proof is checked after
    # them, before any generic completion fallback.
    if action=='phone_connect_failed':
        return ('本鱼没能连接手机，这次还没有操作成功。'
                '检查一下Pinky连接和手机解锁，再决定是否重试。')
    if action=='phone_tool_failed':
        return ('本鱼这次手机任务没有完成，结果还没确认。'
                '先看一下手机，别重复提交。')
    if action=='phone_recovered_unverified':
        return ('本鱼中途一次点击失败，后来重新点击并继续执行了。'
                '但最后结果还没有再次核对。你看一下手机当前页面，先别重复操作。')
    if action=='phone_partial_failure':
        return ('本鱼这次手机操作有步骤失败，部分操作可能已经执行。'
                '最终结果需要核对，请先别重复操作。')
    if action=='approval_rejected':
        return '本鱼知道啦，这次手机授权已被拒绝。前面已经做过的部分还需要你看一眼手机确认。'
    if action=='approval_cancelled':
        return '本鱼知道啦，这次手机授权已取消。前面已经做过的部分还需要你看一眼手机确认。'
    # A typed unsent draft needs independent evidence that no send happened.
    if is_unsent_draft_request(transcript):
        if (pinky_tool_verified is True and confirmed_unsent_draft is True and
            official_reply_confirms_unsent_draft(reply) and not action):
            return reply.strip()
        return ('本鱼尝试操作手机，但还没有确认草稿是否保持未发送。'
                '请在手机上核对实际状态。')
    if action in ('foreground_not_observed','screen_not_observed'):
        label=('前台是什么软件' if action=='foreground_not_observed'
               else '手机屏幕上的内容')
        return (('本鱼连接了手机，但没有完成屏幕查看。'
                 if pinky_tool_verified else '本鱼没有完成手机屏幕查看。')
                + '所以还不能确认'+label+'，这次没有替你点击或打开应用。')
    # R685 one generic, provenance-gated phone result for all apps/actions.
    # The final DSH text follows actual same-turn producer-owned tool
    # results. It is the speech source. Nothing is inferred from tool names.
    # The existing voice normalization strips Markdown for TTS.
    native_final=(direct_actions_finalized is True and
                  task_stage=='actions_unconfirmed' and
                  delegation_state is None)
    native_read=(readonly_query_verified is True or
                 screen_observed is True or front_app_observed is True)
    native_search=(is_phone_search_only_request(transcript) and
                   ((readonly_search_recovered is True and
                     task_stage=='read_only_search_recovered') or
                    (readonly_search_completed is True and
                     task_stage=='read_only_search_verified')))
    simple_launch=simple_app_launch_requested(transcript,confirmed_launch_app)
    if (simple_launch and pinky_tool_verified is True and not action):
        # Producer-confirmed actual foreground app wins over an empty or
        # contradictory generic assistant sentence for a *single* launch.
        return '本鱼已经打开'+confirmed_launch_app+'了。'
    if (pinky_tool_verified is True and not action and
        isinstance(reply,str) and 2<=len(reply.strip())<=1800 and
        (native_final or native_read or native_search)):
        # Read-only observations cannot prove a write, even if the model
        # hallucinates one. Real direct-action finalizations can report writes
        # only because the producer verified an actual settled screen.
        unsupported_write_claim=any(w in reply for w in (
            '已发送','已经发送','发送成功','发送了','已经发给',
            '已经删除','已删除','删除了','删除你的','替你删除',
            '已经付款','已付款','付款成功','已经下单','已下单',
            '已经加购','加购成功','加进购物车','已加入购物车',
            '已经加入购物车'))
        if native_final or not unsupported_write_claim:
            return reply.strip()
    if action in ('foreground_not_observed','screen_not_observed'):
        label=('前台是什么软件' if action=='foreground_not_observed'
               else '手机屏幕上的内容')
        return (('本鱼连接了手机，但没有完成屏幕查看。'
                 if pinky_tool_verified else '本鱼没有完成手机屏幕查看。')
                + '所以还不能确认'+label+'，这次没有替你点击或打开应用。')
    # Real observation (not an app-open attempt) succeeded; the spoken
    # interpretation is still from the official Agent and is not ground truth
    # without human visual acceptance. Do not speak suspicious action claims.
    if front_app_observed is True or screen_observed is True:
        text=reply.strip() if isinstance(reply,str) else ''
        # An observation-only proof cannot license a model's unsupported
        # claim of deletion, payment, send, or any other side effect.
        if any(w in text for w in (
            '已发送','已经发送','发送成功','发送了','已经发给',
            '已经删除','已删除','删除了','删除你的','替你删除',
            '已经付款','已付款','付款成功','已经下单','已下单',
            '已经加购','加购成功','加进购物车','已加入购物车',
            '已经加入购物车')):
            return '本鱼读取了手机页面，但无法确认回复中提到的修改操作。'
        action_terms=('已发送','已删除','已修改','已付款','已下单','已经打开',
                      '完成操作','我点击','我输入','我启动')
        # The real agent may add explanation after the actual answer.
        # Speak a short, source-backed foreground sentence instead of
        # withholding the app name because the entire response exceeds 110.
        first=re.split(r'[。\n]',text,maxsplit=1)[0].strip()
        foreground=('前台','当前','现在','桌面','程序','应用','聊天','窗口','联系人','屏幕')
        if (2<=len(first)<=110 and
                any(w in first for w in foreground) and
                not any(x in first for x in action_terms)):
            return '本鱼查看了手机屏幕。'+first+'。'
        if 2<=len(text)<=110 and not any(x in text for x in action_terms):
            return '本鱼查看了手机屏幕。'+text
        return '本鱼完成了手机屏幕查看，具体内容请在电脑对话里核对。'
    # Native verified read-only query returned a result: allow a useful,
    # strictly bounded acknowledgment. Never speak unverified model details.
    if readonly_query_verified is True:
        return ('本鱼已经收到手机查询的回应了，具体内容可以在电脑对话里查看。'
                '这次没有替你修改手机里的东西。')
    # Native tool names prove steps, never a phone business result.
    # Bridge's same-ID native Pinky state, not unverified assistant prose.
    if delegation_state=='done':
        return ('本鱼收到了手机任务已经结束的正式回报。'
                '具体操作结果请在手机上确认一下。')
    if delegation_state=='waiting_for_person':
        return ('本鱼这次手机任务正在等你处理授权或手机操作，'
                '现在还没有完成。')
    if delegation_state=='running':
        return ('本鱼这次手机任务还在进行中，没有收到最终结果。'
                '先别重复提交。')
    if delegation_state in ('failed','stopped','cancelled'):
        return ('本鱼收到手机任务失败、停止或取消的结果，'
                '没有完成，这次不会自己重试。')
    if delegation_state in ('partial','uncertain'):
        return ('本鱼收到手机任务结果尚不确定的回报，'
                '可能已经做过部分步骤，请先检查手机，别重复操作。')
    # R626: DSH terminal, same-task all-successful direct receipts and a
    # producer-correlated settled phone screen after the last action.
    # This proves completed *execution* and screen read, not an arbitrary
    # app's business result (send/payment/order/cart state). No per-app rules.
    if (direct_actions_finalized is True and pinky_tool_verified is True and
        task_stage=='actions_unconfirmed' and delegation_state is None):
        # R631: one-language, shorter oral ending. The full signed DSH
        # answer remains unchanged and readable in the desktop application.
        # R635: a single coherent sentence, avoiding the real R631 TTS
        # artifact that placed an audible pause between 已 and 经. The
        # underlying native tool proof and exact Mac record are unchanged.
        return ('本鱼完成了这次手机操作，也核对了最后的页面。'
                '具体结果可以在电脑端的对话里查看。')
    if task_stage=='connected_only':
        return ('本鱼这次只连接过手机，还没有执行你要求的操作。'
                '手机里的结果没有确认，也没有替你重复操作。')
    if task_stage=='delegated_unconfirmed':
        return ('本鱼已发起手机任务，但还没确认它是否结束。'
                '请先别重复提交，查看手机上实际结果。')
    if task_stage=='step_failed':
        return ('本鱼操作手机时有一步失败了，不能确认最终结果。'
                '先查看手机，不要重复执行。')
    if task_stage in ('actions_unconfirmed','observed_only',
                      'mixed_or_unverifiable'):
        return ('本鱼已经进行过部分手机步骤，但还没有确认'
                '你要的最终结果。先别重复操作。')
    # Tool transport success does not prove an asynchronous phone task finished.
    if pinky_tool_verified:
        return ('本鱼调用过手机，但还没确认任务是不是完成了。'
                '你看一眼手机结果，先别重复操作。')
    return ('本鱼还没确认这次手机操作是不是成功了。'
            '你看一眼手机结果，先别重复操作。')
