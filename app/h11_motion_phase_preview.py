"""Mac-only, provisional selected35 motions based on verified voice phases.

The 35 animations are user-selected, but phase/cue pairing awaits visual
acceptance. Never claim ESP32 rendered the animation or a DSH tool succeeded.
"""
from __future__ import annotations

from app.selected_motion_director import MotionPlanError

CUES={
    'listening': '点击回应-元气挥手',
    'transcribing': '工作状态-忙碌点按',
    'thinking': '工作状态-忙碌点按',
    'tool_pending': '工作状态-忙碌点按',
    'voice_generating': '工作状态-忙碌点按',
    'speaking': '碎碎念-对屏碎碎念',
    'error': '工作状态-垂头叹气冒汗',
}

def apply_verified_device_phase(native,phase:str,*,source:str):
    if source not in ('esp32_pcm_begin','esp32_pcm_complete','verified_esp32_transcript',
                      'verified_native_answer','verified_tts_audio_ready','verified_esp32_speaker_start',
                      'verified_esp32_speaker_end','verified_voice_error'):
        raise MotionPlanError('physical_or_native_receipt_required')
    if phase not in ('idle',*CUES):
        raise MotionPlanError('unmapped_voice_phase')
    director=native.director
    director.on_state(phase,native.clock(),verified=True)
    name=CUES.get(phase,director.current)
    if name not in native.mapping:
        raise MotionPlanError('cue_not_in_user_selected35')
    director.current=name
    entry=native.mapping[name]
    native.projector.state.update(animation=name,animation_id=entry['id'],
        animation_role=entry['decision'],animation_source='user_selected35',
        animation_preview_status='mac_only_needs_user_acceptance')
    native.projector.write()
    return {'animation_id':entry['id'],'mac_only_preview':True}
