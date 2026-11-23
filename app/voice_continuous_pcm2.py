"""One continuous ESP32 PCM2 codec for multiple <=150-char Qwen phrases.

The same preapproved local reference voice is used for every local Qwen request.
No DSH/model resubmission, USB microphone, or disk recording. A failed stream
cancels the physical codec; partial audio is never reported as completed.
"""
from __future__ import annotations

import math,time
from queue import Queue, Full, Empty
from threading import Event, Thread

from app.h11_checked_tts import CheckedTTSError
from app.r32_streaming_tts_adapter import validated_stream_to_sink
from app.esp_pcm2_stream import PCM2Reply
from app.h10_usb_pcm_player import PCMTransportError
from app.voice_gentle_lift import GentleVoiceLift
from app.r256_voice_seam_guard import fade_phrase_head, tail_to_silence

def stream_phrases_to_pcm2(phrases, port, *, source=validated_stream_to_sink,
                           device_factory=PCM2Reply, on_started=None,
                           startup_chunks=4, min_startup_audio_s=6.0,
                           lift_enabled=False, clock=time.monotonic):
    """Sequence local synthesis and send to one physical PCM2 stream.

    Producer begins the next Qwen request as soon as the previous synthesis
    ends, overlapping ongoing ESP32 audio. Consumer does not close/reopen the
    codec between utterances, and consumes all verified PCM in source order.
    """
    if not isinstance(phrases,(list,tuple)) or not 2 <= len(phrases) <= 16:
        raise ValueError('tts_phrases_count_invalid')
    if any(not isinstance(x,str) or not 1<=len(x.strip())<=150 for x in phrases):
        raise CheckedTTSError('TTS_INVALID_TEXT')
    if sum(len(x) for x in phrases)>1800:
        raise CheckedTTSError('TTS_REPLY_TOO_LONG')
    if startup_chunks not in (2,3,4,5,6,7,8):
        raise ValueError('pcm2_startup_chunks_invalid')
    if not 0<=min_startup_audio_s<=16:
        raise ValueError('invalid_startup_audio_seconds')
    # R208: a complete-first-phrase wait added 15-30s of avoidable
    # first-sound latency. Admit the configured audio-seconds buffer only;
    # keep one codec and the existing cancel / hardware ACK requirements.
    # Safe rollback: R208 pre-change backups preserve the old policy.
    first_phrase_prefetch=False
    events=Queue(maxsize=128)
    shutdown=Event()
    receipt={'chunks':0,'voice_segments':len(phrases),'tts_wait_s':[],
             'bytes':0,'audio_quality_human_verified':False,
             'producer_audio_s':0.,'producer_max_gap_s':0.,
             'device_max_send_s':0.,'startup_audio_s':0.}
    started=clock()
    last_producer=[None];prev_last_sample=[None];boundary_jumps=[]
    first_pcm_at=[None];sample_energy=[0];sample_count=[0]
    original_peak=[0];source_clip_count=[0]
    # R256 long-voice ONLY: the user approved current board volume 86, so
    # preserve hardware setting while keeping more digital headroom to avoid
    # repeated hot Qwen phrase peaks being amplified into speaker artifacts.
    lift=GentleVoiceLift(headroom=27500.0,maximum_gain=1.18) if lift_enabled else None
    seam_bridge_ms=[0.0]
    last_output_sample=[None]
    phrase_audio=[];phrase_output_audio=[]
    physical_first_started_at=[None]
    def put(item):
        while not shutdown.is_set():
            try:
                events.put(item,timeout=.2)
                return
            except Full:
                continue
        raise CheckedTTSError('TTS_STREAM_CANCELLED')
    def producer():
        try:
            for i,phrase in enumerate(phrases):
                began=clock()
                def sink(pcm,sequence):
                    if not isinstance(pcm,bytes) or not pcm or len(pcm)%2:
                        raise CheckedTTSError('TTS_PCM_INVALID')
                    now=clock()
                    if last_producer[0] is not None:
                        receipt['producer_max_gap_s']=max(receipt['producer_max_gap_s'],now-last_producer[0])
                    last_producer[0]=now
                    receipt['producer_audio_s']+=len(pcm)/48000
                    points=memoryview(pcm).cast('h')
                    if first_pcm_at[0] is None:first_pcm_at[0]=now
                    sample_energy[0]+=sum(int(x)*int(x) for x in points)
                    sample_count[0]+=len(points)
                    original_peak[0]=max(original_peak[0],max((abs(int(x)) for x in points),default=0))
                    source_clip_count[0]+=sum(abs(int(x))>=32760 for x in points)
                    if points:
                        if prev_last_sample[0] is not None:
                            boundary_jumps.append(abs(int(points[0])-prev_last_sample[0]))
                        prev_last_sample[0]=int(points[-1])
                    if len(phrase_audio)<=i: phrase_audio.append({'index':i,'energy':0,'samples':0,'peak':0})
                    segment=phrase_audio[i]
                    segment['energy']+=sum(int(x)*int(x) for x in points)
                    segment['samples']+=len(points)
                    segment['peak']=max(segment['peak'],max((abs(int(x)) for x in points),default=0))
                    outgoing=lift.process(pcm) if lift is not None else pcm
                    # Each independent Qwen generation may start at an
                    # arbitrary PCM phase. Give the board a continuous edge;
                    # don't mute or re-generate any verified words.
                    if lift is not None and sequence==1:
                        if last_output_sample[0] is not None:
                            bridge=tail_to_silence(last_output_sample[0])
                            put(('audio',bridge))
                            seam_bridge_ms[0]+=len(bridge)/48.0
                        outgoing=fade_phrase_head(outgoing)
                    if outgoing:
                        last_output_sample[0]=int(memoryview(outgoing).cast('h')[-1])
                    # Per-phrase AFTER-lift metrics show whether the first
                    # phrase remained quiet while later phrases grew louder.
                    if len(phrase_output_audio)<=i:
                        phrase_output_audio.append({'index':i,'energy':0,'samples':0,'peak':0})
                    out_points=memoryview(outgoing).cast('h')
                    after=phrase_output_audio[i]
                    after['energy']+=sum(int(x)*int(x) for x in out_points)
                    after['samples']+=len(out_points)
                    after['peak']=max(after['peak'],max((abs(int(x)) for x in out_points),default=0))
                    put(('audio',outgoing))
                tts=source(phrase,sink)
                if tts.completed is not True:
                    raise CheckedTTSError('TTS_INCOMPLETE_STREAM')
                put(('segment',{'index':i,'duration':round(clock()-began,3),
                                'first':tts.first_audio_s}))
            if lift is not None and last_output_sample[0] is not None:
                fade=tail_to_silence(last_output_sample[0])
                put(('audio',fade))
                seam_bridge_ms[0]+=len(fade)/48.0
            put(('end',None))
        except Exception as exc:
            # Never present a partially synthesized reply as completed.
            try: put(('error',exc))
            except CheckedTTSError:pass
    worker=Thread(target=producer,daemon=True,name='qwen-voice-continuous')
    worker.start()
    output=None
    buffered=[]
    prebuffer_completed=False
    first_phrase_complete=False
    buffered_s=0.
    try:
        while ((len(buffered)<startup_chunks or
                (buffered_s<min_startup_audio_s and not prebuffer_completed))
               or (first_phrase_prefetch and not first_phrase_complete and not prebuffer_completed)):
            try: kind,item=events.get(timeout=45)
            except Empty: raise CheckedTTSError('TTS_STREAM_STALLED')
            if kind=='error':raise item
            if kind=='end':
                prebuffer_completed=True
                break
            if kind=='segment':
                receipt['tts_wait_s'].append(item)
                if item['index']==0:first_phrase_complete=True
                continue
            if kind!='audio':raise CheckedTTSError('TTS_BAD_STREAM_EVENT')
            buffered.append(item);buffered_s+=len(item)/48000
        if not buffered:raise CheckedTTSError('TTS_EMPTY_PCM')
        def track_physical_start(is_started):
            if is_started and physical_first_started_at[0] is None:
                physical_first_started_at[0]=clock()
            if on_started is not None:on_started(is_started)
        output=device_factory(port,on_started=track_physical_start)
        output.start()
        codec_started_s=clock()-started
        for part in buffered:
            before_send=clock();output.send(part)
            receipt['device_max_send_s']=max(receipt['device_max_send_s'],clock()-before_send)
            receipt['bytes']+=len(part);receipt['chunks']+=1
        done=prebuffer_completed
        while not done:
            try:kind,item=events.get(timeout=45)
            except Empty:raise CheckedTTSError('TTS_STREAM_STALLED')
            if kind=='error':raise item
            if kind=='end':done=True;continue
            if kind=='segment':
                receipt['tts_wait_s'].append(item)
                continue
            if kind!='audio':raise CheckedTTSError('TTS_BAD_STREAM_EVENT')
            before_send=clock();output.send(item)
            receipt['device_max_send_s']=max(receipt['device_max_send_s'],clock()-before_send)
            receipt['bytes']+=len(item);receipt['chunks']+=1
        if len(receipt['tts_wait_s'])!=len(phrases):
            raise CheckedTTSError('TTS_MISSING_SEGMENT')
        physical=output.finish()
        if physical.get('pcm_written') is not True:
            raise PCMTransportError('pcm2_no_board_play_confirmation')
        receipt.update(startup_audio_s=round(buffered_s,3),
                       first_phrase_prefetched=first_phrase_complete,
                       first_pcm_ready_s=round(first_pcm_at[0]-started,3) if first_pcm_at[0] else None,
                       codec_start_s=round(codec_started_s,3),
                       physical_first_started_s=(round(physical_first_started_at[0]-started,3)
                           if physical_first_started_at[0] is not None else None),
                       source_peak_pcm16=original_peak[0],
                       source_rms_pcm16=round(math.sqrt(sample_energy[0]/max(1,sample_count[0])),1),
                       source_clipped_samples=source_clip_count[0],
                       output_bit_exact_source=lift is None,
                       single_stage_lift=lift.metrics() if lift is not None else None,
                       phrase_source_metrics=[{'index':p['index'],
                         'peak':p['peak'],
                         'rms':round(math.sqrt(p['energy']/max(1,p['samples'])),1)} for p in phrase_audio],
                       phrase_output_metrics=[{'index':p['index'],'peak':p['peak'],
                         'rms':round(math.sqrt(p['energy']/max(1,p['samples'])),1)}
                         for p in phrase_output_audio],
                       max_pcm_boundary_jump=max(boundary_jumps,default=0),
                       producer_audio_s=round(receipt['producer_audio_s'],3),
                       producer_max_gap_s=round(receipt['producer_max_gap_s'],3),
                       device_max_send_s=round(receipt['device_max_send_s'],3),
                       physical=physical,elapsed_s=round(clock()-started,3),
                       continuous_codec=True,
                       r256_edge_bridge_ms=round(seam_bridge_ms[0],2),
                       r256_long_lift_headroom=27500 if lift is not None else None)
        return receipt
    except BaseException:
        shutdown.set()
        if output is not None:
            output.cancel()
        raise
    finally:
        shutdown.set()
