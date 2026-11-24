/**
 * Native Harness Agent and Session event observers for dsh-live-bridge.
 */
import { cuaMethod, noteCuaResult } from './computer-cua-recovery.js'
import { rememberCompanionFact } from './companion-facts.js'
import { PrivateSpeechPrewarm } from './private-speech-prewarm.js'
import { rejectedObserveSchema } from './pinky-readonly-observe-recovery.js'
import { nativePinkySettledScreen } from './pinky-direct-finalization-proof.js'
import {
  FINAL_STATES,
  delegatedPinkyResult,
  extractAssistant,
  nativePinkyLaunchTarget,
  settledPinkyLaunch,
  settledPinkyScreenApp,
} from './task-records.js'

function parseToolResultMessage(message) {
  let callId = null
  let isError = null
  // DSH V4: first-class tool-role message; confirm producer-owned source.
  if (message?.role === 'tool' && message?.source?.kind === 'tool' &&
      typeof message.toolCallId === 'string' &&
      message.source.callId === message.toolCallId &&
      typeof message.isError === 'boolean') {
    callId = message.toolCallId
    isError = message.isError
  } else if (message?.role !== 'tool') {
    // Older DSH session logs: user-role message wrapping tool-result.
    const block = message?.content?.[0]
    if (block?.type === 'tool-result' &&
        typeof block.toolCallId === 'string' &&
        typeof block.isError === 'boolean' &&
        (message?.source === undefined ||
         (message.source.kind === 'tool' && message.source.callId === block.toolCallId))) {
      callId = block.toolCallId
      isError = block.isError
    }
  }
  return { callId, isError }
}

