/** R568: infer only native Pinky delegate status from one authenticated tool result.
 *
 * The screen, user text and any task identifiers never reach the public Bridge
 * record.  This does not create a task, run a model or bypass an approval.
 */
const PREFIX='mcp__pinky_dafeiyu__phone_'
const NATIVE_DELEGATES=new Set(['task_run','task_wait','task_status'])
const STATES=new Set(['running','done','failed','stopped','cancelled',
  'partial','waiting_for_person','uncertain'])

export function delegatedPinkyResult(name, message) {
  if(typeof name!=='string'||!name.startsWith(PREFIX)||
     !NATIVE_DELEGATES.has(name.slice(PREFIX.length))||
     message?.role!=='tool'||message?.source?.kind!=='tool'||
     typeof message?.toolCallId!=='string'||!message.toolCallId||
     message?.source?.callId!==message?.toolCallId||
     message?.isError!==false||!Array.isArray(message?.content))
    return null
  const first=message.content.find(x=>x?.type==='text'&&typeof x.text==='string')
  if(!first||first.text.length>300000)return null
  const line=first.text.slice(0,200).split('\n',1)[0]
  // Pinky replies start with "running · task_id: ..." / "done · ...".
  // Reject guessed, explanatory or injected text before the status.
  const m=/^([a-z_]{3,22})(?=\s*·|\s*$)/.exec(line)
  if(!m||!STATES.has(m[1]))return null
  const id=/(?:^|·)\s*task_id:\s*([A-Za-z0-9_-]{7,80})(?=\s*(?:·|$))/.exec(line)
  if(!id)return null
  return {status:m[1],id:id[1]}
}

/** A terminal delegated task is verified only if the SAME turn includes
 * the original task_run and a matching Pinky task result. A tool-level
 * success without a Pinky status is never enough.
 */
export function nativePinkyDelegationState(tools) {
  if(!tools||typeof tools.values!=='function')return null
  const rows=[...tools.values()]
  const runs=rows.filter(x=>x?.name===PREFIX+'task_run')
  // One voice turn must not silently conflate two Pinky tasks.
  if(runs.length!==1)return null
  const run=runs[0]
  if(run.outcome!=='success'||!run.delegate?.id||
     !STATES.has(run.delegate.status))return null
  const rawFollowups=rows.filter(x=>
    x?.name===PREFIX+'task_wait'||x?.name===PREFIX+'task_status')
  // A failed wait, mismatched id or a call without a verified result must
  // never promote a previous done state into "current job finished".
  if(rawFollowups.some(x=>x.outcome!=='success'||
      !STATES.has(x.delegate?.status)||x.delegate?.id!==run.delegate.id))
    return null
  const last=rawFollowups.length?
    rawFollowups.at(-1).delegate.status:run.delegate.status
  return last
}
