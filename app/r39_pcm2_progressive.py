"""R39 opt-in true incremental Qwen3 PCM -> already-verified ESP32 PCM2.

Safety: default production voice remains the proven complete-segment TTS.
Only host-owned serial, only Qwen localhost stream, verified start/ACK/end
with one codec instance, no audio persistence or billable provider calls.
"""
from __future__ import annotations
from queue import Queue, Empty, Full
import math,time
from threading import Event,Thread
from app.r32_streaming_tts_adapter import validated_stream_to_sink
from app.esp_pcm2_stream import PCM2Reply
from app.h11_checked_tts import CheckedTTSError
from app.h10_usb_pcm_player import PCMTransportError
from app.voice_gentle_lift import GentleVoiceLift
from app.r241_pcm_silence_probe import NearSilenceMeter

SENTINEL=object()
def stream_sentence_to_pcm2(text,port,*,source=validated_stream_to_sink,
                            device_factory=PCM2Reply,on_started=None,
                            startup_chunks=3,min_startup_audio_s=4.0,
                            lift_enabled=False,clock=time.monotonic):
    if not isinstance(text,str) or not 1<=len(text.strip())<=150:
        raise CheckedTTSError('TTS_INVALID_TEXT')
    if startup_chunks not in (2,3,4,5):
        raise ValueError('pcm2_startup_chunks_invalid')
    if not 0<=min_startup_audio_s<=12:raise ValueError('invalid_startup_audio_seconds')
    queue=Queue(maxsize=24)
    shutdown=Event()
    result=[None]
    derived={'bytes':0,'peak':0,'clipped_samples':0,'queue_highwater':0,
             'produced_audio_s':0.,'arrival_max_gap_s':0.,'send_max_s':0.}
    previous_arrival=[None];prev_pcm_last=[None];arrival_jumps=[]
    sample_energy=[0];sample_count=[0];first_pcm_at=[None];started=clock()
    # R209: one conservative peak-aware stage, no stacked R207 gain.
    lift=GentleVoiceLift() if lift_enabled else None
    near_silence=NearSilenceMeter()
    def sink(pcm,seq):
        now=clock()
        if previous_arrival[0] is not None:
            derived['arrival_max_gap_s']=max(derived['arrival_max_gap_s'],now-previous_arrival[0])
        previous_arrival[0]=now
        samples=memoryview(pcm).cast('h')
        if first_pcm_at[0] is None:first_pcm_at[0]=now
        sample_energy[0]+=sum(int(v)*int(v) for v in samples)
        near_silence.feed(samples)
        sample_count[0]+=len(samples)
        if samples:
            if prev_pcm_last[0] is not None:
                arrival_jumps.append(abs(int(samples[0])-prev_pcm_last[0]))
            prev_pcm_last[0]=int(samples[-1])
        derived['produced_audio_s']+=len(pcm)/48000
        peak=max((abs(int(n)) for n in samples),default=0)
        clipping=sum(abs(int(n))>=32760 for n in samples)
        derived['bytes']+=len(pcm)
        derived['peak']=max(derived['peak'],peak)
        derived['clipped_samples']+=clipping
        if derived['clipped_samples']>128:
            raise CheckedTTSError('TTS_EXCESSIVE_CLIPPING')
        while not shutdown.is_set():
            try:
                queue.put(('audio',lift.process(pcm) if lift is not None else pcm),timeout=.2)
                derived['queue_highwater']=max(derived['queue_highwater'],queue.qsize())
                return
            except Full:pass
        raise CheckedTTSError('TTS_STREAM_CANCELLED')
    def producer():
        try:
            receipt=source(text,sink)
            result[0]=receipt
            queue.put(('end',None),timeout=3)
        except Exception as exc:
            # Never claim a partial stream is a complete TTS response.
            try:queue.put(('error',exc),timeout=1)
            except Full:pass
    thread=Thread(target=producer,daemon=True,name='qwen-pcm2-stream')
    thread.start()
    output=None;buffer=[];got_end=False;chunks=0;buffered_s=0.
    try:
        # Admit a bounded amount of verified Qwen PCM BEFORE starting codec.
        while len(buffer)<startup_chunks or (buffered_s<min_startup_audio_s and not got_end):
            try:kind,value=queue.get(timeout=45)
            except Empty:raise CheckedTTSError('TTS_STREAM_STALLED')
            if kind=='error':raise value
            if kind=='end':got_end=True;break
            if kind!='audio':raise CheckedTTSError('TTS_BAD_STREAM_EVENT')
            buffer.append(value);buffered_s+=len(value)/48000
        if not buffer:raise CheckedTTSError('TTS_EMPTY_PCM')
        output=device_factory(port,on_started=on_started)
        output.start()
        codec_started_s=clock()-started
        for block in buffer:
            t=clock();output.send(block);chunks+=1
            derived['send_max_s']=max(derived['send_max_s'],clock()-t)
        while not got_end:
            try:kind,value=queue.get(timeout=45)
            except Empty:raise CheckedTTSError('TTS_STREAM_STALLED')
            if kind=='error':raise value
            if kind=='end':break
            if kind!='audio':raise CheckedTTSError('TTS_BAD_STREAM_EVENT')
            t=clock();output.send(value);chunks+=1
            derived['send_max_s']=max(derived['send_max_s'],clock()-t)
        if result[0] is None or not result[0].completed:
            raise CheckedTTSError('TTS_INCOMPLETE_STREAM')
        physical=output.finish()
        if physical.get('pcm_written') is not True:
            raise PCMTransportError('pcm2_no_board_play_confirmation')
        derived['startup_audio_s']=round(buffered_s,3)
        derived['first_pcm_ready_s']=round(first_pcm_at[0]-started,3) if first_pcm_at[0] else None
        derived['codec_start_s']=round(codec_started_s,3)
        derived['source_rms_pcm16']=round(math.sqrt(sample_energy[0]/max(1,sample_count[0])),1)
        derived['output_bit_exact_source']=lift is None
        derived['single_stage_lift']=lift.metrics() if lift is not None else None
        derived['max_pcm_boundary_jump']=max(arrival_jumps,default=0)
        derived.update(near_silence.result())
        derived['pcm2_ack_max_s']=physical.get('pcm2_ack_max_s')
        derived['pcm2_ack_p95_s']=physical.get('pcm2_ack_p95_s')
        derived['pcm2_ack_over_500ms']=physical.get('pcm2_ack_over_500ms')
        derived={k:round(v,3) if isinstance(v,float) else v for k,v in derived.items()}
        return {'physical':physical,'tts':result[0],'chunks':chunks,
                'audio_telemetry':derived,'live_incremental':True,
                'audio_quality_human_verified':False}
    except BaseException:
        shutdown.set()
        if output is not None:
            output.cancel()
        raise
    finally:shutdown.set()
