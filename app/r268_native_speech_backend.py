"""R268 transport-independent use of the EXISTING official DSH and D10 Qwen voice.

Instantiated only by an exclusive, authenticated LAN voice owner. Tests inject
a fake backend; importing this module starts no port, microphone, model or API.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
import time

MAX_REPLY_PCM = 180 * 24000 * 2

@dataclass(frozen=True)
class SpeechReply:
    pcm: bytes
    answer_origin: str
    voice_profile_id: str = "dafeiyu-qwen3-d10"
    spoken_text_length: int = 0
    buffered: bool = False

class NativeSpeechBackend:
    """Own one *already bound* NativeDshCompanionSession; never create a second Agent."""
    origin = "official_dsh_verified"
    # Only this bound backend can produce these independently validated
    # *local* weather responses; the WSS gate must check this allowlist.
    verified_local_origins = frozenset((
        "verified_open_meteo_weather", "local_weather_source_unavailable",
        "verified_mac_local_datetime"))
    def __init__(self, native, progress=None):
        if not getattr(native, "bound", False):
            raise ValueError("official_dsh_session_not_verified")
        self.native = native
        self._progress = progress

    def set_progress(self, callback):
        self._progress = callback if callable(callback) else None

    def _mark(self, stage: str, **metrics):
        try:
            if self._progress is not None:
                self._progress(stage, **metrics)
        except Exception:
            # No diagnostics failure may interrupt the real voice request.
            pass

    def _early_tts_permitted(self,on_pcm)->bool:
        # An unbound/fake backend, USB, legacy WSS or an unverified APP
        # must continue to use the complete-phrase original path.
        if on_pcm is None:return False
        from app.native_dsh_companion_session import NativeDshCompanionSession
        if type(self.native) is not NativeDshCompanionSession:return False
        from app.r509_incremental_gate import enabled
        return enabled()

    def process_stream(self, pcm16: bytes, *, origin: str, turn_id: str,
                       on_pcm, on_origin=None,on_voice_profile=None,
                       allow_verified_local_origin:bool=True,
                       cancel_requested=None) -> SpeechReply:
        """Publish validated Qwen D10 PCM after each phrase, before final PCM exists.

        The authenticated WSS gate alone may use this callback. Failure in
        the consumer fails the turn; no truncated audio is a completed reply.
        """
        if not callable(on_pcm):
            raise ValueError("incremental_pcm_sink_required")
        return self.process(pcm16,origin=origin,turn_id=turn_id,
                            on_pcm=on_pcm,on_origin=on_origin,
                            on_voice_profile=on_voice_profile,
                            allow_verified_local_origin=allow_verified_local_origin,
                            cancel_requested=cancel_requested)

    def process(self, pcm16: bytes, *, origin: str, turn_id: str,
                on_pcm=None, on_origin=None,on_voice_profile=None,
                allow_verified_local_origin:bool=True,
                cancel_requested=None) -> SpeechReply:
        # Turn IDs, authorization, source and PCM shape are verified by LAN gate.
        from app.esp_mic_quality import normalize_for_asr
        from app.stt_local import transcribe_bytes,NoSpeechDetected
        from app.r237_wake_speech_gate import wake_capture_block,wake_transcript_block
        from app.r38_memory_retrieval import safe_context
        from app.r252_stable_voice_phrases import stable_voice_plan
        from app.r336_wifi_voice_plan import wifi_voice_phrases
        from app.r336_wifi_weather import wifi_weather_reply
        from app.r458_voice_text import voice_ready_reply
        from app.r458_verified_clock import local_datetime_reply
        from app.r458_stable_pcm import TurnLevelMatcher,TurnWideLoudnessLift
        from app.h11_checked_tts import synthesize as checked_tts
        from app.r441_pcm_quality import summary,compress_excess_silence
        from scripts.r14_h8_voice_trial import audio_wav,PRIVATE_ROOT

        # Only a trusted, incremental Wi-Fi session may play verified DSH
        # progress before the final reply. USB/legacy/fake stay unchanged.
        from app.r517_pinky_voice_contract import is_phone_task
        phone_progress=False
        computer_progress=False
        tool_progress=False
        progress_chunks=[]
        progress_segments=[]
        progress_error=[]
        progress_announced=[]
        phone_progress_level=None
        progress_tts_failed=False
        phone_progress_started_at=None
        phone_progress_last_at=None
        progress_voice_endpoint=None
        def verified_phone_progress(stage):
            nonlocal phone_progress_level,progress_tts_failed,phone_progress_last_at,progress_voice_endpoint
            if (not tool_progress or stage in progress_announced or
                progress_error or progress_tts_failed):
                return
            if computer_progress and not phone_progress:
                # Computer narration never claims progress from model text
                # or an intent guess. A native CUA event is mandatory.
                if (stage not in ("cua_running","cua_waiting_permission",
                                  "approval_pending","still_working","still_working_later") and
                    not (stage.startswith("cua_step_") and stage[9:].isdigit() and
                         1<=int(stage[9:])<=32)):
                    return
            # R541 fixes the 6-second skip of a one-shot tool-running event.
            # Only real tool stages are spoken; human approval is never fake.
            if stage=="submitted":return
            now=time.monotonic()
            # Fast phone tasks (under 6s) must not emit 4s narration for a
            # 1s tool call. The one-shot early callback was previously LOST
            # forever; OfficialVisualObserver.tick() re-offers the latest
            # verified tool stage after 6s if the same task is still active.
            # R679: fast Mac tasks go straight to their verified result.
            # The Mac projector still records EVERY actual native step.
            # Speak progress only after ten seconds and at most twice;
            # explicit human approval remains immediate.
            if computer_progress and not phone_progress:
                from app.r675_computer_progress import computer_voice_progress_permitted
                elapsed=(now-phone_progress_started_at
                         if phone_progress_started_at is not None else 0.0)
                since=(now-phone_progress_last_at
                       if phone_progress_last_at is not None else None)
                if not computer_voice_progress_permitted(
                        stage,elapsed_s=elapsed,since_last_s=since,
                        announced=len(progress_announced)):
                    return
            else:
                if (stage!="approval_pending" and
                    (phone_progress_started_at is None or
                     now-phone_progress_started_at<6.0)):
                    return
                if (phone_progress_last_at is not None and
                    now-phone_progress_last_at<4.0 and
                    stage!="approval_pending"):
                    return
                if len(progress_announced)>=6 and stage!="approval_pending":
                    return
            lines={
                "connecting_phone":"本鱼正在连接手机。",
                "opening_app":"本鱼正在打开应用。",
                "entering_text":"本鱼正在输入内容。",
                "reading_screen":"本鱼正在查看页面。",
                "navigating_screen":"本鱼正在浏览页面。",
                "delegated_task":"本鱼已交给手机执行，正在等待进展。",
                "releasing_phone":"本鱼正在结束手机操作。",
                "approval_requested":"本鱼正在等待手机授权。",
                "phone_tool_busy":"本鱼正在处理手机操作。",
                "tool_running":"本鱼还在处理，稍等一下。",
                "still_working":"本鱼还在继续处理，先别重复发起任务。",
                "still_working_later":"这次操作时间较长，本鱼仍在等真实结果。",
                "approval_pending":"本鱼在等你确认授权。",
                "cua_running":"本鱼正在通过原生工具查看 Mac 电脑。",
                "cua_waiting_permission":"电脑操作需要你的授权，请在 Mac 界面确认。",
            }
            text=lines.get(stage)
            if computer_progress and not phone_progress:
                # The numbered steps remain in the UI timeline, never in
                # final speech, even if the last native step is very fast.
                if stage.startswith("cua_step_") and stage[9:].isdigit():
                    text="电脑操作还在进行，核实完我会告诉你结果。"
                elif stage in ("cua_running","still_working"):
                    text="本鱼还在查看电脑，核实完再汇报结果。"
                elif stage=="still_working_later":
                    text="电脑任务耗时较长，仍在等待真实结果。"
            if not text:return
            try:
                from app.h11_checked_tts import synthesize
                from app.r511_live_tts_pcm import EarlyTurnPCM
                from app.r441_pcm_quality import summary
                if phone_progress_level is None:
                    phone_progress_level=EarlyTurnPCM()
                projector=getattr(self.native,"projector",None)
                if projector is not None and hasattr(projector,"publish_spoken_progress"):
                    try:
                        projector.publish_spoken_progress(text)
                        projector.write()
                    except Exception as exc:
                        self._mark("r518_phone_progress_skipped",error_kind=type(exc).__name__)
                        return
                # Full local TTS before emitting avoids half-published
                # progress if synthesis fails. R576 uses the same R503
                # speaker for Pinky status and final speech when available.
                # Once progress has been emitted, pin its voice for this turn.
                from app.r576_r503_all_voice_policy import (
                    choose_progress,profile_name)
                from app.r505_long_voice_trial import BASELINE
                try:
                    endpoint=(progress_voice_endpoint if progress_voice_endpoint
                              else choose_progress(text))
                    result=(synthesize(text,endpoint=endpoint) if endpoint!=BASELINE
                            else synthesize(text))
                    pcm=phone_progress_level.process(result.pcm,
                         phrase_index=len(progress_announced)+1,
                         candidate=endpoint!=BASELINE)
                    if len(pcm)>MAX_REPLY_PCM//4:
                        raise ValueError("phone_progress_pcm_too_long")
                except Exception as exc:
                    progress_tts_failed=True
                    self._mark("r518_phone_progress_skipped",error_kind=type(exc).__name__)
                    return
                progress_voice_endpoint=endpoint
                if on_origin is not None and not progress_announced:
                    on_origin(self.origin)
                if on_voice_profile is not None and not progress_announced:
                    on_voice_profile(profile_name(endpoint))
                self._mark("r576_phone_progress_voice",
                           r503=int(endpoint!=BASELINE))
                for at in range(0,len(pcm),30720):
                    part=pcm[at:at+30720]
                    on_pcm(part)  # Failed downstream publication must fail turn.
                    progress_chunks.append(part)
                progress_segments.append({"text":text,"audio_ms":summary(pcm).duration_ms})
                progress_announced.append(stage)
                phone_progress_last_at=time.monotonic()
                # R676: native CUA steps are dynamic verified codes, not
                # keys in the static Pinky narration dictionary. Never turn
                # a completed PCM emission into an artificial error.
                progress_code=(100+int(stage[9:]) if
                               stage.startswith("cua_step_") and
                               stage[9:].isdigit() else
                               list(lines).index(stage)+1)
                self._mark("r518_verified_phone_progress",
                           progress_code=progress_code,pcm_bytes=len(pcm))
            except Exception as exc:
                progress_error.append(exc)
                self._mark("r518_phone_progress_failed",error_kind=type(exc).__name__)
        if origin not in ("wake","touch"):
            raise ValueError("untrusted_microphone_origin")
        if not isinstance(pcm16,bytes) or len(pcm16)%2 or not 16000<=len(pcm16)<=20*16000*2:
            raise ValueError("invalid_board_pcm")
        if wake_capture_block(len(pcm16)/32000,origin):
            raise ValueError("wake_audio_too_short")
        self._mark("backend_started", input_pcm_bytes=len(pcm16))
        asr_start = time.monotonic()
        normalized,normalization = normalize_for_asr(pcm16)
        from app.esp_mic_quality import pcm_level
        levels = pcm_level(pcm16)
        # Numeric-only microphone evidence: no audio or recognized words in receipts.
        self._mark("mic_quality", rms_dbfs_tenths=int(round((levels["rms_dbfs"]+100)*10)),
                   peak_permille=int(round(levels["peak_percent"]*10)),
                   clipped_ppm=int(round(levels["clipped_percent"]*10000)),
                   gain_applied=int(bool(normalization["applied"])),
                   gain_hundredths=int(round(normalization["gain"]*100)))
        result=transcribe_bytes(audio_wav(normalized),"audio/wav",
                               PRIVATE_ROOT/"stt-tmp",require_vad=origin=="wake")
        transcript=result.get("text","").strip()
        if not transcript or wake_transcript_block(transcript,origin):
            if origin=="wake":
                raise NoSpeechDetected("no_speech_or_prompt_echo")
            raise ValueError("unverified_or_empty_speech")
        if len(transcript)>600:
            raise ValueError("unverified_or_oversized_speech")
        timing = {key: result[key] for key in ("asr_decode_ms", "asr_whisper_ms")
                  if type(result.get(key)) is int}
        # R541: the user needs to distinguish Whisper raw wording from our
        # post-ASR known-term correction. Log ONLY bounded counters/booleans,
        # never the mic audio, raw text or product names.
        edits=result.get("asr_context_corrections")
        if isinstance(edits,(tuple,list)):
            self._mark("r541_asr_context_correction",
                correction_count=min(16,len(edits)),
                corrected_observed_app_term=int(
                    "taobao_shangou_real_asr_homophone" in edits))
        self._mark("asr_done", asr_ms=int((time.monotonic()-asr_start)*1000), **timing)
        early_progress=self._early_tts_permitted(on_pcm)
        phone_progress=(is_phone_task(transcript) and early_progress)
        from app.r675_computer_progress import explicit_mac_action
        computer_progress=(not phone_progress and early_progress and
                           explicit_mac_action(transcript))
        tool_progress=(phone_progress or computer_progress)
        # Private diagnostic counters only; never log the ASR sentence.
        self._mark("r676_computer_voice_gate",
                   is_computer_request=int(explicit_mac_action(transcript)),
                   early_pcm=int(early_progress),
                   progress_enabled=int(computer_progress))
        # R461 capability negotiation: physical R441 only understands
        # official_dsh_verified on the device, so route locally ONLY after
        # a newly flashed board explicitly advertises local-source support.
        verified_clock=(local_datetime_reply(transcript)
                        if allow_verified_local_origin else None)
        if verified_clock is not None:
            reply=verified_clock.text
            reply_origin=verified_clock.origin
            self._mark("r458_local_clock_verified",clock_source=1)
            projector=getattr(self.native,"projector",None)
            if projector is not None and hasattr(projector,"clock_result"):
                projector.clock_result(reply,same_session=True,verified=True,transcript=transcript)
                projector.write()
        else:
            # R305: WSS has authenticated the physical mic and local STT is now
            # verified. The prior USB pipeline recorded safe memories here, but
            # the Wi-Fi path used to skip this step and DSH could say "记住了"
            # without a Mac vault write. Never learn from the DSH response.
            from app.r305_wifi_memory_review import apply_verified_wifi_memory
            memory_receipt=apply_verified_wifi_memory(transcript,verified_stt=True)
            if memory_receipt.status not in ("none","unverified"):
                self._mark("r305_voice_memory_status",
                           status=memory_receipt.status,
                           category=memory_receipt.category or "")
            context=safe_context(transcript)
            from app.r517_pinky_voice_contract import tool_context
            phone_context=tool_context(transcript)
            if phone_context:
                context=(context+"\n"+phone_context).strip()
                self._mark("r517_pinky_voice_contract",requested=1)
            if memory_receipt.hint:
                # Dedicate bounded space to an authenticated task instruction.
                # Do not duplicate the phone instruction and silently exceed
                # NativeDshCompanionSession's 900-character context budget.
                hint=memory_receipt.hint
                if phone_context:
                    base=context[:-len(phone_context)-1] if context.endswith("\n"+phone_context) else ""
                    base=base[:max(0,890-len(hint)-len(phone_context)-2)].rstrip()
                    context=(base+"\n"+hint+"\n"+phone_context).strip()
                else:
                    context=(context[:max(0,890-len(hint)-1)].rstrip()+"\n"+hint).strip()
            local_weather=(wifi_weather_reply(transcript)
                           if allow_verified_local_origin else None)
            if local_weather is not None:
                # Real checked local source; do not ask DSH to guess from a web
                # link or fabricate rain/temperature. The WSS origin is distinct
                # from official DSH output, including the unavailable case.
                reply=local_weather.text
                reply_origin=local_weather.source
                self._mark("r336_verified_weather_source",
                           available=int(local_weather.available),location="configured_local")
                projector=getattr(self.native,"projector",None)
                if projector is not None and hasattr(projector,"weather_result"):
                    projector.weather_result(reply,same_session=True,verified=True,
                                             available=local_weather.available)
            else:
                self._mark("dsh_started")
                dsh_start = time.monotonic()
                phone_progress_started_at=dsh_start
                # Official observer reports a *verified submitted task* and
                # optionally an actual approval-pending fact. Never invent
                # tool execution progress or launch a second DSH task.
                if tool_progress:
                    response=self.native.chat_once(
                        transcript,memory_context=context,
                        on_verified_progress=verified_phone_progress)
                else:
                    response=(self.native.chat_once(transcript,memory_context=context)
                              if context else self.native.chat_once(transcript))
                if progress_error:
                    raise progress_error[0]
                reply=response["reply"]
                reply_origin=self.origin
                self._mark("dsh_answer_ready",
                           dsh_ms=int((time.monotonic()-dsh_start)*1000),
                           reply_chars=len(reply) if isinstance(reply,str) else 0)
        # R484: use the already user-enabled, text-only isolated Flash
        # speech summarizer for VERIFIED long Wi-Fi DSH replies. This is
        # separate from T1 and the official answer remains in Mac history.
        # If the scoped summary is unavailable, use factual coverage across
        # the entire source, never its opening 320 characters alone.
        from app.r484_wifi_spoken_summary import spoken_source_for_wifi
        from app.r517_pinky_voice_contract import preserve_task_report
        phone_report=preserve_task_report(reply,transcript) and reply_origin==self.origin
        procedure=None
        file_brief=None
        from app.r517_pinky_voice_contract import (
            verified_phone_speech,is_front_app_query,is_phone_screen_query)
        if phone_report:
            # `completed` alone can prove another tool ran, not Pinky. Only
            # a native successful Pinky MCP receipt authorizes saying the
            # requested phone operation is finished.
            verified_pinky=(isinstance(response,dict) and
                            response.get("pinky_tool_execution_verified") is True)
            readonly_query=(isinstance(response,dict) and
                            response.get("pinky_readonly_query_verified") is True)
            front_observed=(isinstance(response,dict) and
                            response.get("pinky_front_app_observed") is True)
            screen_observed=(front_observed or
                             (isinstance(response,dict) and
                              response.get("pinky_screen_observed") is True))
            speech_source=verified_phone_speech(
                reply,pinky_tool_verified=verified_pinky,
                readonly_query_verified=readonly_query,
                front_app_observed=front_observed,
                screen_observed=screen_observed,
                task_stage=(response.get("pinky_tool_stage") if
                            isinstance(response,dict) else None),
                delegation_state=(response.get("pinky_delegation_state") if
                                  isinstance(response,dict) else None),
                confirmed_launch_app=(response.get("pinky_confirmed_launch_app") if
                                      isinstance(response,dict) else None),
                confirmed_unsent_draft=(response.get("pinky_confirmed_unsent_draft") is True if
                                        isinstance(response,dict) else False),
                direct_actions_finalized=(
                    response.get("pinky_direct_actions_finalized") is True
                    if isinstance(response,dict) else False),
                readonly_search_recovered=(isinstance(response,dict) and
                    response.get("pinky_readonly_search_recovered") is True),
                readonly_search_completed=(isinstance(response,dict) and
                    response.get("pinky_readonly_search_completed") is True),
                transcript=transcript,
                action=(response.get("action") if
                        isinstance(response,dict) and response.get("action") else
                        "foreground_not_observed" if
                        is_front_app_query(transcript) and not front_observed
                        else "screen_not_observed" if
                        is_phone_screen_query(transcript) and not screen_observed
                        else None))
            # R620: non-sensitive four-gate trace for post-acceptance
            # debugging. Never store the user utterance, phone text or
            # destination, and never let diagnostics affect the reply.
            from app.r517_pinky_voice_contract import (
                is_unsent_draft_request,official_reply_confirms_unsent_draft)
            self._mark("r620_pinky_unsent_evidence",
                       intent=int(is_unsent_draft_request(transcript)),
                       native_receipt=int(
                           isinstance(response,dict) and
                           response.get("pinky_confirmed_unsent_draft") is True),
                       official_text=int(official_reply_confirms_unsent_draft(reply)),
                       tool_verified=int(verified_pinky))
            self._mark("r626_pinky_generic_finalization",
                       native_done=int(isinstance(response,dict) and
                           response.get("pinky_direct_actions_finalized") is True),
                       tool_verified=int(verified_pinky),
                       task_stage=(response.get("pinky_tool_stage")
                           if isinstance(response,dict) else "none"))
            self._mark("r540_pinky_foreground_observed",verified=int(front_observed))
            self._mark("r538_pinky_readonly_query",verified=int(readonly_query))
            self._mark("r519_pinky_verified_receipt_gate",verified=int(verified_pinky))
        else:
            # R680: a full 12-step verified how-to cannot be compressed to
            # three random facts or a 180-char model overview. For explicitly
            # requested procedures, first compile ALL source-backed steps
            # locally; no second DSH/Flash call or extra model cost.
            from app.r680_procedural_voice import compile_procedure
            procedure=(compile_procedure(reply,transcript)
                       if reply_origin==self.origin and not computer_progress
                       else None)
            if procedure is None and reply_origin==self.origin and not computer_progress:
                # R681: Markdown guides commonly restart their numbering at
                # the next heading; R680's flat 1..N parser rejected the
                # entire espresso guide and silently fell back to random
                # distant sentences. Accept complete numbering PER section.
                from app.r681_structured_briefing import compile_hierarchical_procedure
                procedure=compile_hierarchical_procedure(reply,transcript)
            if procedure is None and reply_origin==self.origin:
                # R681: a verified file metadata answer should speak size,
                # date, and observed location; never pick a rejected,
                # self-corrected path as a random mid-document fact.
                from app.r681_structured_briefing import file_facts_voice
                file_brief=file_facts_voice(reply)
            if file_brief is not None:
                speech_source=file_brief.text
                self._mark("r681_file_facts_source",
                           original_chars=file_brief.source_chars,
                           spoken_chars=len(file_brief.text))
            elif procedure is not None:
                speech_source=procedure.text
                self._mark("r680_procedural_source",
                           original_chars=procedure.source_chars,
                           spoken_chars=len(procedure.text),
                           steps=procedure.steps,sections=procedure.sections)
            else:
                speech_source=spoken_source_for_wifi(
                    reply,transcript,origin=reply_origin,native=self.native,mark=self._mark)
        # A phone task's verified result must not be silently truncated to
        # the generic 320-character speech digest (which can drop approval,
        # partial-completion and failure details). The official DSH is asked
        # to keep it brief; preserve the actual words it returns.
        if phone_report:
            from app.voice_spoken_text import prepare_spoken_text
            # Preserve numeric ranges in native Pinky listings. The global
            # Markdown normalizer also strips ~ markup; 1~2 must not read 12.
            import re
            voice_source=re.sub(r"(?<=\d)\s*[~～]\s*(?=\d)",
                                "到",speech_source)
            spoken=prepare_spoken_text(voice_source)
            voice_brief=False
            if not spoken.strip() or len(spoken)>1800:
                # Keep the normal bounded fallback rather than inventing a
                # completed task or feeding unlimited text into the codec.
                spoken,voice_brief=voice_ready_reply(speech_source)
            self._mark("r517_pinky_spoken_receipt",preserved=int(not voice_brief),
                       chars=len(spoken))
        elif procedure is not None or file_brief is not None:
            from app.voice_spoken_text import prepare_spoken_text
            spoken=prepare_spoken_text(speech_source)
            voice_brief=True
        else:
            spoken,voice_brief=voice_ready_reply(speech_source)
        if voice_brief or speech_source!=reply:
            # Keep R304 evidence contract used by existing WSS receipts.
            self._mark("r304_spoken_brief_selected",
                       original_chars=len(reply),spoken_chars=len(spoken),
                       complete_mac_reply=1)
            self._mark("r484_spoken_brief_selected",
                       original_chars=len(reply),spoken_chars=len(spoken),
                       source="scoped_summary" if speech_source!=reply else "local_coverage",
                       complete_mac_reply=1)
        if not spoken.strip():
            raise ValueError("empty_dsh_speech")
        # R532: markdown headlines and merged bullets may produce "：；".
        # Clean only punctuation, without altering any source-backed claims.
        from app.r532_buffered_voice_pacing import natural_spoken_punctuation
        spoken=natural_spoken_punctuation(spoken)
        # R529: compile source-grounded oral scripts for *different* DSH
        # answer forms (explanation, ordered steps, factual enumeration).
        # This is a no-cost deterministic fallback after any user-enabled
        # speech-only Flash summary. It does not mutate the official DSH answer.
        compiled_long=procedure is not None or file_brief is not None
        if (not compiled_long and not phone_report and
                reply_origin=="official_dsh_verified" and len(reply)>=180):
            from app.r529_long_speech_script import compile_verified_source
            candidate=compile_verified_source(
                speech_source,spoken,model_compacted=(speech_source!=reply))
            if candidate is not None:
                spoken=natural_spoken_punctuation(candidate.text)
                compiled_long=True
                self._mark("r529_oral_script_compiled",
                           original_chars=candidate.source_chars,
                           spoken_chars=len(spoken),
                           items=candidate.factual_items)
        # R679: native Mac path and CLI literals belong in the full Mac
        # result text. A voice-only, deterministic rendering avoids asking
        # Qwen to recite raw usernames and slash-delimited mixed tokens.
        if reply_origin==self.origin and not phone_report:
            from app.r679_mac_technical_speech import (
                oral_mac_technical_text,contains_native_path)
            if computer_progress or contains_native_path(reply):
                # Final path pronunciation is a universal *answer*
                # concern. Do not condition it on a "Cua progressing"
                # intent regex that excludes natural "desktop ..." queries.
                spoken,adapt=oral_mac_technical_text(spoken,reply)
                self._mark("r679_mac_technical_voice",
                       path_count=adapt["file_paths"],
                       command_count=adapt["terminal_commands"],
                       filename_count=adapt["filenames"])
        # R680: protect native dates/units/ranges from mixed-language Qwen
        # reading; only alter TTS input after the verified final answer and
        # original Mac transcript are already sealed.
        if reply_origin==self.origin and not phone_report:
            from app.r680_technical_speech import normalize_technical_speech
            spoken,pronunciation=normalize_technical_speech(spoken)
            self._mark("r680_technical_numbers",
                       dates=pronunciation["datetime"],
                       sizes=pronunciation["bytes"],
                       units=pronunciation["units"],
                       ranges=pronunciation["ranges"])
        final_spoken=spoken
        # R458 Wi-Fi: first phrase <=110 chars preserves first-sound timing,
        # later phrases <=145 chars reduce independent Qwen clone restarts.
        # R252 USB voice path and model/reference identity stay unchanged.
        phrases=wifi_voice_phrases(spoken)
        if on_origin is not None and not progress_announced:
            on_origin(reply_origin)  # Before first streamed PCM/audio_offer.
        from app.r505_long_voice_trial import BASELINE
        from app.r576_r503_all_voice_policy import (
            choose as choose_voice,profile_name,enabled as all_r503_enabled)
        # R576: the user accepted R503 for short AND long Chinese Wi-Fi
        # speech, including Pinky. A progress fragment already emitted must
        # pin the same voice throughout this specific physical turn.
        endpoint=(progress_voice_endpoint if progress_voice_endpoint else
                  choose_voice(origin=reply_origin,spoken=spoken,
                               source_chars=len(reply),
                               summarized_long=compiled_long,
                               phone_report=phone_report))
        profile=profile_name(endpoint)
        if on_voice_profile is not None and not progress_announced:
            on_voice_profile(profile)  # Before any first PCM/audio offer.
        self._mark("r505_voice_trial_selected",
                   long_trial=int(endpoint!=BASELINE),
                   total_chars=len(spoken))
        self._mark("r576_r503_voice_selected",
                   all_mandarin=int(all_r503_enabled()),
                   r503=int(endpoint!=BASELINE),
                   phone_report=int(phone_report),
                   progress_voice_pinned=int(progress_voice_endpoint is not None))
        # R503 phrases are independently generated. R524 buffers every phrase,
        # so their complete PCM can use one fixed gain per phrase before any
        # frame reaches the board; never chase transport chunks.
        candidate_r503=(endpoint!=BASELINE)
        topic_gap=0
        if candidate_r503 and on_pcm is not None:
            from app.r336_wifi_voice_plan import wifi_buffered_r503_phrases
            previous_count=len(phrases)
            # After a safe fact-preserving summary, avoid another independent
            # clone restart for the ~80-130 char one-piece spoken overview.
            # An already approved Flash summary or exact source-grounded
            # local list is also a short oral script. Do not re-fragment its
            # natural punctuation using the original 66-char streaming plan.
            oral_ready=((compiled_long and len(spoken)<=210) or
                        (speech_source!=reply and len(reply)>320 and
                         65<=len(spoken)<=210))
            if oral_ready:
                from app.r336_wifi_voice_plan import wifi_oral_script_phrases
                phrases=wifi_oral_script_phrases(
                    spoken,source_text=speech_source if compiled_long else None)
                if len(phrases)==2 and compiled_long:
                    from app.r537_semantic_tts_boundaries import (
                        source_discontinuity,normalized_source)
                    topic_gap=source_discontinuity(
                        spoken,len(phrases[0]),normalized_source(speech_source))
                    self._mark("r537_semantic_tts_boundary",
                               topic_gap_chars=min(12000,topic_gap),
                               phrase1_chars=len(phrases[0]),
                               phrase2_chars=len(phrases[1]))
            else:
                phrases=wifi_buffered_r503_phrases(spoken,base_phrases=phrases)
            if len(phrases)<previous_count:
                self._mark("r526_buffered_phrase_reduction",
                           old_phrases=previous_count,new_phrases=len(phrases))
        self._mark("tts_plan_ready", phrase_total=len(phrases),
                   previous_r252_phrases=len(stable_voice_plan(spoken).phrases),
                   voice_plan="r526_buffered_r503" if candidate_r503
                   else "wifi_first66_follow145")
        leveler=TurnLevelMatcher(max_gain=1.08 if candidate_r503 else 1.55)
        loudness=TurnWideLoudnessLift()
        # The planned and finalized comparison must describe *all* the PCM
        # in this Wi-Fi turn, including any verified status announcements.
        # Otherwise the final playback binding refuses the length mismatch.
        chunks=list(progress_chunks);total=sum(map(len,progress_chunks))
        phrase_timings=list(progress_segments)
        # R586: exact byte spans for completed, private buffered R503 phrase
        # matching. No partial stream has been sent to the board.
        r503_phrase_spans=[]
        last_pcm_tail_ms=0
        if progress_segments:
            spoken="".join(row["text"] for row in progress_segments)+spoken
        # R511: publish before final TTS; not a playback-complete receipt.
        from app.r499_reply_speech_comparison import save_verified_comparison
        speech_id=getattr(getattr(self.native,"projector",None),"state",{}).get("answer_speech_id")
        if save_verified_comparison(self.native,reply,spoken,reply_origin,
                                    voice_profile_id=profile,
                                    final_spoken_text=(final_spoken if
                                        computer_progress and progress_segments
                                        else None),
                                    tts_generated=False,expected_speech_id=speech_id):
            self._mark("r511_spoken_plan_visible",original_chars=len(reply),
                       spoken_chars=len(spoken))
        # Long synthesis can stall after the board drains its playback ring.
        # Pinky may already have emitted verified progress on the *same*
        # incremental WSS turn. Its final R503 voice must continue through
        # on_pcm, never return a buffered answer after partial frames.
        # For non-phone R503 short/long, preserve full-phrase buffering.
        # R677: the first verified Mac CUA status has ALREADY opened the
        # incremental WSS audio stream. Returning a buffered final answer
        # after that is forbidden by R268LanGateway (and caused the real
        # 2026-11-21 LanGateError:buffered_reply_emitted_early_pcm).
        # Keep the original full-buffer R503 path for ordinary speech that
        # emitted no progress. Once any status PCM was sent, stream ALL final
        # phrases through the same single stream and verified EOS.
        progressive_r503 = (
            os.environ.get("DAFEIYU_R503_PROGRESSIVE_PHRASES") == "1"
            and self._early_tts_permitted(on_pcm)
            and candidate_r503 and not phone_report and not progress_chunks
            and len(phrases) > 1
        )
        buffered = (on_pcm is not None and not phone_report and
                    not progress_chunks and not progressive_r503 and
                    (len(phrases)>1 or candidate_r503 or verified_clock is not None))
        full_phrase_computer=(bool(computer_progress and progress_chunks)
                              and candidate_r503 and not phone_report
                              and on_pcm is not None)
        full_phrase_phone=(bool(phone_report and progress_chunks)
                           and candidate_r503 and on_pcm is not None)
        early_tts=(self._early_tts_permitted(on_pcm) and not buffered
                   and not progressive_r503
                   and not full_phrase_computer and not full_phrase_phone)
        early_level=None
        buffered_level=None
        if early_tts:
            from app.r511_live_tts_pcm import EarlyTurnPCM
            early_level=EarlyTurnPCM(long_answer=len(phrases)>1)
        elif candidate_r503 and (buffered or progressive_r503 or full_phrase_computer
                                 or full_phrase_phone):
            from app.r511_live_tts_pcm import EarlyTurnPCM
            buffered_level=EarlyTurnPCM(long_answer=True)
        self._mark("r679_cua_full_phrase_loudness",
                   enabled=int(full_phrase_computer),
                   prior_progress_frames=int(bool(progress_chunks)))
        self._mark("r687_pinky_full_phrase_loudness",
                   enabled=int(full_phrase_phone),
                   prior_progress_frames=int(bool(progress_chunks)))
        self._mark("r511_tts_early_stream_gate",enabled=int(early_tts))
        for phrase_index, phrase in enumerate(phrases, 1):
            phrase_buffer_start=total
            # Device may time out after 190s even while local TTS is busy.
            # Never start another expensive phrase for an abandoned WSS turn.
            if cancel_requested is not None and cancel_requested():
                raise RuntimeError("voice_cancelled_after_transport")
            self._mark("tts_phrase_started", phrase_index=phrase_index,
                       phrase_total=len(phrases),phrase_chars=len(phrase))
            tts_start = time.monotonic()
            streamed_raw=bytearray()
            streamed_out=bytearray()
            def early_audio(raw_piece:bytes):
                nonlocal total
                if not isinstance(raw_piece,bytes) or not raw_piece or len(raw_piece)%2:
                    raise ValueError("invalid_early_tts_piece")
                streamed_raw.extend(raw_piece)
                rendered=early_level.process(
                    raw_piece,phrase_index=phrase_index,
                    candidate=(candidate_r503 or len(phrases)>1))
                if len(rendered)!=len(raw_piece) or total+len(rendered)>MAX_REPLY_PCM:
                    raise ValueError("tts_reply_exceeds_bound")
                streamed_out.extend(rendered)
                total+=len(rendered)
                # Offer only verified PCM events, with bounded backpressure.
                # The final result is checked against every chunk below.
                for at in range(0,len(rendered),30720):
                    part=rendered[at:at+30720]
                    chunks.append(part)
                    on_pcm(part)
            try:
                if early_tts:
                    result=(checked_tts(phrase,endpoint=endpoint,on_audio=early_audio)
                            if endpoint!=BASELINE else
                            checked_tts(phrase,on_audio=early_audio))
                else:
                    # Unchanged path for legacy WSS, USB and test doubles.
                    result=(checked_tts(phrase,endpoint=endpoint)
                            if endpoint!=BASELINE else checked_tts(phrase))
            except Exception:
                # A dead WSS owner must not trigger a new D10 fallback job
                # when the first R503 call itself fails after disconnection.
                if cancel_requested is not None and cancel_requested():
                    raise RuntimeError("voice_cancelled_after_transport")
                if (endpoint==BASELINE or total>0 or phrase_index!=1 or
                    progress_voice_endpoint is not None):
                    # Once any candidate PCM (including Pinky status) has
                    # been emitted, never switch speaker in this turn.
                    raise
                self._mark("r505_voice_trial_failed_before_audio",
                           fallback_to_d10=1)
                endpoint=BASELINE
                profile=profile_name(endpoint)
                # The candidate failed before publishing PCM: restore the
                # untouched D10 gain path as well as its profile identity.
                candidate_r503=False
                leveler=TurnLevelMatcher()
                loudness=TurnWideLoudnessLift()
                buffered_level=None
                if on_voice_profile is not None:
                    on_voice_profile(profile)  # First phrase failed; no PCM offered.
                result=checked_tts(phrase)
            if cancel_requested is not None and cancel_requested():
                raise RuntimeError("voice_cancelled_after_transport")
            if early_tts and bytes(streamed_raw)!=result.pcm:
                raise ValueError("tts_early_chunk_final_mismatch")
            self._mark("tts_phrase_done", phrase_index=phrase_index,
                       phrase_total=len(phrases),pcm_bytes=len(result.pcm),
                       tts_ms=int((time.monotonic()-tts_start)*1000),
                       tts_first_pcm_ms=max(0,int(getattr(result,"first_pcm_s",0)*1000)),
                       tts_peak=getattr(result,"peak",0),
                       tts_clipped=getattr(result,"clipped_samples",0))
            # R441: bounded numeric-only inspection and repair BEFORE WSS.
            # Do not change normal pauses, the reference voice or DSH text.
            before=summary(result.pcm)
            pcm_for_level=result.pcm
            if candidate_r503 and (buffered or progressive_r503) and not early_tts:
                # Default to crisp original Qwen pacing; ffmpeg atempo=0.94
                # WSOLA stretching can slur fast Mandarin consonants on long
                # replies. Allow explicit opt-in via DAFEIYU_R503_SLOWDOWN=1.
                if os.environ.get("DAFEIYU_R503_SLOWDOWN")=="1":
                    from app.r532_buffered_voice_pacing import soften_fast_r503
                    pcm_for_level,slowed=soften_fast_r503(result.pcm)
                else:
                    slowed=False
                self._mark("r532_r503_tempo",
                           applied=int(slowed),
                           original_duration_ms=before.duration_ms,
                           slowed_duration_ms=len(pcm_for_level)*1000//48000)
            if early_tts:
                # Already emitted while the real TTS stream was running.
                # Never recompress or re-level afterward: bit identity with
                # the frames already sent to ESP32 is mandatory.
                leveled=bytes(streamed_out)
                removed_ms=trimmed_runs=0
                # Candidate processing replaces the turn gain; report what
                # was actually emitted rather than the unused baseline gain.
                uses_phrase_gain=candidate_r503 or len(phrases)>1
                phrase_gain=round((early_level.candidate_gain or early_level.previous_candidate_gain)*1000) if uses_phrase_gain else 1000
                turn_boost=1000 if uses_phrase_gain else round((early_level.gain or 1.0)*1000)
                attack_ms=0
            else:
                repaired,removed_ms,trimmed_runs=(
                    (pcm_for_level,0,0) if (buffered or progressive_r503) else compress_excess_silence(pcm_for_level))
                attack_ms=0
                if buffered_level is not None:
                    leveled=buffered_level.process(
                        repaired,phrase_index=phrase_index,candidate=True)
                    # R526: R525 whole-phrase RMS does not prevent abrupt
                    # high-energy phrases *within* independently cloned audio.
                    # Completed PCM only, no stream-packet volume chasing.
                    from app.r526_buffered_voice_smoothing import smooth_buffered_r503
                    leveled,smoothed_windows=smooth_buffered_r503(leveled)
                    # R537: real long-answer sample showed an over-hot phrase
                    # start and sustained fading near its tail. R536's blind
                    # 0.94 multiplier made that fade WORSE; stop calling it.
                    # Adapt only after detecting a measured >30% sustained
                    # voiced-level drop, with 2s smooth peak-safe envelopes.
                    from app.r537_r503_fade_guard import stabilize_fading_r503
                    leveled,fade=stabilize_fading_r503(
                        leveled,phrase_index=phrase_index)
                    self._mark("r537_fade_guard",
                               phrase_index=phrase_index,**fade)
                    # R680: real first-phrase MIDDLE drop was not eligible
                    # for R537, which only detected late fade in phrase2.
                    # Measure completed speech over 1s windows and repair
                    # sustained >=2s low-voiced runs in either phrase.
                    from app.r680_r503_envelope import recover_sustained_voice_dips
                    leveled,inside=recover_sustained_voice_dips(leveled)
                    self._mark("r680_r503_mid_tail_envelope",
                               phrase_index=phrase_index,**inside)
                    self._mark("r526_buffered_loudness_smoothed",
                               phrase_index=phrase_index,
                               attenuated_200ms_windows=smoothed_windows)
                    if os.environ.get("DAFEIYU_TTS_BREATH_MS", "100") != "0":
                        from app.tts_breath_pacing import extend_silence_valleys
                        leveled, breath_added_ms = extend_silence_valleys(leveled)
                        self._mark("tts_breath_pacing", phrase_index=phrase_index,
                                   added_ms=breath_added_ms)
                    phrase_gain=round((buffered_level.candidate_gain or
                                       buffered_level.previous_candidate_gain)*1000)
                    turn_boost=1000
                else:
                    leveled,phrase_gain=leveler.process(repaired)
                    leveled,turn_boost=loudness.process(leveled)
                if candidate_r503 and buffered_level is None:
                    from app.r508_r503_boundary import smooth_candidate_phrase_start
                    leveled,attack_ms=smooth_candidate_phrase_start(
                        leveled,phrase_index=phrase_index,
                        target_rms=leveler.target_rms or 0)
            # R539: D10 reproduced a sharp high-frequency ringing burst in
            # the already COMPLETE 6-char local clock reply. Repair only
            # exceptional 100ms PCM windows in short, fully buffered D10,
            # never early chunks, R503 or non-audible future packets.
            if not candidate_r503 and not early_tts and len(spoken)<=24:
                from app.r539_d10_spike_guard import suppress_short_d10_spikes
                leveled,spikes=suppress_short_d10_spikes(leveled,permitted=True)
                self._mark("r539_d10_spike_guard",**spikes)
            after=summary(leveled)
            self._mark("tts_pcm_quality",phrase_index=phrase_index,
                       pcm_duration_ms=after.duration_ms,
                       source_pcm_duration_ms=before.duration_ms,
                       pcm_max_quiet_ms=after.max_quiet_ms,
                       source_max_quiet_ms=before.max_quiet_ms,
                       pcm_quiet_percent=after.quiet_percent,
                       pcm_active_rms=after.active_rms,
                       source_pcm_active_rms=before.active_rms,
                       source_pcm_peak=before.peak,
                       pcm_peak=after.peak,
                       phrase_gain_ramp_ms=(35 if phrase_index>1 and buffered_level is not None
                                            else 150 if phrase_index>1 and early_tts and
                                            (candidate_r503 or len(phrases)>1) else 0),
                       pcm_trimmed_ms=removed_ms,
                       pcm_trimmed_runs=trimmed_runs,
                       phrase_level_permille=phrase_gain,
                       turn_boost_permille=turn_boost,
                       r508_boundary_attack_ms=attack_ms,
                       soft_peak_limited_ppm=(
                           round(1000000*early_level.limited_samples/max(1,early_level.total_out//2))
                           if early_tts else
                           round(1000000*buffered_level.limited_samples/max(1,buffered_level.total_out//2))
                           if buffered_level is not None else leveler.last_limited_samples_ppm),
                       global_peak_restricted=(0 if early_tts or buffered_level is not None
                                               else int(leveler.last_peak_restricted)))
            if not early_tts:total+=len(leveled)
            if (phrase_index>1 and candidate_r503 and (buffered or progressive_r503) and
                    not early_tts):
                pause=b""
                if topic_gap>=100:
                    from app.r537_semantic_tts_boundaries import semantic_interphrase_padding
                    pause=semantic_interphrase_padding(
                        previous_tail_ms=last_pcm_tail_ms,
                        next_lead_ms=after.lead_quiet_ms,topic_gap=topic_gap)
                    self._mark("r537_semantic_pause",
                               inserted_ms=len(pause)//48,topic_gap_chars=topic_gap)
                elif progressive_r503 and os.environ.get("DAFEIYU_TTS_BREATH_MS", "100") != "0":
                    from app.tts_breath_pacing import interphrase_breath_gap
                    pause=interphrase_breath_gap(
                        previous_tail_ms=last_pcm_tail_ms,
                        next_lead_ms=after.lead_quiet_ms)
                if pause:
                    total+=len(pause)
                    if total>MAX_REPLY_PCM:raise ValueError("tts_reply_exceeds_bound")
                    chunks.append(pause)
                    if on_pcm is not None and not buffered:
                        on_pcm(pause)
                    phrase_timings[-1]["audio_ms"]+=len(pause)//48
            phrase_timings.append({"text":phrase,"audio_ms":after.duration_ms})
            last_pcm_tail_ms=after.tail_quiet_ms
            if total>MAX_REPLY_PCM:raise ValueError("tts_reply_exceeds_bound")
            # Legacy publishes after completed phrase; R511 true incremental
            # publishes inside each validated /stream audio event instead.
            if not early_tts:
                for offset in range(0,len(leveled),30720):
                    part=leveled[offset:offset+30720]
                    chunks.append(part)
                    if on_pcm is not None and not buffered:
                        on_pcm(part)
            if candidate_r503 and buffered and not phone_report:
                r503_phrase_spans.append((phrase_buffer_start,total))
        if total==0:raise ValueError("no_verified_qwen_pcm")
        # R631: the last Pinky spoken clause is a complete independent TTS
        # phrase. A successful codec_write ACK does not prove the DAC has
        # drained before speaker_close(). Preserve all synthesized samples;
        # add only enough *silent* 60ms frames after the last phrase to protect
        # its final syllables. Do not touch ordinary D10/R503 explanations.
        if phone_report and candidate_r503 and on_pcm is not None and phrases:
            from app.r631_phone_audio_tail_guard import final_tail_padding
            pad=final_tail_padding(leveled,quiet_tail_ms=last_pcm_tail_ms)
            pad_ms=len(pad)//48
            if pad:
                if total+len(pad)>MAX_REPLY_PCM:
                    raise ValueError("tts_reply_exceeds_bound")
                chunks.append(pad)
                total+=len(pad)
                phrase_timings[-1]["audio_ms"]+=pad_ms
                on_pcm(pad)
            self._mark("r631_phone_audio_tail_guard",
                       padded_ms=pad_ms,
                       original_tail_ms=min(1000,last_pcm_tail_ms))
        if candidate_r503 and buffered and not phone_report and len(r503_phrase_spans)>1:
            from app.r586_r503_turn_loudness import balance_buffered_r503_turn
            whole=b"".join(chunks)
            normalized,report=balance_buffered_r503_turn(whole,r503_phrase_spans)
            if len(normalized)!=len(whole) or len(whole)!=total:
                raise ValueError("r586_r503_turn_span_mismatch")
            if report["applied"]:
                chunks=[normalized]
            self._mark("r586_r503_turn_loudness",**report)
        # Numeric metadata only; allows a real human '破音' report to be
        # compared with actual Qwen PCM headroom after single-stage gain.
        self._mark("audio_gain_metrics",
                   lifted_peak=int(early_level.peak if early_tts else
                                   buffered_level.peak if buffered_level is not None
                                   else leveler.peak_out),
                   gain_blocks=int(len(phrases) if early_tts or buffered_level is not None
                                   else leveler.phrases))
        self._mark("pcm_ready",pcm_bytes=total)
        # Actual TTS input and verified source answer are different artifacts:
        # reveal their exact texts in the Mac app, never in progress logs.
        # A PCM offer is not proof that the board has completed playback.
        from app.r499_reply_speech_comparison import save_verified_comparison
        if save_verified_comparison(self.native,reply,spoken,reply_origin,
                                    segments=phrase_timings,
                                    final_spoken_text=(final_spoken if
                                        computer_progress and progress_segments
                                        else None),
                                    voice_profile_id=profile,expected_speech_id=speech_id):
            self._mark("r499_reply_comparison_ready",
                       original_chars=len(reply),spoken_chars=len(spoken))
        return SpeechReply(b"".join(chunks),reply_origin,
                           voice_profile_id=profile,spoken_text_length=len(spoken),buffered=buffered)
