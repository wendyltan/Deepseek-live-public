"""R679: deterministic, speech-only technical token pronunciation.

Use only for verified native Mac CUA answer text. The exact original DSH
answer remains visible, including all paths, CLI commands, file extensions.
This display-specific voice adaptation never changes a real tool result or
sends sensitive local usernames/absolute path to Qwen TTS.
"""
from __future__ import annotations
import re

_ABS_PATH=re.compile(
    r"(?<![\w/])/(?:Users|Volumes|home|private|tmp|Library|Applications|System|opt|var)"
    r"(?:/[A-Za-z0-9_\-.+%\u3400-\u9fff ]{1,120}){1,12}")
_CODE=re.compile(r"`([^`\r\n]{1,240})`")
_TXT=re.compile(r"(?<![A-Za-z0-9_./])([\u3400-\u9fff][\u3400-\u9fff0-9_-]{0,24})\.txt(?!\w)",re.I)
_OTHER_DOC=re.compile(
    r"(?<![A-Za-z0-9_./])([\u3400-\u9fff][\u3400-\u9fffA-Za-z0-9_-]{0,62})"
    r"\.(md|pdf|docx|xlsx|csv)(?![A-Za-z0-9_])",re.I)

def contains_native_path(source:str)->bool:
    return isinstance(source,str) and bool(_ABS_PATH.search(source))

def oral_mac_technical_text(spoken:str,source:str)->tuple[str,dict[str,int]]:
    if not isinstance(spoken,str) or not isinstance(source,str):
        raise ValueError("r679_spoken_source_required")
    if not 1<=len(spoken)<=8000 or not 1<=len(source)<=12000:
        raise ValueError("r679_spoken_source_oversized")
    count={"file_paths":0,"terminal_commands":0,"filenames":0}
    def path(m):
        count["file_paths"]+=1
        return "完整路径见 Mac 对话"
    # Replace paths with an audible reference to the EXACT on-screen answer,
    # not a guessed shortened path or a fake filesystem location.
    spoken=_ABS_PATH.sub(path,spoken)
    commands={"touch":"创建文件的命令","ls -l":"查看文件信息的命令",
              "pwd":"显示当前目录的命令","mkdir":"创建文件夹的命令",
              "mkdir -p":"创建文件夹的命令"}
    for match in _CODE.finditer(source):
        val=match.group(1).strip()
        if val in commands and re.search(
                r"(?<![A-Za-z0-9_/])"+re.escape(val)+r"(?![A-Za-z0-9_/-])",spoken):
            spoken=re.sub(
                r"(?<![A-Za-z0-9_/])"+re.escape(val)+r"(?![A-Za-z0-9_/-])",
                commands[val],spoken,count=1)
            count["terminal_commands"]+=1
    def filename(m):
        count["filenames"]+=1
        name=m.group(1).strip()
        return "名为"+name+"的文本文件"
    spoken=_TXT.sub(filename,spoken)
    labels={"md":"Markdown文档","pdf":"PDF文件","docx":"Word文档",
            "xlsx":"Excel表格","csv":"CSV文件"}
    def other_doc(m):
        count["filenames"]+=1
        return "名为"+m.group(1)+"的"+labels[m.group(2).lower()]
    spoken=_OTHER_DOC.sub(other_doc,spoken)
    # Normalise a naturally redundant "路径是完整路径见..." introduced
    # by dropping the unpronounceable filesystem literal.
    spoken=spoken.replace("路径是 完整路径见 Mac 对话","完整路径见 Mac 对话")
    spoken=spoken.replace("路径是完整路径见 Mac 对话","完整路径见 Mac 对话")
    spoken=re.sub(r"纯文本文件\s+名为([^，。；]{1,40})的文本文件",
                  r"名为\1的纯文本文件",spoken)
    spoken=re.sub(r"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])",
                  "",spoken)
    return spoken,count
