#!/usr/bin/env python3
"""Build the 106 credited motion clips into an SD-ready DFSP tree on the Mac.

Source WebM clips are obtained by the user under their original license.
This script never downloads unapproved media or writes an ESP32/physical SD.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import struct
import zlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CATALOG=ROOT/"app/motion-review/catalog.json"
REFERENCE=ROOT/"release-assets/animation/dfsp-hashes.json"
HEADER=struct.Struct("<4sBHHBH")
FRAME_HEADER=struct.Struct("<BI")
SIZE=240
FPS=8
MAX_BLOCK=65536


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as file:
        for b in iter(lambda:file.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def blob_sha1(path: Path) -> str:
    h=hashlib.sha1()
    h.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def entries() -> list[dict]:
    m=json.loads(CATALOG.read_text())
    items=m["motions"]
    if len(items)!=106 or [x["id"] for x in items]!=[f"m{i:03}" for i in range(106)]:
        raise ValueError("motion_catalog_requires_exact_106_ids")
    return items


def source_for(asset_dir: Path, meta: dict) -> Path:
    if not asset_dir.is_dir() or asset_dir.is_symlink():
        raise ValueError("missing_or_symlink_upstream_asset_directory")
    candidates=[asset_dir/(meta["id"]+".webm"),asset_dir/meta["upstream_file"]]
    found=[p for p in candidates if p.is_file() and not p.is_symlink()]
    if not found:
        raise FileNotFoundError(meta["id"]+".webm")
    for path in found:
        if path.stat().st_size == meta["upstream_size"] and blob_sha1(path)==meta["upstream_git_blob"]:
            return path
    raise ValueError(f"upstream_blob_mismatch:{meta['id']}")


def plan(asset_dir: Path, *, max_clips: int=106) -> dict:
    if not 1<=max_clips<=106:
        raise ValueError("clip_count_out_of_bounds")
    items=entries()[:max_clips]
    verified=[]
    for meta in items:
        path=source_for(asset_dir,meta)
        verified.append(meta["id"])
    return {"schema":1,"mode":"plan","verified_webm_count":len(verified),
            "all106_verified":len(verified)==106,
            "upstream":"PC2005-cloud/dsh-pet@c696095c5786e0eeb25fec0f37a9cdcf30059151",
            "license":"CC BY-NC-SA 4.0, original author attribution required",
            "physical_sd_written":False,"esp32_flashing_performed":False}


def render(source: Path, path: Path) -> dict:
    from scripts.motion_dfsp_codec import (
        decode_frames,calculate_box,rescale_sprite,verify_container
    )
    frames=list(decode_frames(source))
    if not 1<=len(frames)<=100:
        raise ValueError("invalid_8fps_frame_count")
    bbox=calculate_box(frames)
    data=bytearray(HEADER.pack(b"DFSP",1,SIZE,SIZE,FPS,len(frames)))
    prev=None
    for index,frame in enumerate(frames):
        current=rescale_sprite(frame,bbox,SIZE)
        if len(current)!=SIZE*SIZE*3:
            raise ValueError("invalid_rgb565_alpha_frame_size")
        raw=zlib.compress(current,6)
        delta=(zlib.compress(bytes(x^y for x,y in zip(current,prev)),6)
               if prev is not None and index%8 else None)
        kind,part=(2,delta) if delta is not None and len(delta)<len(raw) else (1,raw)
        if len(part)>MAX_BLOCK:
            raise ValueError("compressed_packet_exceeds_64kb")
        data.extend(FRAME_HEADER.pack(kind,len(part)))
        data.extend(part)
        prev=current
    # Owns a new output tree; atomic individual write and full decode checks.
    with path.open("xb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    if verify_container(path)!=len(frames):
        raise ValueError("saved_dfsp_decode_failed")
    return {"id":path.stem.lower(),"bytes":len(data),"frames":len(frames),
            "sha256":hashlib.sha256(data).hexdigest()}


def stage(asset_dir: Path, destination: Path, *, max_clips:int=106,
          compare_reference:bool=False) -> dict:
    verified=plan(asset_dir,max_clips=max_clips)
    dest=destination.expanduser().resolve(strict=False)
    if dest.exists() or destination.is_symlink():
        raise FileExistsError("destination_already_exists")
    if dest==Path("/") or dest.parent==Path("/Volumes") or (
        Path("/Volumes") in dest.parents and ROOT not in dest.parents
    ):
        raise ValueError("refuse_physical_or_other_mounted_volume")
    if ROOT in dest.parents:
        status=os.spawnvp(os.P_WAIT,"git",["git","-C",str(ROOT),"check-ignore","-q",str(dest)])
        if status:
            raise ValueError("project_output_must_be_gitignored")
    selected=entries()[:max_clips]
    reference={}
    if compare_reference:
        m=json.loads(REFERENCE.read_text())
        reference={x["id"]:x for x in m["motions"]}
    root=dest/"DAFEIYU/MOTIONS"
    root.mkdir(parents=True,exist_ok=False)
    items=[]
    try:
        for meta in selected:
            source=source_for(asset_dir,meta)
            asset=root/(meta["id"].upper()+".DFS")
            item=render(source,asset)
            if compare_reference:
                expected=reference[item["id"]]
                if any(item[k]!=expected[k] for k in ("bytes","frames","sha256")):
                    raise ValueError(
                        f"converted_asset_differs_from_verified_reference:{item['id']}"
                    )
            items.append(item)
        digest_manifest={"schema":1,"source":"upstream-blob-verified-webm",
                         "license":"CC BY-NC-SA 4.0","motion_count":len(items),
                         "complete106":len(items)==106,
                         "physical_sd_written":False,"esp32_flashing_performed":False,
                         "items":items}
        (dest/"DAFEIYU/MOTION_CHECKSUMS.json").write_text(
            json.dumps(digest_manifest,ensure_ascii=False,indent=2)+"\n")
    except Exception:
        # The directory was created above with exist_ok=False. It contains
        # only files written by this invocation; no pre-existing user data.
        shutil.rmtree(dest)
        raise
    return {"staged":True,"destination":str(dest),"files":len(items),
            "total_bytes":sum(x["bytes"] for x in items),
            "matches_verified_reference":bool(compare_reference),
            "physical_sd_written":False,"esp32_flashing_performed":False,
            "ready_for_release":False}


def export_mac_assets(motions_dir: Path, *,
                      previews_dir: Path | None = None,
                      gifs_dir: Path | None = None) -> dict:
    from scripts.motion_dfsp_codec import decode_dfsp_frames, rgb565a8_to_rgb_image
    from scripts.verify_motion_library import inspect as verify_dfsp
    check = verify_dfsp(motions_dir)
    if not check["complete"]:
        raise ValueError("motions_dir_incomplete_or_mismatched")
    if previews_dir is not None:
        previews_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if gifs_dir is not None:
        gifs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    exported_jpg = 0
    exported_gif = 0
    for meta in entries():
        ident = meta["id"]
        dfs_path = motions_dir / (ident.upper() + ".DFS")
        frames = [rgb565a8_to_rgb_image(raw, size=w)
                  for w, _, raw in decode_dfsp_frames(dfs_path)]
        if previews_dir is not None:
            jpg_path = previews_dir / (ident + ".jpg")
            frames[len(frames)//3].save(jpg_path, format="JPEG", quality=90)
            os.chmod(jpg_path, 0o600)
            exported_jpg += 1
        if gifs_dir is not None:
            gif_path = gifs_dir / (ident.upper() + ".gif")
            frames[0].save(gif_path, format="GIF", save_all=True,
                           append_images=frames[1:], loop=0,
                           duration=125, disposal=2)
            os.chmod(gif_path, 0o600)
            exported_gif += 1
    return {"schema": 1, "mode": "mac-assets", "verified_dfsp": 106,
            "exported_previews_jpg": exported_jpg,
            "exported_animated_gifs": exported_gif,
            "previews_dir": str(previews_dir) if previews_dir else None,
            "gifs_dir": str(gifs_dir) if gifs_dir else None}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode",choices=("plan","stage","mac-assets"),default="plan")
    p.add_argument("--source-dir",type=Path,
                   help="Licensed, SHA-validated 106 upstream WebM clips (or DFSP dir for --mode mac-assets)")
    p.add_argument("--destination",type=Path)
    p.add_argument("--previews-dir",type=Path,help="Output directory for 106 m000.jpg..m105.jpg Mac App thumbnails")
    p.add_argument("--gifs-dir",type=Path,help="Output directory for 106 M000.gif..M105.gif Mac desktop pet animations")
    p.add_argument("--first",type=int,default=106)
    p.add_argument("--compare-reference",action="store_true")
    args=p.parse_args()
    if args.mode=="mac-assets":
        if args.source_dir is None or (args.previews_dir is None and args.gifs_dir is None):
            p.error("--source-dir and at least one of --previews-dir / --gifs-dir are required for --mode mac-assets")
        r=export_mac_assets(args.source_dir,previews_dir=args.previews_dir,gifs_dir=args.gifs_dir)
    elif args.mode=="stage":
        if args.source_dir is None or args.destination is None:
            p.error("--source-dir and --destination are required for --mode stage")
        r=stage(args.source_dir,args.destination,max_clips=args.first,
                compare_reference=args.compare_reference)
    else:
        if args.source_dir is None:
            p.error("--source-dir is required for --mode plan")
        r=plan(args.source_dir,max_clips=args.first)
    print(json.dumps(r,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
