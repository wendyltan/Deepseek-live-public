/**
 * Read-only, privacy-bounded snapshot of an already-owned DSH Bridge task.
 *
 * This is deliberately NOT a second Session reducer. The Bridge remains the
 * authority for tool outcomes, owner binding, approvals and completion.
 * A future trusted Mac gateway may consume these facts and dispatch confirmed
 * playback into the existing CompanionState device guard.
 */
export function companionFacts(task) {
  const tools = [...task.tools.values()]
  const active = tools.filter((tool) => tool.outcome === 'pending').length
  const failed = tools.some((tool) => tool.outcome === 'failed')
  // R541: one privacy-safe stage derived solely from a NATIVE tool/call.
  // Never expose tool arguments, screen text, product info, or model prose.
  const phoneStepByTool={
    phone_connect:'connecting_phone',phone_launch:'opening_app',
    phone_app:'opening_app',phone_type:'entering_text',
    phone_observe:'reading_screen',phone_wait_for:'reading_screen',
    phone_tap:'navigating_screen',phone_swipe:'navigating_screen',
    phone_task_run:'delegated_task',phone_task_wait:'delegated_task',
    phone_request_approval:'approval_requested',phone_release:'releasing_phone',
  }
  const pendingPhone=tools.filter(t=>t.outcome==='pending' &&
    typeof t.name==='string' &&
    t.name.startsWith('mcp__pinky_dafeiyu__phone_')).at(-1)
  const phoneToolStep=pendingPhone
    ? (phoneStepByTool[pendingPhone.name.slice('mcp__pinky_dafeiyu__'.length)]||'phone_tool_busy')
    : null
  // R672: CUA uses the real native tool name "cua". Expose only bounded
  // outcome counters and a known stage, never tool arguments/screen content.
  const computerTools=tools.filter(t=>t.name==='cua')
  const computerSuccess=Math.min(32,computerTools.filter(t=>t.outcome==='success').length)
  const computerPending=computerTools.some(t=>t.outcome==='pending')
  const computerQuestionPending=computerPending && task.computerQuestionOutstanding===true
  const status = task.status
  const outcome = status === 'completed' ? 'tool_verified'
    : status === 'answered' ? 'answered'
      : status === 'failed' ? 'failed'
        : status === 'cancelled' ? 'cancelled'
          : null
  const phase = outcome ? 'settled'
    : task.approvalOutstanding || computerQuestionPending ? 'approval_pending'
      : status === 'cancel_requested' ? 'cancel_requested'
        : active ? 'working'
          : status === 'awaiting_result' ? 'settling'
            : 'thinking'
  return {
    protocolVersion: 1,
    revision: task.factRevision ?? 0,
    turn_id: task.turn,
    session_id: task.session,
    task_phase: phase,
    tool_active_count: active,
    ...(phoneToolStep?{phone_tool_step:phoneToolStep}:{}),
    ...(computerQuestionPending?{computer_tool_step:'cua_waiting_permission'}:
       computerPending?{computer_tool_step:'cua_running'}:{}),
    ...(computerTools.length?{computer_tool_succeeded_count:computerSuccess}:{}),
    tool_failed: failed,
    approval_pending: outcome === null && (task.approvalOutstanding === true || computerQuestionPending),
    outcome,
    assistant_ready_for_tts: status === 'answered' || status === 'completed',
  }
}

// Volatile snapshots captured at native event boundaries, before the visual
// polling interval can hide short tool/approval transitions. No private data.
export const FACT_HISTORY_LIMIT = 64
export function rememberCompanionFact(task) {
  if (!task.session) return
  const next = companionFacts(task)
  const history = task.factHistory ?? (task.factHistory = [])
  if (history.length && history[history.length - 1].revision === next.revision)
    history[history.length - 1] = next
  else history.push(next)
  if (history.length > FACT_HISTORY_LIMIT) history.shift()
}

export function companionFactChanges(task, afterRevision) {
  const history = task.factHistory ?? []
  if (!history.length || afterRevision > task.factRevision ||
      history[0].revision > afterRevision + 1) return null
  return history.filter((item) => item.revision > afterRevision)
}
