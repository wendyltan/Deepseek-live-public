/**
 * Dual-token protected /memory-manage HTTP endpoint covering manual memory
 * and persona growth candidate review/rollback operations.
 */
import { timingSafeEqual } from 'node:crypto'
import { readBody, send } from './http-utils.js'
import { PROTOCOL_VERSION } from './task-records.js'

const ALLOWED_ACTION_KEYS = {
  list: ['protocolVersion', 'action'],
  export: ['protocolVersion', 'action'],
  read: ['protocolVersion', 'action', 'id'],
  consent: ['protocolVersion', 'action', 'allow', 'confirm'],
  put: ['protocolVersion', 'action', 'id', 'text', 'expectedRevision'],
  remove: ['protocolVersion', 'action', 'id', 'expectedRevision', 'confirm'],
  'growth.list': ['protocolVersion', 'action', 'status'],
  'growth.version': ['protocolVersion', 'action'],
  'growth.propose': ['protocolVersion', 'action', 'text', 'turn_id', 'confirm'],
  'growth.decide': ['protocolVersion', 'action', 'id', 'decision', 'expectedRevision', 'confirm'],
  'growth.rollback': ['protocolVersion', 'action', 'toVersion', 'expectedRevision', 'confirm'],
  'growth.suggestion-consent': ['protocolVersion', 'action', 'allow', 'expectedRevision', 'confirm'],
}

export function registerMemoryManageRoute({
  attach,
  protect,
  memoryVault,
  memoryAdmin,
  growth,
}) {
  attach('/memory-manage', async (req, res) => {
    if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'method_not_allowed' })
    if (!protect(req, res)) return
    if (!memoryVault) return send(res, 503, { ok: false, error: 'memory_not_enabled' })

    const admin = req.headers?.['x-dsh-live-memory-token']
    const wanted = Buffer.from(memoryAdmin)
    const actual = typeof admin === 'string' ? Buffer.from(admin) : Buffer.alloc(0)
    if (actual.length !== wanted.length || !timingSafeEqual(actual, wanted)) {
      return send(res, 403, { ok: false, error: 'memory_admin_required' })
    }

    const body = await readBody(req)
    if (!body || body.protocolVersion !== PROTOCOL_VERSION || typeof body.action !== 'string') {
      return send(res, 400, { ok: false, error: 'memory_request_invalid' })
    }
    const allowed = ALLOWED_ACTION_KEYS[body.action]
    if (!allowed || Object.keys(body).some((key) => !allowed.includes(key))) {
      return send(res, 400, { ok: false, error: 'memory_request_invalid' })
    }

    try {
      if (body.action.startsWith('growth.')) {
        if (!growth) return send(res, 503, { ok: false, error: 'growth_disabled' })
        if (body.action === 'growth.list') {
          return send(res, 200, { ok: true, candidates: growth.listCandidates(body.status ?? 'new') })
        }
        if (body.action === 'growth.version') {
          return send(res, 200, { ok: true, ...growth.version() })
        }
        // Disabling suggestions is always allowed with admin auth. Turning them
        // ON still requires the existing manual-memory consent first.
        if (body.action === 'growth.suggestion-consent') {
          if (body.confirm !== 'GROWTH_SUGGESTIONS_CONSENT') {
            return send(res, 400, { ok: false, error: 'growth_confirmation_required' })
          }
          if (body.allow === true && !memoryVault.list().consent.manual_write) {
            return send(res, 403, { ok: false, error: 'memory_user_consent_required' })
          }
          return send(res, 200, {
            ok: true,
            ...growth.setSuggestionConsent({
              allow: body.allow,
              expectedRevision: body.expectedRevision,
              confirmed: true,
            }),
          })
        }
        // Even staging an explicit user proposal requires existing consent.
        if (!memoryVault.list().consent.manual_write) {
          return send(res, 403, { ok: false, error: 'memory_user_consent_required' })
        }
        if (body.action === 'growth.propose') {
          if (body.confirm !== 'USER_EXPLICIT_GROWTH_PROPOSAL') {
            return send(res, 400, { ok: false, error: 'growth_confirmation_required' })
          }
          return send(res, 200, {
            ok: true,
            ...growth.propose({
              text: body.text,
              turn_id: body.turn_id ?? null,
              source: 'user_explicit',
            }),
          })
        }
        if (body.action === 'growth.decide') {
          if (body.confirm !== (body.decision === 'accept' ? 'ACCEPT_GROWTH_FACT' : 'REJECT_GROWTH_FACT')) {
            return send(res, 400, { ok: false, error: 'growth_confirmation_required' })
          }
          return send(res, 200, {
            ok: true,
            ...growth.decide({
              id: body.id,
              decision: body.decision,
              expectedRevision: body.expectedRevision,
              confirmed: true,
            }),
          })
        }
        if (body.action === 'growth.rollback') {
          if (body.confirm !== 'ROLLBACK_GROWTH_VERSION') {
            return send(res, 400, { ok: false, error: 'growth_confirmation_required' })
          }
          return send(res, 200, {
            ok: true,
            ...growth.rollback({
              toVersion: body.toVersion,
              expectedRevision: body.expectedRevision,
              confirmed: true,
            }),
          })
        }
      }

      if (body.action === 'list') return send(res, 200, { ok: true, ...memoryVault.list() })
      if (body.action === 'export') return send(res, 200, { ok: true, ...memoryVault.exportAll() })
      if (body.action === 'read') return send(res, 200, { ok: true, fact: memoryVault.read(body.id) })
      if (body.action === 'consent') {
        if (body.confirm !== 'MANUAL_MEMORY_CONSENT' || typeof body.allow !== 'boolean') {
          return send(res, 400, { ok: false, error: 'memory_confirmation_required' })
        }
        memoryVault.setManualConsent(body.allow)
        return send(res, 200, { ok: true, consent: memoryVault.list().consent })
      }
      if (body.action === 'put') {
        if (body.id !== undefined && typeof body.id !== 'string') {
          return send(res, 400, { ok: false, error: 'memory_request_invalid' })
        }
        const { id, ...fact } = body
        const value = memoryVault.put({ id, ...fact })
        return send(res, 200, { ok: true, ...value })
      }
      if (body.action === 'remove') {
        if (body.confirm !== 'DELETE_THIS_FACT') {
          return send(res, 400, { ok: false, error: 'memory_confirmation_required' })
        }
        return send(res, 200, { ok: true, ...memoryVault.remove(body.id, body.expectedRevision) })
      }
    } catch (err) {
      const message = err?.message || ''
      if (message === 'memory_user_consent_required') {
        return send(res, 403, { ok: false, error: message })
      }
      if (message === 'memory_revision_conflict' || message === 'growth_revision_conflict') {
        return send(res, 409, { ok: false, error: message })
      }
      if (message.startsWith('growth_') || ['memory_unknown_id', 'memory_invalid_fact'].includes(message)) {
        return send(res, 400, { ok: false, error: message })
      }
      return send(res, 503, { ok: false, error: 'memory_unavailable' })
    }
  })
}
