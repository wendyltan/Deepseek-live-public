"""Local, owner-controlled, source-attributed assistant memory.

Trusted ESP32 STT is the only automatic discovery source. Explicit owner
setting mode=auto is required before creating facts. No auto-import of DSH
replies, tool outputs, arbitrary transcripts, or sensitive categories.
Each record can be removed by its exact ID; retrieval is read-only.
"""
from __future__ import annotations
import json,os,re,tempfile,time,uuid
from pathlib import Path

BASE=Path.home()/"Library/Application Support/Deepseek-live/companion-native"
CONFIG=BASE/"memory-candidate-mode.json"
AUTOSTORE=BASE/"memory-auto-v1.json"
_ALLOWED={"schema":1,"mode":"auto"}
MAX_FACTS=64
BANNED=("密码","验证码","银行卡","身份证","住址","住在","病","诊断","病史","性","宗教","政治","手机号","账号","密钥","秘密","借贷")
_PATTERNS=(
 ("name",re.compile(r"^(?:大肥鱼[，,]?)?(?:我(?:的名字)?叫|请叫我|以后叫我|你可以叫我|请记住我叫|我的昵称是)([\u4e00-\u9fffA-Za-z0-9]{2,16})[。！!]*$")),
 ("likes",re.compile(r"^(?:大肥鱼[，,]?)?(?:我(?:平时|特别|非常|很|比较)?喜欢|请记住我喜欢|记住我喜欢)([\u4e00-\u9fffA-Za-z0-9、 ]{2,35})[。！!]*$")),
 ("dislikes",re.compile(r"^(?:大肥鱼[，,]?)?(?:我(?:很|特别)?不喜欢|请记住我不喜欢)([\u4e00-\u9fffA-Za-z0-9、 ]{2,35})[。！!]*$")),
)
_CATEGORIES={"name":"称呼","likes":"爱好","dislikes":"不喜欢"}
def extract(text):
    if not isinstance(text,str) or len(text)>90:return None
    for cat,pattern in _PATTERNS:
        match=pattern.fullmatch(text.strip())
        if match:
            value=match[1].strip()
            if (not value or any(w in value for w in BANNED) or
                any(w in value for w in ("帮我","替我","执行","打开","删除","关闭","转账","付款","运行","立即"))):return None
            return {"category":cat,"value":value,"text":_CATEGORIES[cat]+"："+value}
    return None

def _safe(p,size=16384):
    try:
        st=p.lstat()
        return p.is_file() and not p.is_symlink() and st.st_size<=size and st.st_mode&0o077==0
    except OSError:return False
def read_store(path=AUTOSTORE):
    if not path.exists():return []
    if not _safe(path,32768):raise ValueError("memory_store_permissions")
    obj=json.loads(path.read_text(encoding="utf8"))
    if obj.get("schema")!=1 or not isinstance(obj.get("items"),list) or len(obj["items"])>MAX_FACTS:
        raise ValueError("memory_store_invalid")
    seen=set()
    for item in obj["items"]:
        if not isinstance(item,dict) or set(item)!={"id","category","value","text","created_at","source"}:
            raise ValueError("memory_item_invalid")
        if not isinstance(item["id"],str) or not re.fullmatch(r"[a-f0-9]{32}",item["id"]) or item["id"] in seen:
            raise ValueError("memory_id_invalid")
        if item["category"] not in _CATEGORIES or len(item["value"])>35 or len(item["text"])>55 or item["source"]!="verified_esp32_user_voice":
            raise ValueError("memory_item_scope")
        seen.add(item["id"])
    return obj["items"]

def _write(path,items):
    parent=path.parent
    parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if parent.is_symlink() or parent.stat().st_mode&0o077 or path.is_symlink():
        raise ValueError("memory_directory_not_private")
    content=json.dumps({"schema":1,"items":items},ensure_ascii=False,separators=(",",":")).encode()
    if len(content)>32768:raise ValueError("memory_too_large")
    candidate=None
    try:
        with tempfile.NamedTemporaryFile(dir=parent,prefix=".auto-memory-",delete=False) as f:
            candidate=Path(f.name);os.fchmod(f.fileno(),0o600);f.write(content);f.flush();os.fsync(f.fileno())
        os.replace(candidate,path)
    finally:
        if candidate:candidate.unlink(missing_ok=True)

def auto_remember(transcript,*,verified_stt=False,config=CONFIG,store=AUTOSTORE,clock=time.time):
    # Mode must be set through Mac's owner-facing preferences screen.
    if not verified_stt or not _safe(config,512):return False
    try:
        if json.loads(config.read_text())!=_ALLOWED:return False
    except (OSError,ValueError,TypeError,UnicodeError):return False
    fact=extract(transcript)
    if fact is None:return False
    if store==AUTOSTORE and config==CONFIG:
        from app.r308_unified_memory import enabled,remember_verified
        if enabled():
            return remember_verified(fact) == "saved"
    try:items=read_store(store)
    except (OSError,ValueError,TypeError):return False
    if any(i["category"]==fact["category"] and i["value"]==fact["value"] for i in items):
        return False
    if fact["category"]=="name":
        items=[x for x in items if x["category"]!="name"]
    if len(items)>=MAX_FACTS:raise ValueError("memory_auto_capacity_review_required")
    try:
        _write(store,[*items,{"id":uuid.uuid4().hex,**fact,
                    "created_at":int(clock()),"source":"verified_esp32_user_voice"}])
        return True
    except (OSError,ValueError,TypeError):return False

def remove_record(id,*,store=AUTOSTORE):
    if not isinstance(id,str) or not re.fullmatch(r"[a-f0-9]{32}",id):return False
    items=read_store(store)
    if not any(x["id"]==id for x in items):return False
    _write(store,[x for x in items if x["id"]!=id])
    return True

def relevant_facts(query,*,store=AUTOSTORE,max_count=3):
    if not isinstance(query,str) or len(query)>600 or max_count>4:return []
    items=read_store(store)
    phrase=query.casefold()
    scored=[]
    for item in items:
        v=item["value"].casefold()
        score=3 if v in phrase else 0
        if item["category"]=="name" and any(w in phrase for w in ("叫","名字","称呼","你认识我","我是谁","介绍我","关于我","喜好","喜欢")):score+=3
        if item["category"]=="likes" and any(w in phrase for w in ("喜欢","爱好","偏好","推荐","兴趣","咖啡","我是谁","关于我")):score+=3
        if item["category"]=="dislikes" and any(w in phrase for w in ("不喜欢","讨厌","偏好","推荐")):score+=3
        if score:scored.append((score,item["created_at"],item))
    scored.sort(key=lambda x:(-x[0],-x[1]))
    return [x[2] for x in scored[:max_count]]
