#!/usr/bin/env python3
"""Private stdio MCP relay: identify Deepseek-live as 大肥鱼 in Pinky.

Only rewrites the JSON-RPC initialize.clientInfo.name; all other protocol
messages are forwarded unchanged. Never reads Pinky tokens or phone content.
"""
import json
import os
import subprocess
import sys
import threading

PINKY=os.environ.get('DAFEIYU_PINKYCTL','/opt/homebrew/bin/pinkyctl')
NAME='大肥鱼'
MAX_LINE=4_000_000


def identify(line:bytes)->bytes:
    if len(line)>MAX_LINE:
        return line
    try:
        message=json.loads(line)
        if not isinstance(message,dict) or message.get('method')!='initialize':
            return line
        params=message.get('params')
        if not isinstance(params,dict) or not isinstance(params.get('clientInfo'),dict):
            return line
        params['clientInfo']['name']=NAME
        return (json.dumps(message,ensure_ascii=False,separators=(',',':'))+'\n').encode()
    except (UnicodeError,ValueError,TypeError):
        return line


def pipe(src,dst,transform=None):
    try:
        while True:
            line=src.readline(MAX_LINE+1)
            if not line:break
            dst.write(transform(line) if transform else line)
            dst.flush()
    except (BrokenPipeError,OSError):
        pass
    finally:
        try:dst.close()
        except OSError:pass


def main():
    child=subprocess.Popen([PINKY,'mcp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                           stderr=sys.stderr,bufsize=0,close_fds=True)
    t=threading.Thread(target=pipe,args=(child.stdout,sys.stdout.buffer),daemon=True)
    t.start()
    try:
        pipe(sys.stdin.buffer,child.stdin,identify)
        return child.wait()
    finally:
        if child.poll() is None:child.terminate()

if __name__=='__main__':sys.exit(main())
