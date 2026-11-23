"""Local proposed SD sync plan, intentionally not a device-write implementation.

Current R61 and R71 firmware accept only 35 built-in motion IDs; arbitrary
imported candidates REQUIRE future allowlist/reader and explicit hardware QA.
The manifest makes those blockers visible, never claims successful upload.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import uuid
from datetime import datetime,timezone
from pathlib import Path
from scripts.r72_prepare_motion_candidate import ROOT,ID,verify,ConversionError

class SyncPlanError(ValueError):pass

ROLE_MAP={"待机":"idle","工作":"work","互动":"reaction","彩蛋":"bonus"}
def plan(root:Path=ROOT):
    # Optional Mac UI classification snapshot; its role is *proposed*.
    # The device does not trust it until a new firmware allowlist is built.
    chosen=None
    ui=root/"pending-motion-plan.json"
    if ui.is_file():
        if ui.is_symlink() or ui.stat().st_size>100_000:
            raise SyncPlanError("untrusted_ui_plan")
        parsed=json.loads(ui.read_text())
        if (parsed.get("schema")!=1 or parsed.get("status")!="pending_review_not_on_device"
            or type(parsed.get("motions")) is not list):
            raise SyncPlanError("invalid_ui_plan")
        chosen={}
        for motion in parsed["motions"]:
            ident=motion.get("id")
            role=motion.get("category")
            if ident in chosen or not isinstance(ident,str) or not ID.fullmatch(ident):
                # Selected catalog entries mNNN are not converted here:
                # they have a separate immutable 35-entry device map.
                if ident and isinstance(ident,str) and re.fullmatch(r"m[0-9]{3}",ident):
                    continue
                raise SyncPlanError("invalid_candidate_selection")
            if role not in ROLE_MAP:raise SyncPlanError("unassigned_or_bad_action_class")
            chosen[ident]=ROLE_MAP[role]
    imports=root/"candidates"
    candidates=sorted(imports.glob("u????????????.json"))
    if len(candidates)>100:raise SyncPlanError("too_many_candidates")
    records=[];ids=set()
    for file in candidates:
        if file.is_symlink() or not file.is_file():raise SyncPlanError("unsafe_manifest")
        ident=file.stem
        if ID.fullmatch(ident) is None or ident in ids:raise SyncPlanError("invalid_id")
        if chosen is not None and ident not in chosen:continue
        ids.add(ident)
        if file.stat().st_size>4096:raise SyncPlanError("manifest_too_large")
        metadata=json.loads(file.read_text())
        dfs=imports/(ident+".DFS")
        if dfs.is_symlink() or not dfs.is_file() or dfs.stat().st_size>8_000_000:
            raise SyncPlanError("missing_or_unsafe_dfsp")
        checked=verify(dfs.read_bytes())
        if metadata.get("id")!=ident or metadata.get("sha256")!=checked["sha256"]:
            raise SyncPlanError("candidate_integrity_mismatch")
        records.append({"id":ident,"action_class":(chosen or {}).get(ident,"unassigned"),
          "bytes":checked["bytes"],
          "sha256":checked["sha256"],"frames":checked["frames"],
          "max_packet":checked["max_compressed_packet"],
          "assigned_device_id":None,
          "hardware_allowlisted":False,"device_written":False,
          "device_readback_verified":False,"source":"local_candidate"})
    # Assign only the proposed *future* user animation slots; never use the
    # factory 35 IDs. These are NOT firmware-allowlisted on R61/R79.
    if len(records)>8:
        raise SyncPlanError("user_slot_capacity_eight_exceeded")
    for slot,record in enumerate(records,start=200):
        record["assigned_device_id"]=f"m{slot:03d}"
        record["hardware_allowlisted"]=False
    return {"schema":1,"stage":"offline_sync_proposal","count":len(records),
      "motions":records,"on_device":False,
      "policy":{"preserve_original_35":True,"requires_firmware_allowlist":True,
      "requires_device_version_handshake":True,"requires_transactional_write":True,
      "requires_post_write_sha256_readback":True,
      "automatic_flash_enabled":False,
      "USB_connection_permitted_now":False}}

def save(*,root:Path=ROOT):
    data=plan(root)
    # Each revision gets a new immutable plan; later classification changes
    # must never silently mutate a plan already reviewed by the user.
    suffix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file=root/("pending-install-"+suffix+"-"+uuid.uuid4().hex[:8]+".json")
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with file.open("x") as out:
        os.fchmod(out.fileno(),0o600)
        json.dump(data,out,ensure_ascii=False,indent=2)
        out.flush();os.fsync(out.fileno())
    data["saved_to"]=str(file)
    return data

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--save",action="store_true")
    a=p.parse_args()
    try:
        result=save() if a.save else plan()
        print(json.dumps(result,ensure_ascii=False))
    except (SyncPlanError,ConversionError,OSError,ValueError) as exc:
        print(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False))
        raise SystemExit(2)