export function registerSessionEventHandlers({
  ctx,
  disposers,
  lookup,
  markCompleted,
  releaseIfFinal,
}) {
  // Native official Agent-stream observation, no TTS or new endpoint.
  // Scope to the task's exact live Agent; never infer owner from foreground UI.
  disposers.push(ctx.on('agent/assistant-stream', ({ agent, frame }) => {
    const task = lookup(agent?.id)
    if (!task || task.agentRef !== agent || task.session !== String(agent.id) ||
        FINAL_STATES.has(task.status) || task.status === 'cancel_requested') return
    try {
      if (frame?.type === 'start' && !task.speechPrewarm &&
          Number.isSafeInteger(frame.turn) && frame.turn >= 0) {
        task.speechPrewarm = new PrivateSpeechPrewarm({
          agentId: task.session,
          sessionId: task.session,
          taskId: task.id,
          nativeTurn: frame.turn,
        })
      }
      task.speechPrewarm?.feed(agent, frame)
    } catch {
      // Presentation observers must never break a native Agent request.
      // Drop only our ephemeral copy, without logging sensitive deltas.
      task.speechPrewarm = null
    }
  }))

  disposers.push(ctx.on('agent/status', ({ agent, status }) => {
    const task = lookup(agent.id)
    if (!task || FINAL_STATES.has(task.status)) return
    task.factRevision += 1
    if (status === 'running' && task.status !== 'cancel_requested') {
      task.status = 'running'
    } else if (status !== 'running') {
      task.idleSeen = true
      task.status = 'awaiting_result'
      markCompleted(task)
    }
    rememberCompanionFact(task)
  }))

  disposers.push(ctx.on('agent/error', ({ agent }) => {
    const task = lookup(agent.id)
    // A late native error must invalidate a premature completed signal.
    if (task) {
      task.speechPrewarm?.nativeEvent('agent/error')
      task.factRevision += 1
      task.status = 'failed'
      releaseIfFinal(task)
      rememberCompanionFact(task)
    }
  }))

  disposers.push(ctx.on('session/event', (session, event) => {
    const task = lookup(session.id)
    if (!task || FINAL_STATES.has(task.status)) return
    const previousRevision = task.factRevision
    if (event?.type === 'tool/call' || event?.type === 'approval/asked') {
      task.speechPrewarm?.nativeEvent(event.type)
    }
    if (['tool/call', 'tool/result', 'approval/asked', 'approval/decided', 'assistant/message', 'turn/end'].includes(event?.type)) {
      task.factRevision += 1
    }

    if (event?.type === 'tool/call') {
      const id = event.data?.callId
      const name = event.data?.name
      if (typeof id === 'string' && id && typeof name === 'string' && name) {
        if (!task.tools.has(id)) {
          task.tools.set(id, {
            name,
            outcome: 'pending',
            ...(name === 'cua' ? { cuaMethod: cuaMethod(event.data?.arguments) } : {}),
            ...(task.phoneMode === 'pinky' && name === 'mcp__pinky_dafeiyu__phone_launch'
              ? { launchTarget: nativePinkyLaunchTarget(name, event.data?.arguments) }
              : {}),
          })
        }
        task.textAfterTools = false
        if (task.status !== 'cancel_requested') task.status = 'running'
      }
    } else if (event?.type === 'tool/result') {
      const message = event.data?.message
      const { callId, isError } = parseToolResultMessage(message)
      const tool = task.tools.get(callId)
      if (tool && typeof isError === 'boolean') {
        tool.outcome = isError || event.data?.error ? 'failed' : 'success'
        if (tool.outcome === 'failed' && tool.name === 'mcp__pinky_dafeiyu__phone_observe') {
          tool.schemaRejected = rejectedObserveSchema(tool.name, message)
        }
        if (tool.name === 'cua') noteCuaResult(tool, message)
        if (tool.outcome === 'success' && task.phoneMode === 'pinky') {
          // R626: final direct action screen proof must be produced by the
          // same native tool call. Store only boolean; no screen data.
          tool.settledScreen = nativePinkySettledScreen(tool.name, message)
          const status = delegatedPinkyResult(tool.name, message)
          if (status) tool.delegate = status
          if (tool.name === 'mcp__pinky_dafeiyu__phone_launch' && tool.launchTarget) {
            const app = settledPinkyLaunch(tool.name, message, tool.launchTarget)
            if (app) tool.launchConfirmed = app
          }
          if (tool.name === 'mcp__pinky_dafeiyu__phone_observe') {
            tool.observedApp = settledPinkyScreenApp(tool.name, message)
          }
          if (tool.name === 'mcp__pinky_dafeiyu__phone_type') {
            tool.typedScreenApp = settledPinkyScreenApp(tool.name, message)
          }
        }
        task.textAfterTools = false
        markCompleted(task)
      }
      // Unknown call IDs, source mismatches and untyped outcomes NEVER verify.
    } else if (event?.type === 'turn/end') {
      const kind = event.data?.reason?.kind
      if (typeof kind === 'string') task.turnEnd = kind
      markCompleted(task)
    } else if (event?.type === 'approval/asked') {
      const { id, toolName } = event.data ?? {}
      if (typeof id !== 'string' || !id || id.length > 128 ||
          typeof toolName !== 'string' || !toolName || task.pendingApprovals.has(id)) {
        task.status = 'failed'
        task.failure = 'invalid_native_approval'
        releaseIfFinal(task)
      } else {
        task.pendingApprovals.add(id)
        task.approvalOutstanding = true
        if (task.status !== 'cancel_requested') task.status = 'approval_needed'
      }
    } else if (event?.type === 'approval/decided') {
      const { id, outcome } = event.data ?? {}
      if (typeof id !== 'string' || !task.pendingApprovals.has(id) ||
          !['allowed-once', 'rejected', 'cancelled', 'unavailable'].includes(outcome)) {
        task.status = 'failed'
        task.failure = 'invalid_native_approval'
        releaseIfFinal(task)
      } else {
        task.pendingApprovals.delete(id)
        task.approvalOutstanding = task.pendingApprovals.size > 0
        if (outcome !== 'allowed-once') {
          task.approvalRejected = true
          task.approvalDenialOutcome ??= outcome
        }
        if (task.status !== 'cancel_requested') {
          task.status = task.approvalOutstanding ? 'approval_needed' : 'running'
        }
        markCompleted(task)
      }
    } else if (event?.type === 'assistant/message') {
      // DSH's own message block type is evidence; the raw private
      // reasoning text, signatures and tool arguments never leave Bridge.
      const blocks = event.data?.message?.content
      if (Array.isArray(blocks) && blocks.some((block) =>
          block?.type === 'reasoning' && typeof block.text === 'string' &&
          block.text.trim().length > 0)) {
        task.reasoningObserved = true
      }
      const text = extractAssistant(event)
      if (text) {
        task.text = text
        task.textAfterTools = true
      }
      markCompleted(task)
    }

    if (task.factRevision !== previousRevision) rememberCompanionFact(task)
    // Do not intercept approval/request, autoapprove or claim tool success.
  }))
}
