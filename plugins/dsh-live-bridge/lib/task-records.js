/**
 * Task serialization, protocol constants, and terminal state transitions
 * for dsh-live-bridge.
 */
import { verifiedCuaPreselectionRecovery } from './computer-cua-recovery.js'
import { delegatedPinkyResult, nativePinkyDelegationState } from './pinky-task-proof.js'
import {
  nativePinkyLaunchTarget,
  settledPinkyLaunch,
  settledPinkyScreenApp,
  nativePinkyConfirmedLaunch,
  nativePinkyConfirmedUnsentDraft,
} from './pinky-direct-launch-proof.js'
import { nativePinkyRecoveredNavigation } from './pinky-recovered-step-proof.js'
import { completedReadonlySearch, recoveredReadonlySearch } from './pinky-readonly-observe-recovery.js'
import { nativePinkyDirectFinalized } from './pinky-direct-finalization-proof.js'

export const PROTOCOL_VERSION = 1
export const TURN_ID = /^[A-Za-z0-9_-]{8,64}$/
export const CONVERSATION_ID = /^[A-Za-z0-9_-]{8,64}$/
export const MODEL_ID = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$/
export const MAX_CONVERSATIONS = 64
export const MAX_PROMPT = 4000
export const MAX_ACTIVE = 16
export const MAX_REMEMBERED = 256
export const FINAL_STATES = new Set(['answered', 'completed', 'failed', 'cancelled'])

export function extractAssistant(event) {
  if (event?.type !== 'assistant/message') return ''
  const parts = event.data?.message?.content
  if (!Array.isArray(parts)) return ''
  return parts
    .filter((x) => x?.type === 'text' && typeof x.text === 'string')
    .map((x) => x.text)
    .join('\n')
    .trim()
    .slice(0, 6000)
}

export function publicRecord(task) {
  const answered = task.status === 'answered' || task.status === 'completed'
  return {
    protocolVersion: PROTOCOL_VERSION,
    task_id: task.id,
    turn_id: task.turn,
    session_id: task.session,
    ...(task.conversation ? { conversation_id: task.conversation } : {}),
    status: task.status,
    result: answered ? {
      text: task.text,
      // Only presence of a native reasoning content block; never expose text.
      reasoning_observed: task.reasoningObserved === true,
      source: task.status === 'completed' ? 'harness_tool_events' : 'harness_assistant',
      // A native successful tool result proves the Harness tool boundary,
      // NOT an arbitrary real-world/business outcome outside that boundary.
      execution_verified: task.status === 'completed',
      tool_receipts: [...task.tools.values()].map((tool) => ({
        name: tool.name,
        receipt: tool.outcome,
      })),
      // Only trusted Pinky tool result state, correlated to the same
      // original delegated task id. Never expose the id or phone data.
      ...(task.phoneMode === 'pinky' ? {
        phone_delegation_state: nativePinkyDelegationState(task.tools),
        phone_confirmed_launch_app: nativePinkyConfirmedLaunch(task.tools),
        phone_confirmed_unsent_draft: nativePinkyConfirmedUnsentDraft(task.tools),
        // Generic same-turn direct-action settlement. The separate app
        // business outcome remains in the original DSH final answer.
        phone_direct_actions_finalized: task.status === 'completed' &&
          task.turnEnd === 'completed' && task.textAfterTools === true &&
          !task.approvalOutstanding && !task.approvalRejected &&
          nativePinkyDirectFinalized(task.tools),
      } : {}),
      phone_read_only_scoped: task.phoneMode === 'readonly' && task.phoneMaskApplied === true,
      ...(task.phoneRecoveredReadonlySearch === true ? { phone_recovered_readonly_search: true } : {}),
      ...(task.status === 'completed' && completedReadonlySearch(task)
        ? { phone_completed_readonly_search: true }
        : {}),
      phone_pinky_policy_scoped: task.phoneMode === 'pinky' && task.phonePolicyApplied === true,
    } : null,
    failure: task.status === 'failed' ? (task.failure || 'harness_agent_failed') : null,
    // R584: a prior failed navigation tap may have been recovered by a
    // later native tap. This never changes terminal status or grants business
    // success. It only avoids falsely saying all subsequent phone steps failed.
    ...(task.phoneMode === 'pinky' && task.status === 'failed' &&
        task.failure === 'native_tool_failed' &&
        task.turnEnd === 'completed' && task.textAfterTools ? {
          phone_recovery_state: nativePinkyRecoveredNavigation(task.tools),
        } : {}),
    ...(task.persona ? { persona: task.persona } : {}),
    // Never return tool arguments, raw event bodies or approval tokens.
    tools: [...task.tools.values()].map((tool) => ({ name: tool.name, outcome: tool.outcome })),
  }
}

