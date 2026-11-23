#!/usr/bin/env python3
"""R677 safe native DSH context rotation. Display/history != model context.

Status and archive browsing are read-only. 'new' is only a direct human UI
action, guarded by authenticated prewake-only Wi-Fi + idle DSH; it archives
the complete private visible history before changing only the voice tab id.
R319 alone owns restart. No compaction LLM call or forced device transition.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse,hashlib,json,os,re,signal,stat,subprocess,tempfile,time,urllib.request,uuid
from pathlib import Path
from types import SimpleNamespace
from scripts.r659_plugin_manager import DEFAULT_HOME
from scripts.r268_transport_supervisor import snapshot,decide
ROOT=Path.home()/"Library/Application Support/Deepseek-live/companion-native"
GW=Path.home()/"Library/Application Support/Deepseek-live/lan-pairing/lan-gateway-status.json"
IDENTITY=ROOT/"voice-tab-identity.json"
HISTORY=ROOT/"conversation-history-v3.json"
ARCHIVES=ROOT/"session-archives"
SID=re.compile(r"^[a-f0-9-]{36}$")
HASH=re.compile(r"^[a-f0-9]{24}$")
CONFIRM="NEW_ISOLATED_DSH_CONTEXT_KEEP_ARCHIVE"
LIMIT=120

def require(ok,code):
    if not ok:raise RuntimeError("R677_"+code)

def put_atomic(path:Path,content:bytes):
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix=".r677-stage-",delete=False) as fp:
        tmp=Path(fp.name)
        os.fchmod(fp.fileno(),0o600)
        fp.write(content)
        fp.flush()
        os.fsync(fp.fileno())
    try:
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)

def port(number:int)->int|None:
    p=subprocess.run(["/usr/sbin/lsof","-nP","-t",f"-iTCP:{number}","-sTCP:LISTEN"],
                     capture_output=True,text=True,timeout=7)
    if p.returncode==1 and not p.stdout.strip():return None
    values=p.stdout.strip().splitlines()
    require(p.returncode==0 and len(values)==1 and values[0].isdigit(),"SOCKET_OWNER_NOT_UNIQUE")
    return int(values[0])

def launchpid(label:str)->int:
    p=subprocess.run(["/bin/launchctl","print",label],capture_output=True,text=True,timeout=7)
    require(p.returncode==0,"LAUNCHAGENT_UNAVAILABLE")
    m=re.search(r"(?m)^\s*pid = (\d+)\s*$",p.stdout)
    require(bool(m),"LAUNCHAGENT_PID_MISSING")
    return int(m.group(1))

def official():
    from scripts.r18_h10_native_dialogue import read_private_token,stable_local_conversation_tab_id,official_bridge_token_path
    from app.dsh_p1_adapter import DshP1Adapter
    token_path=None
    for candidate in (DEFAULT_HOME/"secrets/deepseek-live-bridge.token",
                      DEFAULT_HOME/"secrets/bridge.token"):
        if candidate.is_file():
            token_path=candidate;break
    if token_path is None:token_path=official_bridge_token_path()
    return DshP1Adapter("http://127.0.0.1:3080",read_private_token(token_path)),stable_local_conversation_tab_id()

def health():
    try:
        op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open("http://127.0.0.1:3080/dsh-live-bridge/health",timeout=4) as resp:
            return json.load(resp) if resp.status==200 else {}
    except (OSError,ValueError,TypeError):
        return {}

def peers():
    return {str(k):port(k) for k in (8877,8906,8907)}

def stamp():
    m=json.loads(GW.read_text())
    require(GW.is_file() and not GW.is_symlink() and (GW.stat().st_mode&0o077)==0,"GATEWAY_STATUS_UNTRUSTED")
    require(0<=time.time()-m["updated_at_unix"]<6 and m.get("pid")==port(8877),"GATEWAY_NOT_LIVE")
    require(m.get("pending_dsh_jobs")==0 and m.get("active_devices")==1 and
            m.get("device_phase")=="prewake_streaming" and m.get("prewake_enabled") is True,
            "DEVICE_NOT_QUIESCENT_PREWAKE")
    owner=launchpid(f"gui/{os.getuid()}/local.deepseeklive.r319.transport-supervisor")
    process=subprocess.run(["/bin/ps","-p",str(m["pid"]),"-o","ppid=,command="],
                           capture_output=True,text=True,timeout=5)
    parts=process.stdout.strip().split(None,1)
    require(process.returncode==0 and len(parts)==2 and parts[0]==str(owner) and
            "r268_wifi_mac_gateway.py" in parts[1],"WSS_NOT_SUPERVISOR_CHILD")
    s=snapshot(SimpleNamespace(pid=m["pid"],poll=lambda:None))
    require(not s.usb_present and not s.usb_job_loaded and
            s.lan_alive and s.lan_clients==1 and s.pending_dsh==0 and
            not s.voice_busy and s.paired and decide(s)=="lan_idle",
            "WIFI_NOT_EXCLUSIVE_OWNER")
    return m["pid"]

def selected_model_verified(value):
    return (isinstance(value,dict) and
        value.get("provider")=="deepseek-official" and
        value.get("model")=="deepseek-flash" and
        set(value)<={"provider","model","reasoningEffort"} and
        value.get("reasoningEffort","high")=="high")

def idle():
    gw=stamp()
    a,tab=official()
    session=a.inspect(tab)
    dsh_pid=port(3080)
    require(session.get("ok") is True and session.get("busy") is False and
            session.get("pending_resume") is False and
            selected_model_verified(session.get("selected")) and
            health().get("ok") is True and dsh_pid is not None,
            "OFFICIAL_DSH_NOT_IDLE")
    n=peers()
    require(n["8877"]==gw and (n["8906"] or n["8907"]),"PEER_SERVICES_CHANGED")
    own=launchpid(f"gui/{os.getuid()}/local.deepseeklive.r319.transport-supervisor")
    return session["session_id"],tab,dsh_pid,n,own

def private_file(p,limit):
    s=p.lstat()
    require(stat.S_ISREG(s.st_mode) and not p.is_symlink() and
            s.st_uid==os.getuid() and (s.st_mode&0o077)==0 and
            20<=s.st_size<=limit,"UNTRUSTED_PRIVATE_FILE")
    return p.read_bytes()

def session_record():
    data=json.loads(private_file(IDENTITY,512))
    tab=data.get("tab_id")
    require(data.get("schema")==1 and isinstance(tab,str) and
            re.fullmatch(r"[a-f0-9]{32}",tab),"TAB_INVALID")
    return tab

def history():
    j=json.loads(private_file(HISTORY,220000))
    turns=j.get("turns",[])
    require(j.get("schema")==3 and j.get("session_verified") is True and
            SID.fullmatch(j.get("session_id","")) and isinstance(turns,list) and
            len(turns)<=LIMIT and
            all(isinstance(t,dict) and isinstance(t.get("user"),str)
                and isinstance(t.get("assistant"),str) for t in turns),
            "HISTORY_INVALID")
    return j

def archive_key(sid):
    return hashlib.sha256(sid.encode("ascii")).hexdigest()[:24]

def safe_archive_dir():
    if not ARCHIVES.exists():return None
    s=ARCHIVES.lstat()
    require(stat.S_ISDIR(s.st_mode) and not ARCHIVES.is_symlink()
            and s.st_uid==os.getuid() and not (s.st_mode&0o077),
            "ARCHIVES_NOT_PRIVATE")
    return ARCHIVES

def archive_file(key):
    require(bool(HASH.fullmatch(key)),"BAD_ARCHIVE_ID")
    folder=safe_archive_dir()
    require(folder is not None,"ARCHIVE_NOT_FOUND")
    return folder/(key+".json")

def native_context_pressure(sid,*,directory=None):
    """Read only the same verified native Session's DSH context projection.

    pressureTokens / contextWindow is NOT billable aggregate token usage.
    Reject stale/corrupt/foreign/private-path snapshots; no model calls.
    """
    base=(directory if directory is not None else
          DEFAULT_HOME/"storages/session_projcache/sessions")
    path=base/(sid+".json")
    try:
        j=json.loads(private_file(path,350000))
        record=j["record"]
        rows=record["rows"]
        identity=record["identity"]
        model=rows["modelSelection"]["val"]["lastUsed"]
        pressure=rows["contextPressure"]["val"]
        tokens=pressure["pressureTokens"]
        window=pressure["contextWindow"]
        if (j.get("version")!=7 or not isinstance(identity.get("createdAt"),int)
            or model.get("provider")!="deepseek-official" or
            model.get("model")!="deepseek-flash" or
            type(tokens) is not int or type(window) is not int or
            not (0<=tokens<=window<=4_000_000)):
            return None
        return {"context_pressure_tokens":tokens,
                "context_window_tokens":window,
                "context_usage_percent":round(100*tokens/window,1),
                "context_measurement":"dsh_native_context_pressure",
                "context_recorded_at_unix":int(path.stat().st_mtime)}
    except (OSError,ValueError,TypeError,KeyError,ZeroDivisionError,RuntimeError,
            AttributeError):return None

def context_status():
    tab=session_record()
    a,real=official()
    require(real==tab,"NATIVE_TAB_ID_MISMATCH")
    response=a.inspect(real)
    require(response.get("ok") is True and response.get("busy") is False
            and response.get("pending_resume") is False,"DSH_SESSION_UNAVAILABLE")
    j=history()
    if j["session_id"]==response["session_id"]:
        count=len(j["turns"])
    else:
        # New zero-turn native Sessions need not have written their first
        # history file yet. Count zero only when the old file is verifiably
        # in an owner-private archive AND the current trusted status uses
        # the new DSH Session. Never mislabel the old turns as new context.
        old_archive=archive_file(archive_key(j["session_id"]))
        require(private_file(old_archive,220000)==HISTORY.read_bytes(),
                "NEW_CONTEXT_OLD_HISTORY_NOT_ARCHIVED")
        status=json.loads(private_file(ROOT/"status.json",64000))
        require(status.get("session_id")==response["session_id"] and
                status.get("session_verified") is True,
                "NEW_CONTEXT_STATUS_NOT_VERIFIED")
        count=0
    archived=archives_summary()
    key=archive_key(response["session_id"])
    is_new=bool(archived) and all(x["id"]!=key for x in archived)
    # The archived current Session after a failed R677 rotation is a
    # BACKUP, not an older conversation. Do not show a false "new" badge.
    recent_failed=False
    if archived and not is_new:
        folder=safe_archive_dir()
        if folder is not None:
            transactions=sorted(folder.glob("rotation-"+key+"*/receipt.json"))
            for file in transactions[-4:]:
                try:
                    receipt=json.loads(private_file(file,4096))
                    if receipt.get("stage")=="r677_old_tab_restored_rebind_pending":
                        recent_failed=True
                except (OSError,ValueError,RuntimeError):pass
    pressure=native_context_pressure(response["session_id"])
    percent=pressure["context_usage_percent"] if pressure else None
    return {"ok":True,"current_session":key,
            "current_session_kind":"new" if is_new else "original",
            "current_session_label":("新会话 "+str(len(archived)+1)+" · 当前"
                                     if is_new else "原会话 · 当前"),
            "previous_new_session_failed":recent_failed,
            "visible_turns":count,"history_capacity_turns":LIMIT,
            "context_usage_tokens":pressure["context_pressure_tokens"] if pressure else None,
            "context_window_tokens":pressure["context_window_tokens"] if pressure else None,
            "context_usage_percent":percent,
            "context_measurement":pressure["context_measurement"] if pressure else None,
            "context_recorded_at_unix":pressure["context_recorded_at_unix"] if pressure else None,
            "fresh_context_recommended":percent is not None and percent>=75,
            "new_session_supported":True,
            "past_archives":len(archived)}

def archives_summary():
    folder=safe_archive_dir()
    if folder is None:return []
    rows=[]
    for f in sorted(folder.glob("*.json"),key=lambda a:a.stat().st_mtime,reverse=True)[:25]:
        if not HASH.fullmatch(f.stem):continue
        try:
            j=json.loads(private_file(f,220000))
            if (j.get("schema")!=3 or not SID.fullmatch(j.get("session_id","")) or
                archive_key(j["session_id"])!=f.stem or
                not isinstance(j.get("turns"),list) or len(j["turns"])>LIMIT):
                continue
            rows.append({"id":f.stem,"turns":len(j["turns"]),
                         "archived_at_unix":f.stat().st_mtime})
        except (OSError,ValueError,TypeError,RuntimeError):continue
    return rows

def read_archive(key):
    f=archive_file(key)
    j=json.loads(private_file(f,220000))
    require(j.get("schema")==3 and SID.fullmatch(j.get("session_id","")) and
            archive_key(j["session_id"])==key,
            "ARCHIVE_SESSION_INVALID")
    result=[]
    for row in j.get("turns",[])[-LIMIT:]:
        require(isinstance(row,dict) and
                isinstance(row.get("user"),str) and
                isinstance(row.get("assistant"),str),"ARCHIVE_TURN_INVALID")
        result.append({"user":row["user"][:400],
                       "assistant":row["assistant"][:900],
                       "origin":row.get("origin","model")})
    return {"ok":True,"id":key,"turns":result}

def transaction(stage,folder,**data):
    put_atomic(folder/"receipt.json",(json.dumps({
        "schema":1,"stage":stage,"unix_time":time.time(),**data
    },ensure_ascii=False,indent=2)+"\n").encode())

def new_session():
    before=idle()
    tab=session_record()
    old_j=history()
    require(before[1]==tab and old_j["session_id"]==before[0],
            "BEFORE_SESSION_MISMATCH")
    prior=private_file(IDENTITY,512)
    old_hist=private_file(HISTORY,220000)
    require(len(old_j["turns"])>0,"NO_EXISTING_TURNS_TO_ARCHIVE")
    time.sleep(1.4)
    require(before==idle() and prior==private_file(IDENTITY,512)
            and old_hist==private_file(HISTORY,220000),
            "OWNER_CHANGED_DURING_PREFLIGHT")
    key=archive_key(before[0])
    folder=safe_archive_dir()
    if folder is None:
        ARCHIVES.mkdir(mode=0o700)
        folder=safe_archive_dir()
    target=folder/(key+".json")
    previous_archive=private_file(target,220000) if target.exists() else None
    if previous_archive is not None and previous_archive!=old_hist:
        # A failed earlier rotation may leave a 59-turn archive while the
        # restored old Session has gained additional journal-recovered turns.
        # Upgrade only when every archived verified turn is still represented.
        older=json.loads(previous_archive)
        from collections import Counter
        def identity(row):
            if not isinstance(row,dict):return None
            return (row.get("user"),row.get("assistant"),row.get("origin"))
        old_items=older.get("turns")
        current_items=old_j["turns"]
        # The native journal recovery may insert earlier turns in original
        # order. An archived subset need not be a strict prefix.
        require(older.get("schema")==3 and
                older.get("session_id")==old_j["session_id"] and
                isinstance(old_items,list) and
                len(old_items)<=len(current_items) and
                all(identity(x) is not None for x in old_items) and
                Counter(map(identity,old_items))<=Counter(map(identity,current_items)),
                "ARCHIVE_SUBSET_VALIDATION_FAILED")
    newtab=uuid.uuid4().hex
    txn=folder/("rotation-"+key+"-"+uuid.uuid4().hex[:8])
    require(not txn.exists(),"ROTATION_ID_COLLISION")
    txn.mkdir(mode=0o700)
    put_atomic(txn/"old-tab.json",prior)
    put_atomic(txn/"old-history.json",old_hist)
    if previous_archive is not None:
        put_atomic(txn/"before-archive.json",previous_archive)
    if previous_archive!=old_hist:
        put_atomic(target,old_hist)
    transaction("r677_old_session_archived",txn,
                archived_turns=len(old_j["turns"]),archive_id=key,
                old_session_id_sha=hashlib.sha256(before[0].encode()).hexdigest()[:24])
    changed=False
    try:
        require(idle()==before,"OWNER_BUSY_BEFORE_NEW_SESSION")
        put_atomic(IDENTITY,(json.dumps({"schema":1,"tab_id":newtab})+"\n").encode())
        changed=True
        oldpid=before[3]["8877"]
        os.kill(oldpid,signal.SIGTERM)
        transaction("r677_new_tab_published_owner_restart_requested",txn)
        end=time.monotonic()+85
        check_counts={}
        def missed(reason):
            check_counts[reason]=check_counts.get(reason,0)+1
        while time.monotonic()<end:
            time.sleep(.8)
            try:
                gw=port(8877)
                if not gw or gw==oldpid:
                    missed("waiting_new_owner");continue
                snap=peers()
                if snap.get("8877")!=gw or any(
                    snap.get(k)!=v for k,v in before[3].items() if k!="8877"):
                    missed("other_owner_changed");continue
                a,t=official()
                if t!=newtab:
                    missed("tab_not_switched");continue
                # The normal Wi-Fi owner creates the new native Agent
                # without an LLM call, not this manager script.
                snapshot=a.inspect(newtab)
                if not snapshot.get("ok") or snapshot.get("busy") or snapshot.get("pending_resume"):
                    missed("native_agent_unavailable");continue
                if snapshot["session_id"]==before[0]:
                    missed("old_session_still_bound");continue
                model=snapshot.get("last_request") or snapshot.get("selected")
                # Official DSH now returns reasoningEffort:"high" along
                # with the exact provider/model. The extra verified field
                # is not a model mismatch, and must not roll back a
                # genuinely fresh, idle, correct Session.
                if (not isinstance(model,dict) or
                    model.get("provider")!="deepseek-official" or
                    model.get("model")!="deepseek-flash" or
                    set(model)-{"provider","model","reasoningEffort"} or
                    model.get("reasoningEffort","high")!="high"):
                    missed("model_selection_not_verified");continue
                if stamp()!=gw:
                    missed("wifi_owner_not_verified");continue
                w=json.loads((ROOT.parent/"lan-pairing/lan-gateway-status.json").read_text())
                if (w.get("active_devices")!=1 or w.get("pending_dsh_jobs")!=0 or
                    w.get("device_phase")!="prewake_streaming"):
                    missed("board_not_reconnected");continue
                status=json.loads(private_file(ROOT/"status.json",64000))
                if (status.get("session_id")!=snapshot["session_id"] or
                    status.get("phase")!="idle" or
                    status.get("session_verified") is not True):
                    missed("native_ui_status_mismatch");continue
                fresh=json.loads(private_file(HISTORY,220000))
                if (fresh.get("session_id")!=snapshot["session_id"] or
                    fresh.get("session_verified") is not True or
                    fresh.get("turns")!=[]):
                    missed("new_session_history_not_reset");continue
                transaction("r677_fresh_context_active_and_old_archive_preserved",
                    txn,old_session_id_sha=key,
                    new_session_id_sha=archive_key(snapshot["session_id"]),
                    archived_turns=len(old_j["turns"]),model_calls=0,
                    all_permanent_memories_untouched=True)
                return {"ok":True,"new_session":archive_key(snapshot["session_id"]),
                        "old_archive":key,"old_turns":len(old_j["turns"]),
                        "model_calls":0}
            except (OSError,ValueError,RuntimeError,KeyError) as err:
                missed("native_reconnect_io_"+type(err).__name__);continue
        transaction("r678_rotation_diagnostics",txn,check_counts=check_counts)
        raise RuntimeError("NEW_SESSION_RECONNECT_NOT_VERIFIED")
    except BaseException as e:
        transaction("r677_rollback_started",txn,error=type(e).__name__,
                    **({"check_counts":check_counts} if "check_counts" in locals() else {}))
        if changed:
            put_atomic(IDENTITY,prior)
            put_atomic(HISTORY,old_hist)
            now=port(8877)
            if now:
                try:os.kill(now,signal.SIGTERM)
                except ProcessLookupError:pass
            # R319 owns any future gateway rebind; never force a second DSH
            # model turn or silently claim recovery until the old tab verifies.
            transaction("r677_old_tab_restored_rebind_pending",txn,
                        **({"check_counts":check_counts} if "check_counts" in locals() else {}))
        raise

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("status","archives","archive","new"))
    p.add_argument("--id",default="")
    p.add_argument("--confirm",default="")
    opts=p.parse_args()
    try:
        if opts.action=="status":output=context_status()
        elif opts.action=="archives":output={"ok":True,"archives":archives_summary()}
        elif opts.action=="archive":output=read_archive(opts.id)
        else:
            require(opts.confirm==CONFIRM,"USER_CONFIRMATION_REQUIRED")
            output=new_session()
        print(json.dumps(output,ensure_ascii=False,separators=(",",":")))
    except Exception as exc:
        # Error classification only; do not leak private file names, tokens,
        # session IDs, tool arguments or transcripts to caller/UI.
        print(json.dumps({"ok":False,"error":str(exc)[:110]
                          if str(exc).startswith("R677_") else type(exc).__name__}))
        raise SystemExit(2)
if __name__=="__main__":main()
