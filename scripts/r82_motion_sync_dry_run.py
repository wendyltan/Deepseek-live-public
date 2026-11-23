"""Complete host-only custom motion install rehearsal, no serial device.

Fetches candidate from private Mac directory and checks SHA-256 + DFSP
content; sends staged 384-byte chunks into a *RAM-only* protocol simulator
with identical ACK/COMMIT/VERIFY expectations of future firmware v3.
"""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path
from scripts.r72_plan_motion_sync import plan,SyncPlanError
from scripts.r72_prepare_motion_candidate import ROOT,verify
from app.r82_motion_usb_transport import upload,FakeFutureDevice,TransferRejected

def run(root=ROOT):
    pending=plan(root)
    entries=pending["motions"]
    fake=FakeFutureDevice()
    report=[]
    for motion in entries:
        slot=int(motion["assigned_device_id"][1:])
        role=motion["action_class"]
        if role not in {"idle","work","reaction","bonus"}:
            raise SyncPlanError("action_class_required_for_install")
        path=root/"candidates"/(motion["id"]+".DFS")
        if not path.is_file() or path.is_symlink() or path.stat().st_size>8_000_000:
            raise SyncPlanError("unsafe_candidate_path")
        blob=path.read_bytes()
        frame=verify(blob)
        if frame["sha256"]!=motion["sha256"]:
            raise SyncPlanError("stale_or_corrupted_manifest")
        receipt=upload(fake,slot=slot,contents=blob,role=role,
                       local_confirmation=True)
        report.append({"local_id":motion["id"],"future_slot":receipt.slot,
          "size":receipt.bytes_written,"chunks":receipt.chunks,
          "sha256":receipt.sha256,
          "simulated_sd_readback_equal":fake.files[receipt.slot]==blob})
    return {"schema":1,"mode":"offline_simulator_no_usb",
      "tested":len(report),"simulator_verified":all(x["simulated_sd_readback_equal"] for x in report),
      "physical_esp32_written":False,"actual_sd_readback":False,
      "device_version_supported":False,
      "factory_35_modified":False,"results":report}
if __name__=="__main__":
    try:
        result=run()
        print(json.dumps(result,ensure_ascii=False))
    except (SyncPlanError,TransferRejected,ValueError,OSError) as exc:
        print(json.dumps({"mode":"offline_simulator_no_usb","ok":False,
            "error":str(exc)},ensure_ascii=False))
        raise SystemExit(2)