export function savedPublicRecord(saved) {
  const terminal = FINAL_STATES.has(saved.status)
  if (!terminal) throw new Error('unsettled_saved_task')
  const ok = saved.status === 'answered' || saved.status === 'completed'
  return {
    protocolVersion: PROTOCOL_VERSION,
    task_id: saved.task_id,
    turn_id: saved.turn_id,
    session_id: saved.session_id ?? null,
    ...(saved.conversation ? { conversation_id: saved.conversation } : {}),
    status: saved.status,
    result: ok ? {
      text: saved.text || '',
      source: saved.status === 'completed' ? 'harness_tool_events' : 'harness_assistant',
      execution_verified: saved.status === 'completed',
      tool_receipts: (saved.tools || []).map((x) => ({ name: x.name, receipt: x.outcome })),
    } : null,
    failure: saved.status === 'failed' ? (saved.failure || 'harness_agent_failed') : null,
  }
}

export function applyCompletedTaskOutcome(task) {
  if (!task || FINAL_STATES.has(task.status)) return false
  if (!task.idleSeen || !task.turnEnd) return false
  if (task.turnEnd === 'aborted') {
    task.status = 'cancelled'
  } else if (task.approvalOutstanding) {
    return false
  } else if (task.approvalRejected) {
    task.status = 'failed'
    // Do not misreport a user's native refusal/cancellation as a Host crash.
    // Both outcomes remain failed for execution-safety; no tool success is claimed.
    task.failure = task.approvalDenialOutcome === 'rejected'
      ? 'native_approval_rejected'
      : task.approvalDenialOutcome === 'cancelled'
        ? 'native_approval_cancelled'
        : 'native_approval_not_granted'
  } else if (task.turnEnd !== 'completed') {
    task.status = 'failed'
    task.failure = 'harness_turn_' + task.turnEnd
  } else if ([...task.tools.values()].some((item) => item.outcome === 'failed')) {
    if (verifiedCuaPreselectionRecovery(task)) {
      // R678: provider-confirmed read-only Chrome/Finder result after
      // a harmless pre-getApp state probe. The failed tool receipt is
      // retained; no permission or side-effect error is erased.
      task.status = 'completed'
      task.cuaPreselectionRecovered = true
    } else if (recoveredReadonlySearch(task)) {
      // R682: one rejected phone_observe argument schema never reached
      // the phone; a later producer-verified same-app screen result
      // completed the explicitly read-only SEARCH. Keep failed receipt.
      task.status = 'completed'
      task.phoneRecoveredReadonlySearch = true
    } else {
      task.status = 'failed'
      task.failure = 'native_tool_failed'
    }
  } else if (task.tools.size &&
             [...task.tools.values()].some((item) => item.outcome !== 'success')) {
    task.status = 'awaiting_result'
  } else if (task.text && (!task.tools.size || task.textAfterTools)) {
    // A tool-using turn must contain a subsequent assistant response;
    // earlier "I will do X" prose isn't a final result.
    task.status = task.tools.size ? 'completed' : 'answered'
  } else {
    task.status = 'awaiting_result'
  }
  return true
}

export {
  delegatedPinkyResult,
  nativePinkyLaunchTarget,
  settledPinkyLaunch,
  settledPinkyScreenApp,
}
