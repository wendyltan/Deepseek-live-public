"""R212 optional hidden DeepSeek Flash speech-only compression.

The original verified DSH reply remains in UI/session history. The *spoken*
copy alone may be shortened via one independent, scoped Flash DSH conversation.
No model is called on import, app boot, tests or short replies. No retry.
"""
from __future__ import annotations
import json, os, re, stat, time
from pathlib import Path
from threading import Thread, Lock, Event
from app.r260_local_speech_digest import local_spoken_digest

ROOT = Path.home() / "Library/Application Support/Deepseek-live/companion-native"
CONFIG = ROOT / "voice-preprocessor-r218.json"
IDENTITY = ROOT / "voice-preprocessor-tab.json"
DEFAULT = {"schema": 1, "enabled": False, "model": "deepseek-flash",
           "min_chars": 220, "target_chars": 180}
BUSY = Lock()


def _owned_json(path: Path):
    if path.is_symlink():
        raise ValueError("preprocessor_symlink_forbidden")
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise ValueError("preprocessor_file_permissions")
    return json.loads(path.read_text(encoding="utf-8"))


def settings():
    if not CONFIG.exists():
        return dict(DEFAULT)
    try:
        value = _owned_json(CONFIG)
        if not isinstance(value, dict) or value.get("schema") != 1:
            return {"schema":1, "enabled":False}
        if type(value.get("enabled")) is not bool:
            return {"schema":1, "enabled":False}
        return {**DEFAULT, "enabled":value["enabled"]}
    except (ValueError, OSError, json.JSONDecodeError):
        return {"schema":1, "enabled":False}


def _hidden_tab():
    """Fixed independent hidden DSH tab; never reuse visible voice history."""
    import uuid
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if ROOT.is_symlink():
        raise ValueError("preprocessor_root_symlink")
    if IDENTITY.exists():
        data = _owned_json(IDENTITY)
        value = data.get("tab_id")
        if data.get("schema") == 1 and isinstance(value,str) and re.fullmatch(r"[0-9a-f]{32}",value):
            return value
        raise ValueError("preprocessor_identity_invalid")
    value = uuid.uuid4().hex
    fd = os.open(IDENTITY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd,"w") as stream:
        json.dump({"schema":1,"tab_id":value},stream)
    return value


def _short_repetitive_coverage(original:str, proposed:str) -> bool:
    """Permit a genuinely short summary only for repeated identical facts.

    The older >=72-char floor rejects valid brief scripts from an answer
    repeating the same two sentences many times. Distinct, risky or numeric
    facts still have conservative complete-coverage requirements.
    """
    if not 20 <= len(proposed) <= 71:
        return False
    sentences=[re.sub(r"\s+","",v) for v in re.split(r"[。！？；\n]+",original)
               if len(v.strip()) >= 8]
    distinct=list(dict.fromkeys(sentences))
    if (len(sentences)<6 or not 1<=len(distinct)<=3 or
            len(distinct)*3>len(sentences)):
        return False
    old_nums=set(re.findall(r"\d+(?:[.,]\d+)*",original))
    new_nums=set(re.findall(r"\d+(?:[.,]\d+)*",proposed))
    if old_nums-new_nums:return False
    for keyword in ("禁止","警告","紧急","不得","不能","不要","必须","风险","审批","授权"):
        if keyword in original and keyword not in proposed:
            return False
    # Every *different* original statement must contribute recognisable
    # source terms. A one-topic hallucinated short answer cannot pass.
    compact=re.sub(r"\s+","",proposed)
    for sentence in distinct:
        bigrams={sentence[i:i+2] for i in range(len(sentence)-1)
                 if any("\u4e00"<=c<="\u9fff" for c in sentence[i:i+2])}
        if sum(pair in compact for pair in bigrams)<2:
            return False
    return True


