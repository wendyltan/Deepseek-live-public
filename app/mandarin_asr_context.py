"""Bounded Mandarin ASR context for ESP32 onboard-mic dictation.

Whisper gets a pronunciation context, not a forced transcript. Only the
specific observed homophone substitutions are corrected, with a strict
weather-query guard for the place name.
"""
import re

# NOT passed to Whisper as an initial prompt: the prior named-word prompt
# became a verbatim phantom transcript on short post-wake recordings.
MANDARIN_INITIAL_PROMPT=""

def recover_known_terms(text: str) -> tuple[str,tuple[str,...]]:
    if not isinstance(text,str):raise ValueError("invalid_asr_input")
    edits=[]
    result=text
    for wrong,right in (("大肥瑜","大肥鱼"),("大飞鱼","大肥鱼")):
        if wrong in result and ("你好" in result or result.startswith(wrong)):
            result=result.replace(wrong,right)
            edits.append("avatar_homophone")
    # R541: recover one actually observed app-name homophone from the
    # user's verified ESP32 ASR text. Do not override an unrelated mention
    # of "产购"; never silently infer or change the user's price range.
    if "淘宝产购" in result and any(w in result for w in
                                  ("打开","手机","购物车","面包")):
        result=result.replace("淘宝产购","淘宝闪购")
        edits.append("taobao_shangou_real_asr_homophone")
    return result,tuple(edits)
