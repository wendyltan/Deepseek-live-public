"""Explicit verified ESP voice -> small Mac-local read-only commands.

No shell, recursive filesystem traversal, synthetic device success, or ambient
recording. A capability question is not permission to enumerate Desktop.
"""
from __future__ import annotations
import os
import re
from datetime import datetime
from pathlib import Path

CATALOG=(
 ("大肥鱼，现在几点了", "local_clock"),
 ("大肥鱼，列出桌面文件", "desktop_names"),
 ("大肥鱼，你在吗", "wake"),
 ("大肥鱼，你会什么", "help"),
)
DESKTOP_PATTERNS=(
 re.compile(r"^(?:大肥鱼)?(?:请|帮我)?(?:列出|查看|说说|告诉我)(?:一下)?(?:我(?:电脑)?的)?桌面(?:上|文件夹里?)?(?:有(?:哪些|什么))?(?:文件|项目|内容)?(?:的名字|名称|列表)?$"),
 re.compile(r"^(?:大肥鱼)?(?:我(?:电脑)?的)?桌面(?:上|文件夹里?)?有(?:哪些|什么)文件$"),
)
CLOCK_EXACT=frozenset(("几点了","现在几点了","现在几点","大肥鱼几点了","大肥鱼现在几点了"))
def command_for_transcript(text,*,verified_stt=False):
    if verified_stt is not True or not isinstance(text,str) or len(text)>200:return None
    phrase=re.sub(r"[\s，。？！?,.!]+","",text)
    if phrase in CLOCK_EXACT:return "clock"
    if any(pattern.fullmatch(phrase) for pattern in DESKTOP_PATTERNS):return "desktop_names"
    return None

def execute_local_command(kind,*,desktop=None,now=None):
    if kind=="clock":
        current=now or datetime.now()
        return "现在是"+current.strftime("%H点%M分")+"。"
    if kind!="desktop_names":raise ValueError("unsupported_local_command")
    path=desktop or Path.home()/"Desktop"
    # Source must be a physical expected user's own desktop directory.
    if path.is_symlink() or not path.is_dir():
        return "我暂时无法读取桌面目录，请在Mac检查文件权限。"
    try:
        items=[]
        with os.scandir(path) as it:
            for entry in it:
                if entry.name.startswith(".") or entry.is_symlink():continue
                if not entry.is_file(follow_symlinks=False) and not entry.is_dir(follow_symlinks=False):continue
                items.append(entry.name[:45])
                if len(items)>=30:break
    except (PermissionError,OSError):
        return "我没有读取桌面的权限，请在Mac检查相关权限。"
    if not items:return "目前桌面没有可见文件或文件夹。"
    names="、".join(sorted(items,key=str.casefold)[:8])
    suffix="。我只读取了文件名，没有打开文件内容。"
    if len(items)>8:suffix="等。为避免语音过长，我只报前八项。没有打开文件内容。"
    return "我在你的桌面上看到："+names+suffix
