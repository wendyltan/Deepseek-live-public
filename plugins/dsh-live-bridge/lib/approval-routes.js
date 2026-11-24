/**
 * Approval and macOS Computer Use / CUA question waterfall handlers and HTTP routes
 * for dsh-live-bridge.
 */
import { randomUUID } from 'node:crypto'
import { boundedComputerQuestion } from './computer-questions.js'
import { localMacPreconsent, preapprovedNativeCuaChoice } from './computer-preconsent.js'
import { rememberCompanionFact } from './companion-facts.js'
import { readBody, send } from './http-utils.js'
import { CONVERSATION_ID, FINAL_STATES, PROTOCOL_VERSION } from './task-records.js'

export function registerApprovalAndQuestionRoutes({
  attach,
  protect,
  tasks,
  bySession,
  byConversation,
  approvalRequests,
  computerQuestions,
  approvalEnabled,
}) {
  function approvalOwner(body) {
    if (!body || body.protocolVersion !== PROTOCOL_VERSION ||
        typeof body.conversation_id !== 'string' ||
        !CONVERSATION_ID.test(body.conversation_id)) {
      return null
    }
    const binding = byConversation.get(body.conversation_id)
    const task = tasks.get(binding?.busy ?? '')
    return task?.session && !FINAL_STATES.has(task.status) ? task : null
  }

  // Official Harness waterfall answerer. No locally invented permission result.
  // Only the no-I/O probe can be approved in the current isolated milestone.
  function companionApprovalAnswerer(request, next) {
    if (!approvalEnabled || request?.toolName !== 'dsh_live_approval_probe') {
      return next()
    }
    const task = tasks.get(bySession.get(String(request?.agent?.id ?? '')) ?? '')
    if (!task || !task.conversation || task.agentRef !== request.agent ||
        FINAL_STATES.has(task.status) || task.status === 'cancel_requested') {
      return 'unavailable'
    }
    if ([...approvalRequests.values()].some((x) => x.task_id === task.id)) {
      return 'unavailable'
    }
    const request_id = randomUUID()
    return new Promise((resolve) => {
      let settled = false
      const finish = (outcome) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        request.signal?.removeEventListener('abort', aborted)
        approvalRequests.delete(request_id)
        resolve(outcome)
      }
      const aborted = () => finish('cancelled')
      const timer = setTimeout(() => finish('unavailable'), 120000)
      approvalRequests.set(request_id, {
        request_id,
        task_id: task.id,
        conversation_id: task.conversation,
        session_id: task.session,
        agent: request.agent,
        tool: 'dsh_live_approval_probe',
        finish,
      })
      if (request.signal?.aborted) aborted()
      else request.signal?.addEventListener('abort', aborted, { once: true })
    })
  }

  // The native macOS CUA provider asks through the official User Questions
  // waterfall, not approval/request. Capture only an exact live computer
  // tool question, forward it to the authenticated Mac user, and never
  // choose a default answer or let a disconnected browser claim it.
  function scopedComputerQuestionAnswerer(request, next) {
    const agent = request?.agent
    const task = tasks.get(bySession.get(String(agent?.id ?? '')) ?? '')
    const question = boundedComputerQuestion(request)
    if (!question || !task || task.agentRef !== agent ||
        !task.conversation || FINAL_STATES.has(task.status) ||
        task.status === 'cancel_requested' ||
        ![...task.tools.values()].some((t) => t.name === 'cua' && t.outcome === 'pending')) {
      return next()
    }
    if ([...computerQuestions.values()].some((q) => q.task_id === task.id)) {
      return next()
    }
    // R676: a previous explicit switch in Mac Preferences may authorize
    // only the exact built-in Finder/Chrome access request for this task.
    // No generic tool grant, no saved CUA permission, no macOS TCC bypass.
    const preauthorized = preapprovedNativeCuaChoice(request, localMacPreconsent())
    if (preauthorized) return Promise.resolve(preauthorized)
    const request_id = randomUUID()
    return new Promise((resolve, reject) => {
      let settled = false
      const finish = (selection, reason = null) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        request.signal?.removeEventListener('abort', aborted)
        computerQuestions.delete(request_id)
        task.computerQuestionOutstanding = false
        task.factRevision++
        rememberCompanionFact(task)
        if (reason) reject(new Error(reason))
        else resolve({ answers: [{ id: question.question_id, selected: [selection] }] })
      }
      const aborted = () => finish(null, 'cua_question_aborted')
      const timer = setTimeout(() => finish(null, 'cua_question_timeout'), 105000)
      computerQuestions.set(request_id, {
        request_id,
        task_id: task.id,
        conversation_id: task.conversation,
        session_id: task.session,
        agent,
        question,
        finish,
      })
      task.computerQuestionOutstanding = true
      task.factRevision++
      rememberCompanionFact(task)
      if (request.signal?.aborted) aborted()
      else request.signal?.addEventListener('abort', aborted, { once: true })
    })
  }

  attach('/computer-question/pending', async (req, res) => {
    if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'method_not_allowed' })
    if (!protect(req, res)) return
    const body = await readBody(req)
    if (!body || body.protocolVersion !== PROTOCOL_VERSION ||
        typeof body.conversation_id !== 'string' ||
        !CONVERSATION_ID.test(body.conversation_id) ||
        Object.keys(body).some((k) => !['protocolVersion', 'conversation_id'].includes(k))) {
      return send(res, 400, { ok: false, error: 'invalid_computer_question_query' })
    }
    const task = approvalOwner(body)
    const pending = task
      ? [...computerQuestions.values()].find((q) =>
          q.task_id === task.id && q.session_id === task.session && q.agent === task.agentRef)
      : null
    return send(res, 200, {
      ok: true,
      pending: pending ? {
        task_id: pending.task_id,
        request_id: pending.request_id,
        question_id: pending.question.question_id,
        question: pending.question.question,
        detail: pending.question.detail,
        header: pending.question.header,
        options: pending.question.options,
      } : null,
    })
  })

  attach('/computer-question/decide', async (req, res) => {
    if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'method_not_allowed' })
    if (!protect(req, res)) return
    const body = await readBody(req)
    if (!body || body.protocolVersion !== PROTOCOL_VERSION ||
        typeof body.conversation_id !== 'string' ||
        !CONVERSATION_ID.test(body.conversation_id) ||
        !['task_id', 'request_id', 'question_id', 'choice'].every((k) =>
          typeof body[k] === 'string' && body[k].length > 0 && body[k].length <= 160) ||
        Object.keys(body).some((k) => !['protocolVersion', 'conversation_id',
          'task_id', 'request_id', 'question_id', 'choice'].includes(k))) {
      return send(res, 400, { ok: false, error: 'invalid_computer_question_decision' })
    }
    const task = approvalOwner(body)
    const q = computerQuestions.get(body.request_id)
    if (!task || !q || q.task_id !== task.id || q.agent !== task.agentRef ||
        q.session_id !== task.session || q.conversation_id !== body.conversation_id ||
        q.question.question_id !== body.question_id ||
        !q.question.options.includes(body.choice) ||
        !task.computerQuestionOutstanding) {
      return send(res, 409, { ok: false, error: 'computer_question_no_longer_pending' })
    }
    q.finish(body.choice)
    return send(res, 202, {
      ok: true,
      submitted: true,
      message: 'native_computer_question_answer_pending_confirmation',
    })
  })

  attach('/approval/pending', async (req, res) => {
    if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'method_not_allowed' })
    if (!protect(req, res)) return
    if (!approvalEnabled) return send(res, 503, { ok: false, error: 'approval_disabled' })
    const body = await readBody(req)
    if (!body || body.protocolVersion !== PROTOCOL_VERSION ||
        typeof body.conversation_id !== 'string' || !CONVERSATION_ID.test(body.conversation_id) ||
        Object.keys(body).some((k) => !['protocolVersion', 'conversation_id'].includes(k))) {
      return send(res, 400, { ok: false, error: 'invalid_approval_query' })
    }
    const task = approvalOwner(body)
    const request = task
      ? [...approvalRequests.values()].find((x) =>
          x.task_id === task.id && x.session_id === task.session)
      : null
    return send(res, 200, {
      ok: true,
      pending: request ? {
        task_id: request.task_id,
        request_id: request.request_id,
        tool: request.tool,
        description: '仅返回内存测试标记，不读取或修改电脑',
        scope: '仅本次操作',
      } : null,
    })
  })

  attach('/approval/decide', async (req, res) => {
    if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'method_not_allowed' })
    if (!protect(req, res)) return
    if (!approvalEnabled) return send(res, 503, { ok: false, error: 'approval_disabled' })
    const body = await readBody(req)
    if (!body || body.protocolVersion !== PROTOCOL_VERSION ||
        typeof body.conversation_id !== 'string' || !CONVERSATION_ID.test(body.conversation_id) ||
        typeof body.task_id !== 'string' || typeof body.request_id !== 'string' ||
        !['allowed-once', 'rejected', 'cancelled'].includes(body.decision) ||
        Object.keys(body).some((k) => !['protocolVersion', 'conversation_id', 'task_id', 'request_id', 'decision'].includes(k))) {
      return send(res, 400, { ok: false, error: 'invalid_approval_decision' })
    }
    const task = approvalOwner(body)
    const request = approvalRequests.get(body.request_id)
    if (!task || task.id !== body.task_id || !request ||
        request.task_id !== task.id || request.conversation_id !== body.conversation_id ||
        request.session_id !== task.session || request.agent !== task.agentRef ||
        !task.approvalOutstanding || !task.pendingApprovals.size) {
      return send(res, 409, { ok: false, error: 'approval_no_longer_pending' })
    }
    request.finish(body.decision)
    return send(res, 202, {
      ok: true,
      submitted: true,
      message: 'approval_decision_pending_native_confirmation',
    })
  })

  return { companionApprovalAnswerer, scopedComputerQuestionAnswerer }
}