def _safe_shortening(original:str, proposed:str, max_chars:int):
    if not isinstance(proposed,str) or not proposed.strip():
        return None
    text = proposed.strip().strip('"“”')
    text = re.sub(r"^\s*(?:语音版[：:]|精简回复[：:])\s*", "", text)
    if len(text) >= len(original) or len(text) > max_chars:
        return None
    if (len(text) < max(72, min(120, len(original) // 4)) and
            not _short_repetitive_coverage(original,text)):
        return None
    # Never insert new price, quantity, date or invented numeric facts.
    if set(re.findall(r"\d+(?:[.,]\d+)*",text)) - set(re.findall(r"\d+(?:[.,]\d+)*",original)):
        return None
    # Even an existing number is unsafe if attached to an invented unit:
    # a price of 3 yuan may not be rewritten as 3 kilograms.
    quantities = r"\d+(?:[.,]\d+)?\s*(?:元|块|斤|公斤|千克|克|小时|分钟|天|%)"
    normalized = lambda s: {re.sub(r"\s+", "", q) for q in re.findall(quantities, s)}
    if normalized(text) - normalized(original):
        return None
    # A model must not reverse the price of two named products. Conservative
    # fallback is preferable to speaking a plausible but incorrect amount.
    for m in re.finditer(r"([\u4e00-\u9fff]{1,5})每斤(\d+(?:\.\d+)?)元", original):
        name, price = m.groups()
        if name in text:
            occurrence = text[text.find(name)+len(name):].split('，', 1)[0].split('。', 1)[0]
            price_in_summary = re.search(r"\d+(?:\.\d+)?\s*(?:元|块)", occurrence)
            if price_in_summary and price_in_summary.group().replace('块', '元').replace(' ', '') != price+'元':
                return None
    if re.search(r"(?i)(api[-_ ]?key|sk-[a-z0-9]{12}|密码|token|口令)", text):
        return None
    return text


def spoken_only(original: str, user_text: str, *, adapter=None,
                timeout_s=12, output=print):
    if not isinstance(original,str) or not original.strip():
        return original
    opts = settings()
    if not opts.get("enabled",False) or len(original) < opts.get("min_chars",220):
        return original
    if not isinstance(user_text,str) or any(
        flag in user_text for flag in ("完整朗读","逐字朗读","详细解释","不要简化","原文照读")):
        return original
    if re.search(r"(?i)(api[-_ ]?key|sk-[a-z0-9]{12}|密码|token|口令)",original):
        return original
    # R266: do not ask a 240-char model summary to preserve seven steps.
    # This locally verified path consumes zero additional DSH/Flash calls.
    from app.r266_structured_voice import structured_spoken_digest
    step_digest = structured_spoken_digest(original)
    if step_digest is not None:
        output("R266_SPEECH_STRUCTURED_STEPS original_chars="+str(len(original))+
               " spoken_chars="+str(len(step_digest))+" source=verified_dsh")
        return step_digest
    if len(original)>4500:
        output("R260_SPEECH_LOCAL_DIGEST original_too_long_for_flash")
        return local_spoken_digest(original)
    if not BUSY.acquire(blocking=False):
        output("R212_PREPROCESS_SKIPPED busy")
        output("R260_SPEECH_LOCAL_DIGEST flash_busy")
        return local_spoken_digest(original)
    proposed = []
    done = Event()
    def worker():
        try:
            from app.dsh_p1_adapter import DshP1Adapter
            client = adapter or DshP1Adapter
            client = client() if isinstance(client,type) else client
            tab = _hidden_tab()
            # Two sessions are independent. The visible DSH session is never
            # switched or reused, and user/model results stay there unchanged.
            client.ensure(tab)
            if client.selected(tab) != "deepseek-flash":
                client.switch(tab,"deepseek-flash")
            prompt = ("你是仅供语音播报的简化器，不是对话助手。不调用工具、不接新任务。"
                      "把下方已完成的回答改成适合朗读的中文口语稿，控制在120至180字。"
                      "先判断它是解释原因、对比选择、操作步骤，还是多项列举。"
                      "解释：清楚交代结论、主要原因、关键条件和最终提醒。"
                      "对比：两边的主要区别都要保留，不可只保留一边。"
                      "步骤：必须覆盖每个必要步骤和其中的安全提醒。"
                      "列举：每项名称及一个最重要的事实都要保留，不能漏项。"
                      "按正常说话顺序组织，不逐段抄写、不复读引言、不作机械截断。"
                      "数字、价格、单位、否定词和条件不可编造或换意；"
                      "如果压缩后无法同时保留必要信息，就尽量保留完整事实。"
                      "只返回自然口语，保留合适标点，无Markdown，不输出说明。\n"
                      "已完成的原文：\n"+original[:4500])
            response = client.chat(tab,prompt,visual_observer=None)
            proposed.append(response.get("reply"))
        except Exception as exc:
            # Never expose tokens, private prompt, identity or API responses.
            # A real backend failure must be diagnosable without retrying a
            # possibly charged model turn.
            # The bridge returns machine error codes (e.g. scoped-tool
            # policy unavailability). Whitelist only machine codes, never
            # user text, arguments, model replies or opaque credentials.
            message=str(exc)
            match=re.search(r"\b(speech_[a-z0-9_]{3,56})\b",message)
            http=re.search(r"HTTP (4\d\d|5\d\d)",message)
            safe_code=match.group(1) if match else ("http_"+http.group(1) if http else "backend_unavailable")
            output("R212_PREPROCESS_FAIL "+type(exc).__name__+
                   " reason="+safe_code)
        finally:
            BUSY.release()
            done.set()
    started = time.monotonic()
    # One authorized model request per eligible user turn. Timeout does NOT
    # retry or cancel a possibly already-billed DSH request; original plays.
    try:
        Thread(target=worker,daemon=True,name="r212-speech-only").start()
    except (RuntimeError, OSError):
        BUSY.release()
        output("R212_PREPROCESS_FALLBACK thread_unavailable")
        return original
    done.wait(max(0.25,min(float(timeout_s),15.0)))
    # If the user disabled the feature during a paid request, never play its
    # late summary. The request itself is never retried or replayed.
    current_enabled=settings().get("enabled") is True
    suggestion=(_safe_shortening(original,proposed[0],opts["target_chars"])
                if done.is_set() and proposed and current_enabled else None)
    # R260: if isolated Flash is unavailable or timed out, NEVER read a
    # 1000-character Markdown table verbatim. Use an explicit local extract.
    # The full verified answer stays in the Mac UI; no new API requests.
    fallback = None
    if suggestion is None and current_enabled and len(original)>=opts["min_chars"]:
        fallback=local_spoken_digest(original)
        output("R260_SPEECH_LOCAL_DIGEST original_chars="+str(len(original))+
               " spoken_chars="+str(len(fallback))+" source=verified_dsh")
    chosen=suggestion or fallback or original
    output("R212_PREPROCESS "+("APPLIED" if suggestion else
           "LOCAL_DIGEST" if fallback else "FALLBACK")+
           " original_chars="+str(len(original))+" spoken_chars="+
           str(len(chosen))+" latency_s="+str(round(time.monotonic()-started,2)))
    return chosen
