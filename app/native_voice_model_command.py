"""Verified ESP32/STT voice model switch routed to the SAME official DSH tab.

Only an explicit command, only currently advertised models, and an actual
DSH switch+session receipt can change the Mac status. No chat/LLM request.
"""
from __future__ import annotations
from app.model_catalog import parse_model_command

def handle_voice_model_command(native, utterance: str, *, output=print):
    if not isinstance(utterance,str) or len(utterance)>100:
        return None
    # Drawing/image model is a separate capability. Do not silently change
    # the dialogue model when the user explicitly specified '绘画模型'.
    if any(word in utterance for word in ("绘画模型","生图模型","画图模型")):
        if any(word in utterance for word in ("切换","切到","换到","换成","改成","改用")):
            return "当前只能切换大肥鱼的对话模型。绘画模型属于单独服务，我没有修改它。"
        return None
    # Cheap intent gate: prevent catalog network calls on ordinary speech.
    triggers=("切换","切到","切回","换到","换回","换成","改用","改成","调到","调成","换模型","把模型")
    if not any(t in utterance for t in triggers):
        return None
    if not native.bound or native.projector.turn_id is not None:
        return "官方会话暂不可操作；模型没有改变。"
    try:
        discovered=native.adapter.models()
        models=discovered["models"]
        command=parse_model_command(utterance,models)
        if command is None:
            return None
        if command["type"]!="model_switch":
            return command.get("message","模型尚未确认，当前会话没有改变。")
        intended=command["model"]
        before=native.adapter.inspect(native.tab_id)
        if not before.get("ok") or before.get("session_id")!=native.projector.session_id:
            return "官方会话已变化，模型没有改变，请先重新连接。"
        old=(before.get("selected") or {}).get("model")
        if intended==old:
            return "当前对话已经是 "+intended+"，不需要重复切换。"
        effective=native.adapter.switch(native.tab_id,intended)
        after=native.adapter.inspect(native.tab_id)
        if (effective!=intended or not after.get("ok")
            or after.get("session_id")!=native.projector.session_id
            or (after.get("selected") or {}).get("model")!=intended):
            return "DSH 没有返回一致的模型确认；暂不报告切换成功，请在设置查看当前模型。"
        native.projector.state.update(model_id=intended,model_confirmed=True,
            model_selection_source="dsh_native_session",
            updated_at_unix=native.projector.clock())
        native.projector.record_step("idle","DSH官方会话已确认模型切换至 "+intended)
        native.projector.write()
        output("R68_VOICE_MODEL_SWITCH_VERIFIED target="+intended)
        return "已经由官方 DSH 会话确认，对话模型切换为 "+intended+"。"
    except (RuntimeError,ValueError,KeyError,TypeError) as exc:
        output("R68_VOICE_MODEL_SWITCH_UNVERIFIED error="+type(exc).__name__)
        return "暂时无法确认模型是否切换成功，请看 Mac 上的真实模型状态。"
