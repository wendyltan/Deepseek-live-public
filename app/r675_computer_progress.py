"""R675 computer-use narration intent gate; no model, side effects or claims.

Enable intermediate voice only for an explicit imperative desktop request.
The actual narration is triggered only by native CUA facts, never intent alone.
"""
from __future__ import annotations
import re
ACTION=re.compile(r"(?:帮(?:我|忙)?|请(?:你)?|替我|给我|现在|打开|查看|看看|看下|检查|操作|点击|点开|读取|切换|启动|关闭|帮忙)")
OBJECT=re.compile(r"(?:Mac(?:\s*Book|\s*mini)?|macOS|我的电脑|我电脑|这台电脑|本机电脑|电脑上|电脑里|电脑当前|电脑桌面|Finder|访达|Chrome|Safari|Edge|浏览器|终端(?:窗口|应用)?|桌面(?:窗口|应用|文件)|当前(?:窗口|应用)|窗口(?:内容|状态)|前台(?:程序|应用)|当前(?:标签页|页面)|应用程序)",re.I)
DISCUSSION=re.compile(r"^(?:(?:给我|帮我|请你|请给我))?(?:为什么|什么是|介绍|讲解|解释|科普|分析|讨论|教程|如何|怎么|能不能|可不可以|为什么说|比较|对比|说说)")
def explicit_mac_action(text):
    if not isinstance(text,str) or not 2<=len(text)<=600:return False
    if DISCUSSION.match(text.strip()):return False
    if (re.search(r'手机|iPhone|Pinky|电话',text,re.I) and
        not re.search(r'Mac|电脑|Finder|访达|Chrome|Safari|Edge|浏览器|桌面',text,re.I)):
        return False
    objects=list(OBJECT.finditer(text))
    actions=list(ACTION.finditer(text))
    return any(abs(a.start()-o.start())<=38 for a in actions for o in objects)

def computer_voice_progress_permitted(stage:str,*,elapsed_s:float,
                                      since_last_s:float|None,announced:int)->bool:
    """Only useful long-running native CUA stages become audible.

    Native UI records all verified steps separately. For a fast finished
    task, do not spend multiple seconds synthesizing progress; the final
    verified answer is more useful. Human approval remains immediate.
    """
    if stage in ("cua_waiting_permission","approval_pending"):
        return True
    if stage not in ("cua_running","still_working","still_working_later") and not (
        stage.startswith("cua_step_") and stage[9:].isdigit()
        and 1<=int(stage[9:])<=32):
        return False
    if elapsed_s<10.0 or announced>=2:
        return False
    if since_last_s is not None and since_last_s<24.0:
        return False
    return True
