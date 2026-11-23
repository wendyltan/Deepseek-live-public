/** R3 official AssistantStreamFrame -> private TTS prewarm candidates.
 * Isolated planning only; never plays audio or modifies the native Bridge.
 * The tool/approval/turn authority remains the existing DSH reducer.
 * Reasoning/tool-call arguments are not recorded, exposed or spoken.
 */
export class PrivateSpeechPrewarm {
  constructor({agentId, taskId, sessionId, nativeTurn, maxChars=2000}) {
    if (![agentId,taskId,sessionId].every(x=>typeof x==='string' && x.length>0 && x.length<160) ||
        !Number.isSafeInteger(nativeTurn) || nativeTurn<0 ||
        !Number.isSafeInteger(maxChars) || maxChars<100 || maxChars>6000)
      throw new TypeError('invalid native owner')
    this.agentId=agentId;this.taskId=taskId;this.sessionId=sessionId;this.nativeTurn=nativeTurn
    this.maxChars=maxChars;this.attempt=null;this.text='';this.nextIndex=0
    this.status='waiting';this.candidates=[];this.issued=0;this.closed=false
    this.committed=false;this.toolObserved=false;this.approvalObserved=false
  }
  /** agent is the DSH emitted owner, NOT latest foreground Session. */
  feed(agent, frame) {
    if (this.closed || agent?.id!==this.agentId || !frame || typeof frame!=='object')
      return []
    if (frame.type==='start') {
      if (this.attempt!==null || typeof frame.attemptId!=='string' ||
          !frame.attemptId || !Number.isSafeInteger(frame.revision) ||
          frame.turn!==this.nativeTurn || !Number.isSafeInteger(frame.step)) {
        this.status='invalid';this.closed=true;return []
      }
      this.attempt={id:frame.attemptId,revision:frame.revision,turn:frame.turn,step:frame.step}
      this.status='streaming';return []
    }
    const a=this.attempt
    if (!a || frame.attemptId!==a.id || frame.revision!==a.revision ||
        !Number.isSafeInteger(frame.index) || frame.index!==this.nextIndex) {
      this.closed=true;this.status='invalid';return []
    }
    if (frame.type==='chunk') {
      this.nextIndex++
      const item=frame.chunk
      if (!item || item.type!=='text-delta' || typeof item.text!=='string') {
        if (item?.type==='tool-call-delta')this.toolObserved=true
        return []
      }
      if (this.toolObserved || this.approvalObserved)return []
      if (item.text.length>this.maxChars-this.text.length) {
        this.status='overflow';this.closed=true;this.candidates=[];return []
      }
      this.text+=item.text
      const result=[]
      // A complete sentence is only a *prewarm proposal*. It can be deleted.
      const match=/[。！？!?；;](?:[”"’']|\s)*/gu
      match.lastIndex=this.issued
      let found
      while ((found=match.exec(this.text))) {
        const end=match.lastIndex
        const sentence=this.text.slice(this.issued,end).trim()
        this.issued=end
        if (sentence.length<2 || sentence.length>320)continue
        const c={kind:'prewarm_only',task_id:this.taskId,session_id:this.sessionId,
                 attempt_id:a.id,step:a.step,from:end-sentence.length,to:end,text:sentence}
        this.candidates.push(c);result.push(c)
      }
      return result
    }
    if (frame.type==='end') {
      if (frame.outcome?.kind!=='committed' || frame.outcome.eventType!=='assistant/message') {
        this.closed=true;this.status='abandoned';this.candidates=[];return []
      }
      this.committed=true
      this.status='awaiting_native_turn_end'
      return []
    }
    this.closed=true;this.status='invalid';return []
  }
  /** Tool/approval appeared on the same official task: no precommitted speech. */
  nativeEvent(eventType) {
    if (this.closed)return
    if (['tool/call','approval/asked'].includes(eventType)) {
      this.toolObserved ||= eventType==='tool/call'
      this.approvalObserved ||= eventType==='approval/asked'
      this.candidates=[]
    }
    if (['agent/error','cancel_requested','turn/aborted','session/ended'].includes(eventType)) {
      this.status='cancelled';this.closed=true;this.candidates=[]
    }
  }
  /** Only after the single authoritative task has actually settled. */
  finalize({status,finalText,turnEnd,executionVerified=false}) {
    if (this.closed || !this.committed || !['answered','completed'].includes(status) ||
        turnEnd!=='completed' || typeof finalText!=='string' ||
        this.toolObserved || this.approvalObserved) {
      this.status='not_releaseable';this.closed=true;this.candidates=[];return []
    }
    // Prefix check defends stale/mismatched attempted text; only release exact
    // sentences also present in the final native assistant message.
    if (!finalText.startsWith(this.text)) {
      this.status='text_changed';this.closed=true;this.candidates=[];return []
    }
    const released=this.candidates.map(({text,from,to})=>({
      kind:'verified_sentence',text,from,to,task_id:this.taskId,session_id:this.sessionId
    }))
    this.status='verified';this.closed=true
    return released
  }
}
