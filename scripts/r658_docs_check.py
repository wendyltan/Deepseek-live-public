#!/usr/bin/env python3
"""R658 public Markdown/docs linter; offline and no secret-file reads."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[1]
DOCS=(
    "README.md","README.en.md","LICENSE_SCOPE.md",
    "CONTRIBUTING.md","SECURITY.md",
    "CHANGELOG.md","docs/INSTALL_MAC.md","docs/FIRST_BOOT_ESP32.md",
    "docs/ANIMATION_RIGHTS_REGISTER.md",
    "docs/INSTALL_WHISPER_CPP.md","docs/INSTALL_QWEN3_TTS.md",
    "docs/INSTALL_PINKY_CUA.md","docs/AGENT_INSTALL_PROMPT.md",
    "docs/INSTALL_VOICE_GATEWAY.md",
    "docs/HARDWARE_AND_MICROSD.md",
    "docs/VOICE_PROVENANCE.md","release-assets/voice/README.md",
    "docs/INSTALL_ESP32_FIRMWARE_AND_MOTIONS.md","release-assets/animation/README.md",
    "docs/ARCHITECTURE.md","docs/PLUGINS.md","docs/TROUBLESHOOTING.md",
    "docs/THIRD_PARTY_NOTICES.md","docs/OPEN_SOURCE_COMPANION_DEPLOYMENT.md",
    "plugins/dsh-live-bridge/README.md",
    "firmware/esp32/unified-wifi-wake/README.md",
)
MARKDOWN=re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
HTML=re.compile(r'<(?:img|a)\s[^>]*(?:src|href)="([^"]+)"')
PRIVATE=(
    re.compile(r"(?i)sk-(?:proj-|live-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"/Users/(?!example|USER|yourname)[A-Za-z0-9._-]+/"),
    re.compile(r"/Volumes/ExtSSD/"),
    re.compile(r"(?i)(?:api_key|bridge_token|memory_admin_token)\s*[:=]\s*['\"]?[A-Za-z0-9+/=_-]{30,}"),
)

def check():
    links=0;missing=[];fences=[];private=[]
    for name in DOCS:
        file=ROOT/name
        if not file.is_file():
            missing.append(name+":file_missing")
            continue
        body=file.read_text(encoding="utf-8")
        if sum(x.lstrip().startswith("```") for x in body.splitlines())%2:
            fences.append(name)
        if any(p.search(body) for p in PRIVATE):
            private.append(name)
        paths=[m.group(1) for m in MARKDOWN.finditer(body)]
        paths.extend(m.group(1) for m in HTML.finditer(body))
        for ref in paths:
            if ref.startswith(("http:","https:","mailto:","#","data:")):
                continue
            path=unquote(ref.split("#",1)[0])
            if not path:continue
            target=(file.parent/path).resolve(strict=False)
            links+=1
            if not target.is_relative_to(ROOT) or not target.exists():
                missing.append(name+":"+path)
    return {"schema":1,"public_files_checked":len(DOCS),
            "local_links_checked":links,"missing":missing,
            "unbalanced_fences":fences,
            "possible_private_content_in_files":private,
            "ok":not (missing or fences or private)}

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--strict",action="store_true")
    o=p.parse_args()
    result=check()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if o.strict and not result["ok"]:
        raise SystemExit(2)
