/**
 * Project-owned bridge to the official Harness agent API.
 *
 * Loads only in an explicitly selected official Harness profile.
 * No sibling-project service, model key, or remote approval delegation.
 */
import { createHash, randomUUID, timingSafeEqual } from 'node:crypto'
import { z } from 'zod'
import { readFileSync, statSync, lstatSync } from 'node:fs'
import { isAbsolute, join } from 'node:path'
import { installReadonlyScope } from './mac-readonly.js'
import { installModelSelection } from '@deepseek-ai/dsh-agent'
import { openBindingLedger, turnDigest } from './session-bindings.js'
import { openManualMemory } from './manual-memory.js'
import { companionFacts, rememberCompanionFact, companionFactChanges } from './companion-facts.js'
import { boundedComputerQuestion } from './computer-questions.js'
import {localMacPreconsent,preapprovedNativeCuaChoice} from './computer-preconsent.js'
import {cuaMethod,noteCuaResult,verifiedCuaPreselectionRecovery} from './computer-cua-recovery.js'
import { PrivateSpeechPrewarm } from './private-speech-prewarm.js'
import { scopedReadOnlyPhoneTools } from './pinky-readonly-policy.js'
import { delegatedPinkyResult, nativePinkyDelegationState } from './pinky-task-proof.js'
import { nativePinkyLaunchTarget, settledPinkyLaunch, settledPinkyScreenApp, nativePinkyConfirmedLaunch, nativePinkyConfirmedUnsentDraft } from './pinky-direct-launch-proof.js'
import { nativePinkyRecoveredNavigation } from './pinky-recovered-step-proof.js'
import { completedReadonlySearch,recoveredReadonlySearch,rejectedObserveSchema } from './pinky-readonly-observe-recovery.js'
import { nativePinkySettledScreen, nativePinkyDirectFinalized } from './pinky-direct-finalization-proof.js'
import { openPersona } from './persona-runtime.js'
import { openGrowth } from './persona-growth.js'
import {suggestedGrowthFromUserTurn} from './persona-growth-suggestions.js'

export const name = 'dsh-live-bridge'
export const inject = ['webServer', 'agents', 'agentDefaultModel', 'tools', 'llm']

// Optional native Profile wiring. The token stays in a private, mode-0600
// file owned by the current user; isolated legacy env setups remain unchanged.
export const Config = z.object({
  workspaceRoot: z.string().default(''),
  bridgeTokenFile: z.string().default(''),
  toolMode: z.enum(['legacy', 'native']).default('legacy'),
  // Explicit profile opt-in; never silently attach an Agent preset elsewhere.
  webPresetId: z.enum(['', 'deepseek-live-web']).default(''),
  visibleModels: z.string().default(''),
  companionFacts: z.boolean().default(false),
  companionPersona: z.boolean().default(false),
  // R538 opt-in only in the isolated 3080 profile. The ledger is private
  // inside the selected project only; never activate it in another DSH instance.
  sessionRecovery: z.boolean().default(false),
  sessionStateDir: z.string().default(''),
  // Native profile configuration avoids plaintext admin credentials in YAML,
  // process arguments, global launchctl environment, or logs.
  manualMemory: z.boolean().default(false),
  personaGrowth: z.boolean().default(false),
  memoryAdminTokenFile: z.string().default(''),
  manualMemoryDir: z.string().default(''),
  personaGrowthDir: z.string().default(''),
})

function readProfileBridgeToken(path) {
  if (!path) return ''
  if (!isAbsolute(path)) throw new Error('bridge_token_path_not_absolute')
  const file = statSync(path)
  if (!file.isFile() || (file.mode & 0o077) !== 0 ||
      (typeof process.getuid === 'function' && file.uid !== process.getuid()))
    throw new Error('bridge_token_file_not_private')
  return readFileSync(path, 'utf8').trim()
}
function readProfileAdminToken(path) {
  if (!isAbsolute(path))throw new Error('memory_admin_path_not_absolute')
  const file=lstatSync(path)
  if(file.isSymbolicLink()||!file.isFile()||file.nlink!==1||(file.mode&0o077)!==0||
      (typeof process.getuid==='function' && file.uid!==process.getuid()))
    throw new Error('memory_admin_file_not_private')
  return readFileSync(path,'utf8').trim()
}

const PREFIX = '/dsh-live-bridge'
const PROTOCOL_VERSION = 1
const TURN_ID = /^[A-Za-z0-9_-]{8,64}$/
const CONVERSATION_ID = /^[A-Za-z0-9_-]{8,64}$/
const MODEL_ID = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$/
const MAX_CONVERSATIONS = 64
const MAX_PROMPT = 4000
const MAX_ACTIVE = 16
const MAX_REMEMBERED = 256
const LIMIT_BYTES = 16 * 1024
const FINAL_STATES = new Set(['answered', 'completed', 'failed', 'cancelled'])

function send(res, code, payload) {
  const body = JSON.stringify(payload)
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
  })
  res.end(body)
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0
    const parts = []
    req.on('data', (part) => {
      size += part.length
      if (size > LIMIT_BYTES) {
        reject(new Error('body_too_large'))
        return
      }
      parts.push(part)
    })
    req.on('end', () => {
      if (size > LIMIT_BYTES) return
      try {
        const obj = JSON.parse(Buffer.concat(parts).toString('utf8'))
        resolve(obj && typeof obj === 'object' && !Array.isArray(obj) ? obj : null)
      } catch { resolve(null) }
    })
    req.on('error', reject)
  })
}

function isLoopback(req) {
  const ip = req.socket?.remoteAddress ?? ''
  return ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1'
}

function goodToken(req, expected) {
  if (expected.length < 32 || expected.length > 256) return false
  const header = req.headers?.authorization
  if (typeof header !== 'string' || !header.startsWith('Bearer ')) return false
  const actual = Buffer.from(header.slice(7))
  const wanted = Buffer.from(expected)
  return actual.length === wanted.length && timingSafeEqual(actual, wanted)
}

function validWorkspace(text) {
  if (typeof text !== 'string' || !isAbsolute(text)) return false
  try { return statSync(text).isDirectory() } catch { return false }
}

function extractAssistant(event) {
  if (event?.type !== 'assistant/message') return ''
  const parts = event.data?.message?.content
  if (!Array.isArray(parts)) return ''
  return parts.filter((x) => x?.type === 'text' && typeof x.text === 'string')
    .map((x) => x.text).join('\n').trim().slice(0, 6000)
}

function publicRecord(task) {
  const answered = task.status === 'answered' || task.status === 'completed'
  return {
    protocolVersion: PROTOCOL_VERSION,
    task_id: task.id, turn_id: task.turn,
    session_id: task.session,
    ...(task.conversation ? { conversation_id: task.conversation } : {}),
    status: task.status,
    result: answered ? {
      text: task.text,
      // Only presence of a native reasoning content block; never expose text.
      reasoning_observed:task.reasoningObserved === true,
      source: task.status === 'completed' ? 'harness_tool_events' : 'harness_assistant',
      // A native successful tool result proves the Harness tool boundary,
      // NOT an arbitrary real-world/business outcome outside that boundary.
      execution_verified: task.status === 'completed',
      tool_receipts: [...task.tools.values()].map((tool) => ({
        name: tool.name, receipt: tool.outcome,
      })),
      // Only trusted Pinky tool result state, correlated to the same
      // original delegated task id. Never expose the id or phone data.
      ...(task.phoneMode==='pinky' ? {
        phone_delegation_state:nativePinkyDelegationState(task.tools),
        phone_confirmed_launch_app:nativePinkyConfirmedLaunch(task.tools),
        phone_confirmed_unsent_draft:nativePinkyConfirmedUnsentDraft(task.tools),
        // Generic same-turn direct-action settlement. The separate app
        // business outcome remains in the original DSH final answer.
        phone_direct_actions_finalized:task.status==='completed' &&
          task.turnEnd==='completed' && task.textAfterTools===true &&
          !task.approvalOutstanding && !task.approvalRejected &&
          nativePinkyDirectFinalized(task.tools)
      } : {}),
      phone_read_only_scoped:task.phoneMode==='readonly' && task.phoneMaskApplied===true,
      ...(task.phoneRecoveredReadonlySearch===true ? {phone_recovered_readonly_search:true} : {}),
      ...(task.status==='completed' && completedReadonlySearch(task) ?
         {phone_completed_readonly_search:true} : {}),
      phone_pinky_policy_scoped:task.phoneMode==='pinky' && task.phonePolicyApplied===true,
    } : null,
    failure: task.status === 'failed' ? (task.failure || 'harness_agent_failed') : null,
    // R584: a prior failed navigation tap may have been recovered by a
    // later native tap. This never changes terminal status or grants business
    // success. It only avoids falsely saying all subsequent phone steps failed.
    ...(task.phoneMode==='pinky' && task.status==='failed' &&
        task.failure==='native_tool_failed' &&
        task.turnEnd==='completed' && task.textAfterTools ? {
          phone_recovery_state:nativePinkyRecoveredNavigation(task.tools)
        } : {}),
    ...(task.persona ? {persona:task.persona} : {}),
    // Never return tool arguments, raw event bodies or approval tokens.
    tools:[...task.tools.values()].map(tool=>({name:tool.name,outcome:tool.outcome})),
  }
}

function savedPublicRecord(saved) {
  const terminal=FINAL_STATES.has(saved.status)
  if (!terminal) throw new Error('unsettled_saved_task')
  const ok=saved.status==='answered'||saved.status==='completed'
  return {
    protocolVersion:PROTOCOL_VERSION,
    task_id:saved.task_id,turn_id:saved.turn_id,
    session_id:saved.session_id??null,
    ...(saved.conversation?{conversation_id:saved.conversation}:{}),
    status:saved.status,
    result:ok?{
      text:saved.text||'',
      source:saved.status==='completed'?'harness_tool_events':'harness_assistant',
      execution_verified:saved.status==='completed',
      tool_receipts:(saved.tools||[]).map(x=>({name:x.name,receipt:x.outcome})),
    }:null,
    failure:saved.status==='failed'?(saved.failure||'harness_agent_failed'):null,
  }
}

export function apply(ctx, profileConfig = {}) {
  const config = Config.parse(profileConfig)
  ctx.effect(() => {
    const token = process.env.DSH_LIVE_BRIDGE_TOKEN || readProfileBridgeToken(config.bridgeTokenFile)
    const root = process.env.DSH_LIVE_WORKSPACE_ROOT || config.workspaceRoot
    // No token provisioning, no profile changes, no automatic model requests.
    const configured = token.length >= 32 && token.length <= 256 && validWorkspace(root)
    // Explicitly opt-in: no memory, disk writes or resume in the existing v0.4 profile.
    const recoveryEnabled = process.env.DSH_LIVE_ENABLE_SESSION_RECOVERY === '1'
       || config.sessionRecovery === true
    const ledger = configured && recoveryEnabled
      ? openBindingLedger(root, process.env.DSH_LIVE_STATE_DIR || config.sessionStateDir)
      : null
    // Persona has a private snapshot/fallback independent of Agent lifecycle.
    // Never turn an invalid persona file into a failed DSH session or a
    // second tool-enabled Agent. Keep workspace validation fail-closed.
    const personaEnabled = process.env.DSH_LIVE_ENABLE_P1_PERSONA === '1' ||
      config.companionPersona
    const personaEngine = configured && personaEnabled ? openPersona(root) : null
    // Separate admin capability: the ordinary task token alone cannot alter
    // remembered user facts or grant consent. Disabled in all existing profiles.
    const memoryOptIn = process.env.DSH_LIVE_ENABLE_MANUAL_MEMORY === '1' || config.manualMemory
    const memoryAdmin = process.env.DSH_LIVE_MEMORY_ADMIN_TOKEN ||
      (memoryOptIn && config.memoryAdminTokenFile
        ? readProfileAdminToken(config.memoryAdminTokenFile) : '')
    if (memoryOptIn && (!configured || memoryAdmin.length < 32 ||
        memoryAdmin.length > 256 || memoryAdmin === token))
      throw new Error('memory_admin_not_configured')
    const memoryVault = memoryOptIn
      ? openManualMemory(root,process.env.DSH_LIVE_MANUAL_MEMORY_DIR || config.manualMemoryDir)
      : null
    // Growth is a separate, opt-in human review queue. The existing private
    // admin token and explicit manual-memory consent remain mandatory.
    const growthEnabled=process.env.DSH_LIVE_ENABLE_PERSONA_GROWTH==='1' || config.personaGrowth
    if(growthEnabled && (!personaEngine || !memoryVault))
      throw new Error('growth_requires_persona_and_manual_memory')
    const growth=growthEnabled ? openGrowth(root,
      process.env.DSH_LIVE_PERSONA_GROWTH_DIR || config.personaGrowthDir) : null
    // One bounded renderer is shared by actual official PromptContext and
    // metadata. Prevent version/hash drifting from what a bound Agent reads.
    // Growth never changes identity Core or adds extra model requests.
    function approvedGrowthContext() {
      if(!personaEngine)return ''
      try {
        const base=personaEngine.metadata()
        // Keep dynamic text byte-stable when an older reviewed fact set is
        // restored. The monotonic version lives in /health and /result
        // metadata, not in the durable user-role PromptContext snapshot.
        const limit=Math.min(1100,8192-base.bytes-2)
        const header='大肥鱼人格来源 '+base.source
        if(limit<Buffer.byteLength(header))return ''
        let rendered=header
        if(growth && memoryVault?.list().consent.manual_write) {
          for(const fact of growth.activeFacts(10)) {
            const next=rendered+'\n经用户审核的长期事实：'+fact
            if(Buffer.byteLength(next)>limit)break
            rendered=next
          }
        }
        return rendered
      }catch{return ''}
    }
    function personaMetadata(speechOnly=false) {
      if(!personaEngine)return null
      const base=personaEngine.metadata(speechOnly)
      if(!growth || speechOnly)return base
      const layers=personaEngine.load()
      const dynamic=approvedGrowthContext()
      const joined=layers.core+'\n'+layers.style+
        (dynamic?'\n'+dynamic:'')
      const header=dynamic.split('\n')[0]||''
      const dbytes=dynamic?Buffer.byteLength(dynamic):0
      const hbytes=Buffer.byteLength(header)
      const memoryBytes=dynamic.includes('\n')?
        dbytes-hbytes-1:0
      return {...base,
        version:growth.version().version,
        sha256:createHash('sha256').update(joined).digest('hex'),
        bytes:Buffer.byteLength(joined),
        layers:{core:Buffer.byteLength(layers.core),
          style:Buffer.byteLength(layers.style),
          dynamic:hbytes,memory:memoryBytes},
        growth:growth.version()}
    }
    const tasks = new Map()
    const byTurn = new Map()
    const bySession = new Map()
    const byConversation = new Map()
    const pendingConversations = new Set()
    const endedConversations = new Set()
    const approvalEnabled = configured &&
      process.env.DSH_LIVE_ENABLE_COMPANION_APPROVAL === '1' &&
      process.env.DSH_LIVE_APPROVAL_TOOL === 'dsh_live_approval_probe'
    const approvalRequests = new Map()
    // Scoped native CUA human questions, never a blanket tool approval.
    const computerQuestions = new Map()
    const disposers = []

    function attach(path, handler) {
      disposers.push(ctx.webServer.register({
        kind: 'exact', path: PREFIX + path,
        handler: async (req, res) => {
          try { await handler(req, res) }
          catch (err) {
            send(res, err?.message === 'body_too_large' ? 413 : 500,
              { ok: false, error: err?.message === 'body_too_large' ? 'body_too_large' : 'bridge_error' })
          }
        },
      }))
    }

    function protect(req, res) {
      if (!isLoopback(req)) {
        send(res, 403, { ok: false, error: 'loopback_only' })
        return false
      }
      if (!configured) {
        send(res, 503, { ok: false, error: 'bridge_not_configured' })
        return false
      }
      if (!goodToken(req, token)) {
        send(res, 401, { ok: false, error: 'unauthorized' })
        return false
      }
      return true
    }

    // Official Harness waterfall answerer. No locally invented permission result.
    // Only the no-I/O probe can be approved in the current isolated milestone.
    function companionApprovalAnswerer(request, next) {
      if (!approvalEnabled || request?.toolName !== 'dsh_live_approval_probe')
        return next()
      const task=tasks.get(bySession.get(String(request?.agent?.id??''))??'')
      if (!task || !task.conversation || task.agentRef!==request.agent ||
          FINAL_STATES.has(task.status) || task.status==='cancel_requested')
        return 'unavailable'
      if ([...approvalRequests.values()].some(x=>x.task_id===task.id))
        return 'unavailable'
      const request_id=randomUUID()
      return new Promise(resolve=>{
        let settled=false
        const finish=outcome=>{
          if(settled)return
          settled=true
          clearTimeout(timer)
          request.signal?.removeEventListener('abort',aborted)
          approvalRequests.delete(request_id)
          resolve(outcome)
        }
        const aborted=()=>finish('cancelled')
        const timer=setTimeout(()=>finish('unavailable'),120000)
        approvalRequests.set(request_id,{
          request_id,task_id:task.id,conversation_id:task.conversation,
          session_id:task.session,agent:request.agent,
          tool:'dsh_live_approval_probe',finish,
        })
        if(request.signal?.aborted)aborted()
        else request.signal?.addEventListener('abort',aborted,{once:true})
      })
    }

    // The native macOS CUA provider asks through the official User Questions
    // waterfall, not approval/request. Capture only an exact live computer
    // tool question, forward it to the authenticated Mac user, and never
    // choose a default answer or let a disconnected browser claim it.
    function scopedComputerQuestionAnswerer(request,next) {
      const agent=request?.agent
      const task=tasks.get(bySession.get(String(agent?.id??''))??'')
      const question=boundedComputerQuestion(request)
      if(!question || !task || task.agentRef!==agent ||
         !task.conversation || FINAL_STATES.has(task.status) ||
         task.status==='cancel_requested' ||
         ![...task.tools.values()].some(t=>t.name==='cua'&&t.outcome==='pending'))
        return next()
      if([...computerQuestions.values()].some(q=>q.task_id===task.id))
        return next()
      // R676: a previous explicit switch in Mac Preferences may authorize
      // only the exact built-in Finder/Chrome access request for this task.
      // No generic tool grant, no saved CUA permission, no macOS TCC bypass.
      const preauthorized=preapprovedNativeCuaChoice(request,localMacPreconsent())
      if(preauthorized)return Promise.resolve(preauthorized)
      const request_id=randomUUID()
      return new Promise((resolve,reject)=>{
        let settled=false
        const finish=(selection,reason=null)=>{
          if(settled)return
          settled=true
          clearTimeout(timer)
          request.signal?.removeEventListener('abort',aborted)
          computerQuestions.delete(request_id)
          task.computerQuestionOutstanding=false
          task.factRevision++
          rememberCompanionFact(task)
          if(reason)reject(new Error(reason))
          else resolve({answers:[{id:question.question_id,selected:[selection]}]})
        }
        const aborted=()=>finish(null,'cua_question_aborted')
        const timer=setTimeout(()=>finish(null,'cua_question_timeout'),105000)
        computerQuestions.set(request_id,{request_id,task_id:task.id,
          conversation_id:task.conversation,session_id:task.session,
          agent,question,finish})
        task.computerQuestionOutstanding=true
        task.factRevision++
        rememberCompanionFact(task)
        if(request.signal?.aborted)aborted()
        else request.signal?.addEventListener('abort',aborted,{once:true})
      })
    }

    function approvalOwner(body) {
      if(!body || body.protocolVersion!==PROTOCOL_VERSION ||
         typeof body.conversation_id!=='string' ||
         !CONVERSATION_ID.test(body.conversation_id))return null
      const binding=byConversation.get(body.conversation_id)
      const task=tasks.get(binding?.busy??'')
      return task?.session && !FINAL_STATES.has(task.status)?task:null
    }

    attach('/computer-question/pending',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      if(!body || body.protocolVersion!==PROTOCOL_VERSION ||
         typeof body.conversation_id!=='string' ||
         !CONVERSATION_ID.test(body.conversation_id) ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_computer_question_query'})
      const task=approvalOwner(body)
      const pending=task?[...computerQuestions.values()].find(q=>
        q.task_id===task.id && q.session_id===task.session &&
        q.agent===task.agentRef):null
      return send(res,200,{ok:true,pending:pending?{
        task_id:pending.task_id,request_id:pending.request_id,
        question_id:pending.question.question_id,
        question:pending.question.question,detail:pending.question.detail,
        header:pending.question.header,options:pending.question.options,
      }:null})
    })

    attach('/computer-question/decide',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      if(!body || body.protocolVersion!==PROTOCOL_VERSION ||
         typeof body.conversation_id!=='string' ||
         !CONVERSATION_ID.test(body.conversation_id) ||
         !['task_id','request_id','question_id','choice'].every(k=>
             typeof body[k]==='string' && body[k].length>0 && body[k].length<=160) ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id',
             'task_id','request_id','question_id','choice'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_computer_question_decision'})
      const task=approvalOwner(body)
      const q=computerQuestions.get(body.request_id)
      if(!task || !q || q.task_id!==task.id || q.agent!==task.agentRef ||
         q.session_id!==task.session || q.conversation_id!==body.conversation_id ||
         q.question.question_id!==body.question_id ||
         !q.question.options.includes(body.choice) ||
         !task.computerQuestionOutstanding)
        return send(res,409,{ok:false,error:'computer_question_no_longer_pending'})
      q.finish(body.choice)
      return send(res,202,{ok:true,submitted:true,
        message:'native_computer_question_answer_pending_confirmation'})
    })

    attach('/approval/pending',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      if(!approvalEnabled)return send(res,503,{ok:false,error:'approval_disabled'})
      const body=await readBody(req)
      if(!body || body.protocolVersion!==PROTOCOL_VERSION ||
         typeof body.conversation_id!=='string' || !CONVERSATION_ID.test(body.conversation_id) ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_approval_query'})
      const task=approvalOwner(body)
      const request=task?[...approvalRequests.values()].find(x=>
        x.task_id===task.id&&x.session_id===task.session):null
      return send(res,200,{ok:true,pending:request?{
        task_id:request.task_id,request_id:request.request_id,
        tool:request.tool,description:'仅返回内存测试标记，不读取或修改电脑',
        scope:'仅本次操作',
      }:null})
    })

    attach('/approval/decide',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      if(!approvalEnabled)return send(res,503,{ok:false,error:'approval_disabled'})
      const body=await readBody(req)
      if(!body || body.protocolVersion!==PROTOCOL_VERSION ||
         typeof body.conversation_id!=='string' || !CONVERSATION_ID.test(body.conversation_id) ||
         typeof body.task_id!=='string' || typeof body.request_id!=='string' ||
         !['allowed-once','rejected','cancelled'].includes(body.decision) ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id','task_id','request_id','decision'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_approval_decision'})
      const task=approvalOwner(body)
      const request=approvalRequests.get(body.request_id)
      if(!task || task.id!==body.task_id || !request ||
         request.task_id!==task.id || request.conversation_id!==body.conversation_id ||
         request.session_id!==task.session || request.agent!==task.agentRef ||
         !task.approvalOutstanding || !task.pendingApprovals.size)
        return send(res,409,{ok:false,error:'approval_no_longer_pending'})
      request.finish(body.decision)
      return send(res,202,{ok:true,submitted:true,
        message:'approval_decision_pending_native_confirmation'})
    })

    attach('/memory-manage', async (req,res) => {
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      if(!memoryVault)return send(res,503,{ok:false,error:'memory_not_enabled'})
      const admin=req.headers?.['x-dsh-live-memory-token']
      const wanted=Buffer.from(memoryAdmin)
      const actual=typeof admin==='string'?Buffer.from(admin):Buffer.alloc(0)
      if(actual.length!==wanted.length || !timingSafeEqual(actual,wanted))
        return send(res,403,{ok:false,error:'memory_admin_required'})
      const body=await readBody(req)
      if(!body||body.protocolVersion!==PROTOCOL_VERSION ||
          typeof body.action!=='string')
        return send(res,400,{ok:false,error:'memory_request_invalid'})
      const keys={
        list:['protocolVersion','action'],
        export:['protocolVersion','action'],
        read:['protocolVersion','action','id'],
        consent:['protocolVersion','action','allow','confirm'],
        put:['protocolVersion','action','id','text','expectedRevision'],
        remove:['protocolVersion','action','id','expectedRevision','confirm'],
        'growth.list':['protocolVersion','action','status'],
        'growth.version':['protocolVersion','action'],
        'growth.propose':['protocolVersion','action','text','turn_id','confirm'],
        'growth.decide':['protocolVersion','action','id','decision','expectedRevision','confirm'],
        'growth.rollback':['protocolVersion','action','toVersion','expectedRevision','confirm'],
        'growth.suggestion-consent':['protocolVersion','action','allow','expectedRevision','confirm'],
      }
      const allowed=keys[body.action]
      if(!allowed || Object.keys(body).some(key=>!allowed.includes(key)))
        return send(res,400,{ok:false,error:'memory_request_invalid'})
      try {
        if(body.action.startsWith('growth.')) {
          if(!growth)return send(res,503,{ok:false,error:'growth_disabled'})
          if(body.action==='growth.list')
            return send(res,200,{ok:true,candidates:growth.listCandidates(body.status??'new')})
          if(body.action==='growth.version')
            return send(res,200,{ok:true,...growth.version()})
          // Disabling suggestions is always allowed with admin auth. Turning them
          // ON still requires the existing manual-memory consent first.
          if(body.action==='growth.suggestion-consent') {
            if(body.confirm!=='GROWTH_SUGGESTIONS_CONSENT')
              return send(res,400,{ok:false,error:'growth_confirmation_required'})
            if(body.allow===true && !memoryVault.list().consent.manual_write)
              return send(res,403,{ok:false,error:'memory_user_consent_required'})
            return send(res,200,{ok:true,...growth.setSuggestionConsent({
              allow:body.allow,expectedRevision:body.expectedRevision,confirmed:true,
            })})
          }
          // Even staging an explicit user proposal requires existing consent.
          if(!memoryVault.list().consent.manual_write)
            return send(res,403,{ok:false,error:'memory_user_consent_required'})
          if(body.action==='growth.propose') {
            if(body.confirm!=='USER_EXPLICIT_GROWTH_PROPOSAL')
              return send(res,400,{ok:false,error:'growth_confirmation_required'})
            return send(res,200,{ok:true,...growth.propose({
              text:body.text,turn_id:body.turn_id??null,source:'user_explicit',
            })})
          }
          if(body.action==='growth.decide') {
            if(body.confirm!==(
              body.decision==='accept'?'ACCEPT_GROWTH_FACT':'REJECT_GROWTH_FACT'))
              return send(res,400,{ok:false,error:'growth_confirmation_required'})
            return send(res,200,{ok:true,...growth.decide({
              id:body.id,decision:body.decision,
              expectedRevision:body.expectedRevision,confirmed:true,
            })})
          }
          if(body.action==='growth.rollback') {
            if(body.confirm!=='ROLLBACK_GROWTH_VERSION')
              return send(res,400,{ok:false,error:'growth_confirmation_required'})
            return send(res,200,{ok:true,...growth.rollback({
              toVersion:body.toVersion,expectedRevision:body.expectedRevision,
              confirmed:true,
            })})
          }
        }
        if(body.action==='list')return send(res,200,{ok:true,...memoryVault.list()})
        if(body.action==='export')return send(res,200,{ok:true,...memoryVault.exportAll()})
        if(body.action==='read')return send(res,200,{ok:true,fact:memoryVault.read(body.id)})
        if(body.action==='consent') {
          if(body.confirm!=='MANUAL_MEMORY_CONSENT'||typeof body.allow!=='boolean')
            return send(res,400,{ok:false,error:'memory_confirmation_required'})
          memoryVault.setManualConsent(body.allow)
          return send(res,200,{ok:true,consent:memoryVault.list().consent})
        }
        if(body.action==='put') {
          if(body.id!==undefined && typeof body.id!=='string')
            return send(res,400,{ok:false,error:'memory_request_invalid'})
          const {id,...fact}=body
          const value=memoryVault.put({id, ...fact})
          return send(res,200,{ok:true,...value})
        }
        if(body.action==='remove') {
          if(body.confirm!=='DELETE_THIS_FACT')
            return send(res,400,{ok:false,error:'memory_confirmation_required'})
          return send(res,200,{ok:true,...memoryVault.remove(body.id,body.expectedRevision)})
        }
      } catch(err) {
        const message=err?.message||''
        if(message==='memory_user_consent_required')
          return send(res,403,{ok:false,error:message})
        if(message==='memory_revision_conflict'||message==='growth_revision_conflict')
          return send(res,409,{ok:false,error:message})
        if(message.startsWith('growth_'))
          return send(res,400,{ok:false,error:message})
        if(['memory_unknown_id','memory_invalid_fact'].includes(message))
          return send(res,400,{ok:false,error:message})
        return send(res,503,{ok:false,error:'memory_unavailable'})
      }
    })

    attach('/health', async (req, res) => {
      if (req.method !== 'GET') return send(res, 405, { ok: false, error: 'method_not_allowed' })
      if (!isLoopback(req)) return send(res, 403, { ok: false, error: 'loopback_only' })
      send(res, 200, { ok: true, protocolVersion: PROTOCOL_VERSION, configured,
        ...(personaEngine ? {persona:{
          ...personaMetadata(),
          warning_count:personaEngine.health().warning_count,
        }} : {}),
        ...(growth ? {growth:growth.version()} : {}) })
    })

    function sessionModel(binding) {
      // Next-request selection belongs to Harness's installed Agent-scoped
      // model-selection hook; last_request is from the durable native header.
      const next = binding.selection.current
      const last = binding.agent.session?.requestHeader?.()?.config
      return {
        selected: next ? { ...next } : null,
        last_request: last?.provider && last?.model
          ? { provider: last.provider, model: last.model } : null,
        pending_next_request: !!next && (!last ||
          next.provider !== last.provider || next.model !== last.model),
      }
    }

    async function createBinding(conversation,{speechOnly=false}={}) {
      const recorded = conversation ? ledger?.binding(conversation) : null
      const resume = !speechOnly && !!recorded && !recorded.expired
      let selected = resume ? recorded.selected : ctx.agentDefaultModel.currentSelection()
      if (typeof selected?.provider !== 'string' || !selected.provider ||
          typeof selected?.model !== 'string' || !selected.model) {
        throw new Error('harness_default_model_unavailable')
      }
      if(speechOnly) {
        const route=await ctx.llm.resolveCallConfig({provider:selected.provider,model:'deepseek-flash'})
        if(route?.provider!==selected.provider || route.model!=='deepseek-flash')
          throw new Error('speech_flash_model_unavailable')
        selected={provider:route.provider,model:route.model}
      }
      const selection = { current: { ...selected }, assembled: undefined }
      // Native product mode inherits official Harness tools without a whitelist.
      // Keep the existing read-only/limited profile for isolated experiments.
      const nativeTools = (process.env.DSH_LIVE_TOOL_MODE || config.toolMode) === 'native'
      const safeMacTools = process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL === '1'
      if (nativeTools && safeMacTools)
        throw new Error('native_mode_conflicts_with_isolated_readonly_scope')
      const nativeWebSearch = !nativeTools && process.env.DSH_LIVE_ENABLE_WEB_SEARCH === '1'
      const search = {supported:false,enabled:false,names:[],mask:null,tools:null}
      // Inspect the *bound Agent's* actual tool scope; MCP process startup
      // alone never proves the voice Agent can invoke Pinky.
      const phone = {scoped_checked:false,visible:false,tool_count:0,tools:null}
      // R540: use all Pinky tools at their NORMAL installed permissions,
      // but no ambient phone access outside an actual authenticated ESP
      // voice turn requesting a phone task. Pinky owns its own rules and
      // human approval; this Bridge neither grants nor bypasses those rules.
      const phonePolicy={guardDispose:null}
      if(nativeTools && resume && recorded.web_search_enabled === true)
        search.enabled = true
      if (nativeWebSearch && !safeMacTools)
        throw new Error('native_web_search_requires_scoped_tool_policy')
      const memoryEnabled = process.env.DSH_LIVE_ENABLE_REME_SEARCH === '1'
      if (memoryEnabled && !safeMacTools) throw new Error('memory_requires_readonly_scope')
      const memoryEndpoint = memoryEnabled ? process.env.DSH_LIVE_REME_URL : null
      const setup = async (agentCtx, agent) => {
        // DSH's AgentRegistry does not mount agent presets implicitly.
        // Use the project's Web-only preset, not the default standard preset
        // (which also grants shell and filesystem tools).
        if (!speechOnly && nativeTools && config.webPresetId) {
          const presets = typeof ctx.get === 'function' && ctx.get('agentPresets')
          if (typeof presets?.mount !== 'function')
            throw new Error('native_web_preset_service_unavailable')
          await presets.mount(agentCtx, config.webPresetId)
        }
        if(speechOnly) {
          const tools=agentCtx.tools
          if(typeof tools?.restrict!=='function'||typeof tools?.guard!=='function'||
             typeof tools?.schemas!=='function')
            throw new Error('speech_scope_guard_unavailable')
          tools.restrict({allow:[]})
          tools.guard(()=> 'speech_only_tool_forbidden')
          if(tools.schemas(agent).length)throw new Error('speech_scoped_tool_visible')
        }
        installModelSelection(agentCtx, selection)
        // The official ApprovalService routes its request to the Agent scope.
        // Prepend before built-in browser forwarding so a disconnected
        // official Web client cannot hold this isolated no-I/O decision.
        if (approvalEnabled && !speechOnly) agentCtx.on('approval/request',companionApprovalAnswerer,{prepend:true})
        if (nativeTools && !speechOnly) agentCtx.on('user-questions/request',scopedComputerQuestionAnswerer,{prepend:true})
        if(personaEngine) {
          if(typeof agentCtx.systemPrompt?.section!=='function'||
             typeof agentCtx.systemPrompt?.getSectionOrder!=='function')
            throw new Error('native_persona_scope_unavailable')
          const first=agentCtx.systemPrompt.getSectionOrder('DEPLOYMENT_PERSONA_PREFIX')+1
          if(speechOnly) {
            // Compact speech identity; no tools, unchanged Flash maxTokens.
            agentCtx.systemPrompt.section({
              name:'dsh-live:whale-voice',
              order:first,text:personaEngine.voice,
            })
          } else {
            // Core and style live in this Agent's prompt scope, not globally.
            // Function texts re-read the safe snapshot on each assembly.
            agentCtx.systemPrompt.section({
              name:'dsh-live:whale-core',
              order:first,text:personaEngine.core,
            })
            agentCtx.systemPrompt.section({
              name:'dsh-live:whale-style',
              order:first+1,text:personaEngine.style,
            })
            // P1 dynamic channel: bounded current source/version facts only.
            // Approved long-term memory and candidate growth come later.
            if(typeof agentCtx.systemPrompt.context==='function' &&
               typeof agentCtx.systemPrompt.getContextOrder==='function'){
              agentCtx.systemPrompt.context({
                name:'dsh-live:whale-dynamic',
                order:agentCtx.systemPrompt.getContextOrder('WEB_SURFACE')+1,
                text:approvedGrowthContext,
              })
            }
          }
        }
        if (safeMacTools && !speechOnly) installReadonlyScope(agentCtx, root, memoryEndpoint, nativeWebSearch)
        if (nativeTools && !speechOnly) {
          if (typeof agentCtx.tools?.schemas !== 'function' ||
              typeof agentCtx.tools?.restrict !== 'function')
            throw new Error('native_scoped_search_api_unavailable')
          // The real DSH registry requires the owning Agent as its viewing scope.
          // Calling schemas() unscoped inspects only globally visible tools
          // and can miss (or falsely report) preset-scoped tools.
          // R540: user explicitly requested full Pinky permissions. Do NOT
          // install R538's blanket deny mask; real Pinky approvals still apply.
          // Retain the per-turn phone-intent guard and original Web preset.
          if(typeof agentCtx.tools.guard!=='function')
            throw new Error('r538_phone_execution_guard_unavailable')
          // R542: permission is derived from the EXACT official task owner,
          // not a free-standing mutable flag. R540 could lose its flag after
          // an Agent resume/rebind and then deny the legitimate phone_connect.
          // The task must be live, accepted as phone-scoped, and running on
          // this very Agent and conversation. Native Pinky approvals still apply.
          // A repeated setup/resume on the same native Agent must not stack
          // two guards with conflicting per-turn ownership snapshots.
          try {phonePolicy.guardDispose?.()} catch {}
          phonePolicy.guardDispose=null
          const undoPhoneGuard=agentCtx.tools.guard(exec=>{
            if(typeof exec?.name!=='string' ||
               !exec.name.startsWith('mcp__pinky_dafeiyu__'))return undefined
            const owner=tasks.get(bySession.get(String(agent.id)))
            const bound=byConversation.get(conversation)
            if(!owner || !bound || owner.agentRef!==agent ||
               owner.session!==String(agent.id) ||
               owner.conversation!==conversation ||
               bound.agent!==agent || bound.busy!==owner.id ||
               FINAL_STATES.has(owner.status) ||
               !(owner.phoneMode==='pinky' && owner.phonePolicyApplied===true ||
                 owner.phoneMode==='readonly' && owner.phoneMaskApplied===true))
              return 'r542_phone_turn_owner_required'
            return undefined
          })
          if(typeof undoPhoneGuard==='function')
            phonePolicy.guardDispose=undoPhoneGuard
          const installed = new Set(agentCtx.tools.schemas(agent).map(x=>x.name))
          phone.scoped_checked=true
          phone.tools=agentCtx.tools
          phone.tool_count=[...installed].filter(x=>
            /^mcp__pinky_dafeiyu__phone_[a-z_]+$/.test(x)).length
          phone.visible=phone.tool_count>0
          search.supported = installed.has('web_search')
          search.names = ['web_search','web_fetch'].filter(x=>installed.has(x))
          search.tools = agentCtx.tools
          if(!search.supported)search.enabled=false
          if(search.supported && !search.enabled)
            search.mask=search.tools.restrict({deny:search.names})
        }
      }
      let handle
      if (resume) {
        if (typeof ctx.agents.resume !== 'function') throw new Error('native_session_resume_unavailable')
        // Never silently create a new session if persisted history cannot load.
        await ctx.llm.resolveCallConfig(selected)
        handle = await ctx.agents.resume({
          resumeSessionId: recorded.session_id,
          agentOptions: {provider:selected.provider,model:selected.model,
            ...(speechOnly ? {maxTokens:320}: safeMacTools ? {maxTokens:512}: {})},
          setup,
        })
        // A native Session event outranks cached metadata if a model append was
        // durable before our ledger update. Don't rewrite the Session here.
        const events=handle.agent.session?.events
        const native = Array.isArray(events)
          ? [...events].reverse().find(x => x.type === 'model/selection')?.data : null
        if (typeof native?.provider === 'string' && typeof native?.model === 'string') {
          selection.current = { ...native }
        }
      } else {
        handle = await ctx.agents.create({
          sessionId:randomUUID(),
          agentOptions:{provider:selected.provider,model:selected.model,
            ...(speechOnly ? {maxTokens:320}: safeMacTools ? {maxTokens:512}: {})},
          meta:{cwd:root},
          setup,
        })
        handle.agent.session.append('model/selection',{...selected})
      }
      try {
        if (conversation && ledger && !speechOnly) ledger.putBinding(conversation,
          String(handle.agent.id),selection.current)
      } catch(err) {
        try {phonePolicy.guardDispose?.()} catch {}
        if (typeof handle.dispose === 'function') await handle.dispose()
        throw err
      }
      return {conversation,handle,agent:handle.agent,selection,search,phone,phonePolicy,nativeTools,speechOnly,
        persona:personaMetadata(speechOnly),busy:null,switching:false}
    }

    // Explicit text-only Flash scope; no model generation during capabilities
    // or bind. The token remains on localhost Mac; no ESP32 access.
    attach('/speech-capabilities',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      if(body?.protocolVersion!==PROTOCOL_VERSION ||
         Object.keys(body).some(k=>k!=='protocolVersion'))
        return send(res,400,{ok:false,error:'invalid_speech_capabilities'})
      return send(res,200,{ok:true,model:'deepseek-flash',tools_denied:true})
    })
    attach('/speech-bind',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      const id=body?.conversation_id
      if(body?.protocolVersion!==PROTOCOL_VERSION ||
         !CONVERSATION_ID.test(id??'') || !id.startsWith('speech_') ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_speech_binding'})
      if(endedConversations.has(id))return send(res,410,{ok:false,error:'session_ended'})
      if(pendingConversations.has(id))return send(res,409,{ok:false,error:'session_busy'})
      let binding=byConversation.get(id)
      if(binding && !binding.speechOnly)
        return send(res,409,{ok:false,error:'speech_binding_conflict'})
      if(!binding) {
        if(byConversation.size+pendingConversations.size>=MAX_CONVERSATIONS)
          return send(res,429,{ok:false,error:'session_capacity_reached'})
        pendingConversations.add(id)
        try {
          binding=await createBinding(id,{speechOnly:true})
          byConversation.set(id,binding)
        }catch{
          return send(res,503,{ok:false,error:'speech_scope_unavailable'})
        }finally{pendingConversations.delete(id)}
      }
      return send(res,200,{ok:true,conversation_id:id,session_id:binding.agent.id,
        selected:{...binding.selection.current},pending_resume:false,
        speech_only:true,tools_denied:true})
    })

    // Free, scoped binding handshake for the local P1 adapter. No LLM call.
    attach('/bind', async (req,res) => {
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      if(body?.protocolVersion!==PROTOCOL_VERSION ||
         !CONVERSATION_ID.test(body?.conversation_id ?? '') ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_bind'})
      const id=body.conversation_id
      if(id.startsWith('speech_'))return send(res,403,{ok:false,error:'speech_requires_isolated_bind'})
      if(endedConversations.has(id))return send(res,410,{ok:false,error:'session_ended'})
      if(pendingConversations.has(id))return send(res,409,{ok:false,error:'session_busy'})
      let binding=byConversation.get(id)
      if(!binding){
        if(byConversation.size+pendingConversations.size>=MAX_CONVERSATIONS)
          return send(res,429,{ok:false,error:'session_capacity_reached'})
        pendingConversations.add(id)
        try {
          binding=await createBinding(id)
          byConversation.set(id,binding)
        } catch {
          return send(res,503,{ok:false,error:'session_bind_failed'})
        } finally {pendingConversations.delete(id)}
      }
      return send(res,200,{ok:true,conversation_id:id,
        session_id:binding.agent.id,...sessionModel(binding),
        pending_resume:false,busy:!!binding.busy,
        search_supported:binding.search.supported,search_enabled:binding.search.enabled})
    })

    // R539 strictly free Native ToolRegistry mask inspection. The earlier
    // real R538 read-only turn failed in <100 ms before any Pinky tool call;
    // test the EXACT bound Agent's temporary mask without submitting a model
    // request, installing a tool, or accessing the user's phone.
    attach('/phone-readonly-preflight',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      if(body?.protocolVersion!==PROTOCOL_VERSION ||
         !CONVERSATION_ID.test(body?.conversation_id??'') ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_phone_readonly_preflight'})
      const binding=byConversation.get(body.conversation_id)
      if(!binding)return send(res,404,{ok:false,error:'unknown_conversation'})
      if(binding.busy || binding.switching || binding.agent.status==='running' ||
         pendingConversations.has(body.conversation_id))
        return send(res,409,{ok:false,error:'session_busy'})
      let undo=null
      try {
        undo=scopedReadOnlyPhoneTools(binding)
        const enabled=binding.phone.tools.schemas(binding.agent).filter(x=>
          /^mcp__pinky_dafeiyu__phone_[a-z_]+$/.test(x?.name??'')).length
        return send(res,200,{ok:true,scoped_checked:true,
                             readonly_mask_verified:true,safe_phone_tool_count:enabled,
                             actual_phone_tools_executed:0,model_turns_created:0})
      } catch(err) {
        const known=new Set(['r538_pinky_native_scope_missing','r538_readonly_tools_missing',
                             'r538_readonly_mask_cannot_be_removed',
                             'r538_readonly_mask_not_enforced'])
        const code=known.has(err?.message)?err.message:'r539_unexpected_tool_scope_failure'
        return send(res,409,{ok:false,error:code,
                             actual_phone_tools_executed:0,model_turns_created:0})
      } finally {
        try{undo?.()}catch{}
      }
    })

    // R540 no-model, no-phone-task proof of the LIVE native Agent's Pinky
    // catalog. Never expose tool arguments, screen text or phone identifiers.
    attach('/phone-policy-capabilities',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      if(body?.protocolVersion!==PROTOCOL_VERSION ||
         !CONVERSATION_ID.test(body?.conversation_id??'') ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_phone_policy_capabilities'})
      const binding=byConversation.get(body.conversation_id)
      if(!binding)return send(res,404,{ok:false,error:'unknown_conversation'})
      if(!binding.nativeTools || !binding.phone?.scoped_checked)
        return send(res,409,{ok:false,error:'phone_native_scope_missing'})
      const names=new Set(binding.phone.tools.schemas(binding.agent)
        .map(x=>x?.name).filter(x=>typeof x==='string'))
      const count=[...names].filter(x=>x.startsWith('mcp__pinky_dafeiyu__phone_')).length
      const required=['phone_connect','phone_observe','phone_launch','phone_tap',
                      'phone_task_run','phone_request_approval']
      const full=count>=20 && required.every(t=>
        names.has('mcp__pinky_dafeiyu__'+t))
      return send(res,200,{ok:true,agent_tools_native:true,
        pinky_policy_available:full,pinky_tool_count:count,
        foreground_screen_read_available:names.has('mcp__pinky_dafeiyu__phone_observe'),
        app_launch_available:names.has('mcp__pinky_dafeiyu__phone_launch'),
        // Pinky's own phone approvals remain enforced at execution time.
        approval_decisions_bypassed:false,phone_tools_executed:0,model_turns_created:0})
    })

    // R519 authenticated read-only evidence of the real, bound Agent's MCP
    // scope. No phone action, no model call, no raw tool names/token exposure.
    attach('/phone-capabilities',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      if(body?.protocolVersion!==PROTOCOL_VERSION ||
         !CONVERSATION_ID.test(body?.conversation_id??'') ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_phone_capabilities'})
      const binding=byConversation.get(body.conversation_id)
      if(!binding)return send(res,404,{ok:false,error:'unknown_conversation'})
      const phone=binding.phone
      // Recheck live tool membership: an MCP server can reconnect after
      // Agent setup and should not leave a stale green capability receipt.
      let count=0
      if(phone?.scoped_checked && typeof phone.tools?.schemas==='function'){
        try{
          count=phone.tools.schemas(binding.agent).filter(x=>
            /^mcp__pinky_dafeiyu__phone_[a-z_]+$/.test(x?.name??'')).length
        }catch{
          return send(res,503,{ok:false,error:'phone_scope_unavailable'})
        }
      }
      return send(res,200,{ok:true,scoped_checked:phone?.scoped_checked===true,
        agent_tools_native:binding.nativeTools===true,
        pinky_dafeiyu_visible:count>0,
        pinky_tool_count:count})
    })

    // Discover the bound provider's actual native catalog, like official DSH
    // Session Controller. A legacy visibleModels allowlist must not hide Pro.
    // Read-only provider metadata; no model generation or global selection.
    attach('/models', async (req,res) => {
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      if(body?.protocolVersion!==PROTOCOL_VERSION ||
         Object.keys(body).some(k=>k!=='protocolVersion'))
        return send(res,400,{ok:false,error:'invalid_model_query'})
      const selected=ctx.agentDefaultModel.currentSelection()
      if(!selected?.provider||!selected?.model)
        return send(res,503,{ok:false,error:'model_route_unavailable'})
      let discovered
      try {
        discovered=await ctx.llm.listModels(selected.provider)
      } catch {
        return send(res,503,{ok:false,error:'model_catalog_unavailable'})
      }
      if(!Array.isArray(discovered))
        return send(res,503,{ok:false,error:'model_catalog_unavailable'})
      const models=[]
      for(const candidate of discovered) {
        if(models.length>=12)break
        if(candidate?.provider!==selected.provider || !MODEL_ID.test(candidate?.id ?? '') ||
           models.some(x=>x.id===candidate.id))continue
        try{
          const resolved=await ctx.llm.resolveCallConfig({
            provider:selected.provider,model:candidate.id
          })
          if(resolved?.provider===selected.provider && resolved?.model===candidate.id)
            models.push({id:candidate.id,
              name:typeof candidate.name==='string' && candidate.name.trim()
                ? candidate.name.trim().slice(0,100) : candidate.id})
        }catch{}
      }
      if(!models.length || !models.some(x=>x.id===selected.model))
        return send(res,503,{ok:false,error:'model_route_unavailable'})
      return send(res,200,{ok:true,models,default:selected.model,
        source:'dsh-native-provider-catalog-no-call'})
    })

    // A deliberate user-ended conversation invalidates the binding, scrubs
    // cached reply text, but never claims to have removed native DSH files.
    // Native cleanup must follow the separate shutdown/ownership policy.
    attach('/end',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      if(body?.protocolVersion!==PROTOCOL_VERSION ||
         !CONVERSATION_ID.test(body?.conversation_id??'') ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_end'})
      const id=body.conversation_id
      const binding=byConversation.get(id)
      if(pendingConversations.has(id)||binding?.busy||binding?.switching||
         binding?.agent.status==='running'||
         [...tasks.values()].some(task=>task.conversation===id&&!FINAL_STATES.has(task.status)))
        return send(res,409,{ok:false,error:'session_busy'})
      try{
        ledger?.endConversation(id)
      }catch{
        return send(res,409,{ok:false,error:'session_pending_turn'})
      }
      if(binding){
        try{await binding.handle?.dispose?.()}catch{
          return send(res,503,{ok:false,error:'session_dispose_failed'})
        }
        byConversation.delete(id)
        bySession.delete(String(binding.agent.id))
      }
      for(const [taskId,task] of tasks) if(task.conversation===id){
        tasks.delete(taskId)
        byTurn.delete(task.turn)
        bySession.delete(String(task.session))
      }
      endedConversations.add(id)
      return send(res,200,{ok:true,session_ended:true,
        native_artifacts:'pending_cleanup',backup_artifacts:'not_verified'})
    })

    attach('/session', async (req, res) => {
      if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'method_not_allowed' })
      if (!protect(req, res)) return
      const body = await readBody(req)
      if (body?.protocolVersion !== PROTOCOL_VERSION ||
          !CONVERSATION_ID.test(body?.conversation_id ?? '') ||
          Object.keys(body).some((key) => !['protocolVersion', 'conversation_id'].includes(key))) {
        return send(res, 400, { ok: false, error: 'invalid_session_query' })
      }
      const binding = byConversation.get(body.conversation_id)
      if (!binding) {
        const recorded=ledger?.binding(body.conversation_id)
        if (!recorded || recorded.expired)
          return send(res, 404, {ok:false,error:'unknown_conversation'})
        return send(res,200,{ok:true,conversation_id:body.conversation_id,
          session_id:recorded.session_id,selected:{...recorded.selected},
          last_request:null,pending_next_request:true,
          pending_resume:true,busy:false,
          search_supported:false,search_enabled:recorded.web_search_enabled===true})
      }
      send(res, 200, {
        ok: true, conversation_id: body.conversation_id,
        session_id: binding.agent.id, ...sessionModel(binding),
        pending_resume:false,busy:!!binding.busy,
        search_supported:binding.search.supported,search_enabled:binding.search.enabled,
      })
    })

    // Per-Session native search preference: no new model call, no Host-wide
    // permission changes, no bypass of built-in approval or global guards.
    attach('/search',async(req,res)=>{
      if(req.method!=='POST')return send(res,405,{ok:false,error:'method_not_allowed'})
      if(!protect(req,res))return
      const body=await readBody(req)
      if(body?.protocolVersion!==PROTOCOL_VERSION ||
         !CONVERSATION_ID.test(body?.conversation_id??'') ||
         (body.enabled!==undefined && typeof body.enabled!=='boolean') ||
         Object.keys(body).some(k=>!['protocolVersion','conversation_id','enabled'].includes(k)))
        return send(res,400,{ok:false,error:'invalid_search_preference'})
      const binding=byConversation.get(body.conversation_id)
      if(!binding)return send(res,404,{ok:false,error:'unknown_conversation'})
      const state=()=>({ok:true,session_id:binding.agent.id,
        supported:binding.search.supported,enabled:binding.search.enabled,
        source:'harness-agent-scoped-tools'})
      if(body.enabled===undefined)return send(res,200,state())
      if(!binding.nativeTools || !binding.search.supported)
        return send(res,409,{ok:false,error:'native_search_unavailable'})
      if(binding.busy || binding.switching || binding.agent.status==='running')
        return send(res,409,{ok:false,error:'session_busy'})
      const search=binding.search
      if(search.enabled===body.enabled)return send(res,200,state())
      try {
        if(body.enabled) {search.mask?.();search.mask=null}
        else search.mask=search.tools.restrict({deny:search.names})
        search.enabled=body.enabled
        ledger?.putBinding(binding.conversation,String(binding.agent.id),
          binding.selection.current,search.enabled)
      } catch {
        // A failed persistence step must not silently claim a new preference.
        try {
          if(body.enabled && !search.mask)
            search.mask=search.tools.restrict({deny:search.names})
          else if(!body.enabled && search.mask) {search.mask();search.mask=null}
        }catch{}
        search.enabled=!body.enabled
        if(!search.enabled && !search.mask)
          return send(res,503,{ok:false,error:'search_scope_unknown_disable_agent'})
        return send(res,503,{ok:false,error:'search_preference_not_committed'})
      }
      return send(res,200,state())
    })

    attach('/model', async (req, res) => {
      if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'method_not_allowed' })
      if (!protect(req, res)) return
      const body = await readBody(req)
      if (body?.protocolVersion !== PROTOCOL_VERSION ||
          !CONVERSATION_ID.test(body?.conversation_id ?? '') ||
          !MODEL_ID.test(body?.model ?? '') ||
          Object.keys(body).some((key) =>
            !['protocolVersion', 'conversation_id', 'model'].includes(key))) {
        return send(res, 400, { ok: false, error: 'invalid_model_selection' })
      }
      const binding = byConversation.get(body.conversation_id)
      if (!binding) return send(res, 404, { ok: false, error: 'unknown_conversation' })
      if(binding.speechOnly)return send(res,403,{ok:false,error:'speech_model_fixed'})
      if (binding.busy || binding.switching || binding.agent.status === 'running') {
        return send(res, 409, { ok: false, error: 'session_busy' })
      }
      // The provider is inherited from this bound Session. A caller may not
      // change provider, cwd, agent, credential, approval, or global defaults.
      const current = binding.selection.current
      const requested = { provider: current.provider, model: body.model }
      let resolved
      binding.switching = true
      try {
        resolved = await ctx.llm.resolveCallConfig(requested)
        if (resolved.provider !== requested.provider || resolved.model !== requested.model) {
          throw new Error('model_route_changed')
        }
      } catch {
        binding.switching = false
        return send(res, 422, { ok: false, error: 'harness_model_unavailable',
          session_id: binding.agent.id, ...sessionModel(binding) })
      }
      // Only native session append + official Agent-scoped selection.
      // NEVER call sessionController.selectModel(): it saves the global default.
      const selected = { provider: resolved.provider, model: resolved.model,
        ...(resolved.reasoningEffort === undefined ? {} :
          { reasoningEffort: resolved.reasoningEffort }) }
      try {
        binding.agent.session.append('model/selection', selected)
        binding.selection.current = selected
        if (ledger && binding.conversation) ledger.putBinding(binding.conversation,
          String(binding.agent.id), selected)
      } catch {
        binding.switching = false
        return send(res, 503, { ok: false, error: 'session_model_commit_failed',
          session_id: binding.agent.id, ...sessionModel(binding) })
      }
      binding.switching = false
      send(res, 200, { ok: true, conversation_id: body.conversation_id,
        session_id: binding.agent.id, ...sessionModel(binding) })
    })

    attach('/submit', async (req, res) => {
      if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'method_not_allowed' })
      if (!protect(req, res)) return
      const body = await readBody(req)
      if (body?.protocolVersion !== PROTOCOL_VERSION ||
          !TURN_ID.test(body?.turn_id ?? '') ||
          typeof body.prompt !== 'string' ||
          !body.prompt.trim() || body.prompt.length > MAX_PROMPT ||
          (body.conversation_id !== undefined && !CONVERSATION_ID.test(body.conversation_id)) ||
          (body.phone_read_only !== undefined && body.phone_read_only !== true) ||
          (body.phone_policy !== undefined && body.phone_policy !== 'pinky') ||
          (body.phone_policy !== undefined && body.phone_read_only !== undefined) ||
          Object.keys(body).some((key) => !['protocolVersion', 'turn_id', 'prompt',
            'conversation_id', 'phone_read_only', 'phone_policy'].includes(key))) {
        return send(res, 400, { ok: false, error: 'invalid_submit' })
      }
      const prompt = body.prompt.trim()
      const phoneMode=body.phone_policy==='pinky'?'pinky':
                      body.phone_read_only===true?'readonly':null
      const savedTurn = ledger?.getTurn(body.turn_id)
      const previousId = byTurn.get(body.turn_id)
      if (previousId) {
        const previous = tasks.get(previousId)
        if (previous.prompt !== prompt ||
            previous.conversation !== (body.conversation_id ?? null) ||
            previous.phoneMode !== phoneMode) {
          return send(res, 409, { ok: false, error: 'turn_payload_changed' })
        }
        // Once received, retries only read previous state; NEVER followup twice.
        return send(res, 200, { ok: true, idempotent: true, ...publicRecord(previous) })
      }
      if (savedTurn) {
        // The old persistence schema has no proof of the R538 read-only
        // guard. A replay after Host restart must NEVER be treated as a
        // fresh safe phone operation or inherit a different execution scope.
        if (phoneMode!==null)
          return send(res,409,{ok:false,error:'r540_phone_turn_scope_unknown',
            task_id:savedTurn.task_id,turn_id:body.turn_id})
        if (savedTurn.status==='ended')
          return send(res,410,{ok:false,error:'session_ended'})
        if (savedTurn.digest !== turnDigest(body.conversation_id ?? null, prompt))
          return send(res, 409, {ok:false,error:'turn_payload_changed'})
        if (!FINAL_STATES.has(savedTurn.status)) {
          // Never blindly redrive an interrupted/unknown tool execution.
          return send(res, 409, {ok:false,error:'turn_outcome_unknown',
            task_id:savedTurn.task_id,turn_id:body.turn_id})
        }
        return send(res,200,{ok:true,idempotent:true,...savedPublicRecord(savedTurn)})
      }
      const active = [...tasks.values()].filter((task) => !FINAL_STATES.has(task.status)).length
      if (active >= MAX_ACTIVE || tasks.size >= MAX_REMEMBERED) {
        return send(res, 429, { ok: false, error: 'capacity_reached' })
      }

      const conversation = body.conversation_id ?? null
      if(conversation?.startsWith('speech_') && !byConversation.get(conversation)?.speechOnly)
        return send(res,403,{ok:false,error:'speech_requires_isolated_bind'})
      let binding = conversation ? byConversation.get(conversation) : null
      if (phoneMode!==null && (!conversation || !binding ||
          !binding.nativeTools || !binding.phone?.scoped_checked || !binding.phone?.visible))
        return send(res,409,{ok:false,error:'r540_phone_scope_unavailable'})
      if (pendingConversations.has(conversation) || binding?.busy || binding?.switching ||
          binding?.agent.status === 'running') {
        return send(res, 409, { ok: false, error: 'session_busy' })
      }
      if (conversation && endedConversations.has(conversation)) {
        return send(res,410,{ok:false,error:'session_ended'})
      }
      if (conversation && !binding &&
          byConversation.size + pendingConversations.size >= MAX_CONVERSATIONS) {
        return send(res, 429, { ok: false, error: 'session_capacity_reached' })
      }
      const task = {
        id: randomUUID(), turn: body.turn_id, prompt, conversation,
        session: null, status: 'accepted', text: '', idleSeen: false,
        approvalOutstanding: false, pendingApprovals: new Set(), approvalRejected: false,
        approvalDenialOutcome: null,
        turnEnd: null, tools: new Map(),
        textAfterTools: false, failure: null, agentRef: null,
        reasoningObserved: false, factRevision: 0, speechPrewarm: null,
        phoneMode,phoneMaskApplied:false,phoneMask:null,
        phonePolicyApplied:false,
      }
      if (ledger) {
        // The admission record precedes native execution; unknown after crash
        // means unknown, not a license to retry an external tool.
        try {ledger.reserveTurn(task.turn,conversation,prompt,task.id)}
        catch {return send(res,503,{ok:false,error:'session_turn_ledger_unavailable'})}
      }
      tasks.set(task.id, task)
      byTurn.set(task.turn, task.id)
      try {
        // Session stays bound to this conversation; no per-turn agent recreation.
        // Legacy callers with no conversation_id retain the v0.3 semantics.
        if (!binding) {
          if (conversation) pendingConversations.add(conversation)
          try {
            binding = await createBinding(conversation)
            if (conversation) byConversation.set(conversation, binding)
          } finally {
            if (conversation) pendingConversations.delete(conversation)
          }
        }
        task.session = String(binding.agent.id)
        task.persona = personaMetadata(binding.speechOnly)
        rememberCompanionFact(task)
        task.agentRef = binding.agent
        binding.busy = task.id
        bySession.set(task.session, task.id)
        if(task.phoneMode==='readonly') {
          // Backward-compatible R538 legacy read-only route, without global
          // blanket deny. Normal R540 voice requests use full Pinky rules.
          task.phoneMask=scopedReadOnlyPhoneTools(binding)
          task.phoneMaskApplied=true

        } else if(task.phoneMode==='pinky') {
          // Real Agent scope, NOT process-level MCP discovery. No extra tools
          // granted, no approvals bypassed, no duplicate agent or task.
          const names=new Set(binding.phone.tools.schemas(binding.agent)
            .map(x=>x?.name).filter(x=>typeof x==='string'))
          const must=['phone_connect','phone_observe','phone_launch','phone_tap',
                      'phone_task_run','phone_request_approval']
          if(!must.every(x=>names.has('mcp__pinky_dafeiyu__'+x)) ||
             [...names].filter(x=>x.startsWith('mcp__pinky_dafeiyu__phone_')).length<20)
            throw new Error('r540_full_pinky_catalog_unavailable')
          task.phonePolicyApplied=true

        }
        // Refresh the recovery window before delivering any native side effect.
        if (conversation) ledger?.touch(conversation)
        binding.agent.followup({
          id: randomUUID(), role: 'user', source: { kind: 'user' },
          content: [{ type: 'text', text: prompt }],
        })
      } catch(err) {
        task.status = 'failed'
        const safeKinds=new Set(['r538_pinky_native_scope_missing',
          'r538_readonly_tools_missing','r538_readonly_mask_cannot_be_removed',
          'r538_readonly_mask_not_enforced','r540_full_pinky_catalog_unavailable'])
        task.failure=safeKinds.has(err?.message)?err.message:'harness_agent_failed'
        try {task.phoneMask?.()} catch {}
        task.phoneMask=null
        try {ledger?.finishTurn(task)} catch {}
        if (binding?.busy === task.id) binding.busy = null
      }
      send(res, task.status === 'failed' ? 500 : 202,
        { ok: task.status !== 'failed', idempotent: false, ...publicRecord(task) })
    })

    attach('/result', async (req, res) => {
      if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'method_not_allowed' })
      if (!protect(req, res)) return
      const body = await readBody(req)
      if (body?.protocolVersion !== PROTOCOL_VERSION ||
          typeof body?.task_id !== 'string' ||
          Object.keys(body).some((key) => !['protocolVersion', 'task_id'].includes(key))) {
        return send(res, 400, { ok: false, error: 'invalid_query' })
      }
      const task = tasks.get(body.task_id)
      if (!task) {
        const saved=ledger?.getTask(body.task_id)
        if (!saved)return send(res,404,{ok:false,error:'unknown_task'})
        if (saved.status==='ended')
          return send(res,410,{ok:false,error:'session_ended'})
        if (!FINAL_STATES.has(saved.status))
          return send(res,409,{ok:false,error:'turn_outcome_unknown',task_id:body.task_id})
        return send(res,200,{ok:true,...savedPublicRecord(saved)})
      }
      send(res, 200, { ok: true, ...publicRecord(task) })
    })

    // Optional read-only snapshot for a trusted Mac-side visual/device gateway.
    // Never expose the Bridge bearer credential directly to an ESP32.
    attach('/companion-facts', async (req, res) => {
      if (req.method !== 'POST') return send(res, 405, {ok:false,error:'method_not_allowed'})
      if (!protect(req, res)) return
      if (process.env.DSH_LIVE_ENABLE_COMPANION_FACTS !== '1' && !config.companionFacts)
        return send(res,503,{ok:false,error:'companion_facts_disabled'})
      const body=await readBody(req)
      if (!body || body.protocolVersion!==PROTOCOL_VERSION ||
          typeof body.task_id!=='string' || typeof body.session_id!=='string' ||
          (body.after_revision !== undefined &&
           (!Number.isSafeInteger(body.after_revision) || body.after_revision < -1 ||
            body.after_revision > 1000000000)) ||
          Object.keys(body).some((key)=>!['protocolVersion','task_id','session_id','after_revision'].includes(key)))
        return send(res,400,{ok:false,error:'invalid_query'})
      // This endpoint does not read the persisted ledger; an unbound or ended
      // task must never recover a stale source context through a visual poll.
      const task=tasks.get(body.task_id)
      if (!task) return send(res,404,{ok:false,error:'unknown_task'})
      if (!task.session || body.session_id!==task.session)
        return send(res,409,{ok:false,error:'session_mismatch'})
      // The /end handler removes its active task entry; never load ledger data.
      if (body.after_revision !== undefined) {
        const changes = companionFactChanges(task, body.after_revision)
        if (!changes) return send(res,409,{ok:false,error:'visual_history_gap'})
        return send(res,200,{ok:true,...companionFacts(task),changes})
      }
      send(res,200,{ok:true,...companionFacts(task)})
    })

    attach('/cancel', async (req, res) => {
      if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'method_not_allowed' })
      if (!protect(req, res)) return
      const body = await readBody(req)
      if (body?.protocolVersion !== PROTOCOL_VERSION ||
          typeof body.task_id !== 'string' ||
          Object.keys(body).some((key) => !['protocolVersion', 'task_id'].includes(key))) {
        return send(res, 400, { ok: false, error: 'invalid_query' })
      }
      const task = tasks.get(body.task_id)
      if (!task) {
        const saved=ledger?.getTask(body.task_id)
        if (!saved)return send(res,404,{ok:false,error:'unknown_task'})
        if (saved.status==='ended')
          return send(res,410,{ok:false,error:'session_ended'})
        if (!FINAL_STATES.has(saved.status))
          return send(res,409,{ok:false,error:'turn_outcome_unknown',task_id:body.task_id})
        return send(res,200,{ok:true,idempotent:true,...savedPublicRecord(saved)})
      }
      if (FINAL_STATES.has(task.status) || task.status === 'cancel_requested') {
        return send(res, 200, { ok: true, idempotent: true, ...publicRecord(task) })
      }
      if (typeof task.agentRef?.cancel !== 'function') {
        return send(res, 501, { ok: false, error: 'native_cancel_unavailable' })
      }
      try {
        task.agentRef.cancel({ kind: 'user' })
        // cancel() is only a request. Only turn/end(aborted) + idle proves settlement.
        task.status = 'cancel_requested'
        task.speechPrewarm?.nativeEvent('cancel_requested')
        task.factRevision += 1
        rememberCompanionFact(task)
      } catch {
        return send(res, 503, { ok: false, error: 'native_cancel_failed' })
      }
      send(res, 202, { ok: true, idempotent: false, ...publicRecord(task) })
    })

    function lookup(session) {
      return tasks.get(bySession.get(String(session)) ?? '')
    }
    function releaseIfFinal(task) {
      if (!task || !FINAL_STATES.has(task.status)) return
      // A *process-local* official stream is only a speculative TTS preview.
      // Verify the final native settlement and immediately drop raw chunks;
      // never expose candidate wording through Bridge routes or disk ledger.
      if (task.speechPrewarm) {
        try {
          const gate=task.speechPrewarm
          const verified=gate.finalize({
            status:task.status,finalText:task.text,turnEnd:task.turnEnd,
            executionVerified:task.status==='completed',
          })
          task.speechPrewarmVerified=verified.length // count only, no raw preview
        } catch {
          task.speechPrewarmVerified=0
        } finally {
          task.speechPrewarm=null // discard all ephemeral text on settlement
        }
      }
      // R538: restore the user's NORMAL Agent tool scope only when the
      // exact official DSH task truly settles (not on cancellation request).
      // The result retains the fact that this turn was read-only.
      const bound=task.conversation ? byConversation.get(task.conversation) : null
      try {task.phoneMask?.()} catch {}
      task.phoneMask=null
      try {ledger?.finishTurn(task)} catch {}
      // R236 passive suggestion candidate from a successful native turn.
      // NOT a separate Agent, model call, or memory write. Never save raw
      // transcript or inferred private user facts; candidates do not affect
      // persona without a separate affirmative human review.
      if (growth && ['answered','completed'].includes(task.status) &&
          task.conversation && memoryVault?.list().consent.manual_write &&
          growth.version().suggestions_enabled) {
        try {
          const text=suggestedGrowthFromUserTurn(task.prompt)
          if(text)growth.propose({text,turn_id:task.turn,
            source:'assistant_suggested'})
        }catch{/* suggestion failures NEVER affect user tasks */}
      }
      if (!task.conversation) return
      const binding = byConversation.get(task.conversation)
      if (binding?.busy === task.id) binding.busy = null
    }
    function markCompleted(task) {
      if (!task || FINAL_STATES.has(task.status)) return
      if (!task.idleSeen || !task.turnEnd) return
      if (task.turnEnd === 'aborted') {
        task.status = 'cancelled'
      } else if (task.approvalOutstanding) {
        return
      } else if (task.approvalRejected) {
        task.status = 'failed'
        // Do not misreport a user's native refusal/cancellation as a Host crash.
        // Both outcomes remain failed for execution-safety; no tool success is claimed.
        task.failure = task.approvalDenialOutcome === 'rejected'
          ? 'native_approval_rejected'
          : task.approvalDenialOutcome === 'cancelled'
            ? 'native_approval_cancelled' : 'native_approval_not_granted'
      } else if (task.turnEnd !== 'completed') {
        task.status = 'failed'
        task.failure = 'harness_turn_' + task.turnEnd
      } else if ([...task.tools.values()].some((item) => item.outcome === 'failed')) {
        if(verifiedCuaPreselectionRecovery(task)) {
          // R678: provider-confirmed read-only Chrome/Finder result after
          // a harmless pre-getApp state probe. The failed tool receipt is
          // retained; no permission or side-effect error is erased.
          task.status='completed'
          task.cuaPreselectionRecovered=true
        }else if(recoveredReadonlySearch(task)) {
          // R682: one rejected phone_observe argument schema never reached
          // the phone; a later producer-verified same-app screen result
          // completed the explicitly read-only SEARCH. Keep failed receipt.
          task.status='completed'
          task.phoneRecoveredReadonlySearch=true
        }else{
          task.status='failed'
          task.failure='native_tool_failed'
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
      releaseIfFinal(task)
    }
    // Native official Agent-stream observation, no TTS or new endpoint.
    // Scope to the task's exact live Agent; never infer owner from foreground UI.
    disposers.push(ctx.on('agent/assistant-stream', ({agent,frame}) => {
      const task=lookup(agent?.id)
      if (!task || task.agentRef!==agent || task.session!==String(agent.id) ||
          FINAL_STATES.has(task.status) || task.status==='cancel_requested') return
      try {
        if (frame?.type==='start' && !task.speechPrewarm &&
            Number.isSafeInteger(frame.turn) && frame.turn>=0) {
          task.speechPrewarm=new PrivateSpeechPrewarm({
            agentId:task.session,sessionId:task.session,
            taskId:task.id,nativeTurn:frame.turn,
          })
        }
        task.speechPrewarm?.feed(agent,frame)
      } catch {
        // Presentation observers must never break a native Agent request.
        // Drop only our ephemeral copy, without logging sensitive deltas.
        task.speechPrewarm=null
      }
    }))
    disposers.push(ctx.on('agent/status', ({ agent, status }) => {
      const task = lookup(agent.id)
      if (!task || FINAL_STATES.has(task.status)) return
      task.factRevision += 1
      if (status === 'running' && task.status !== 'cancel_requested') task.status = 'running'
      else if (status !== 'running') {
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
        task.factRevision += 1; task.status = 'failed'; releaseIfFinal(task)
        rememberCompanionFact(task)
      }
    }))
    disposers.push(ctx.on('session/event', (session, event) => {
      const task = lookup(session.id)
      if (!task || FINAL_STATES.has(task.status)) return
      const previousRevision = task.factRevision
      if (event?.type==='tool/call' || event?.type==='approval/asked')
        task.speechPrewarm?.nativeEvent(event.type)
      if (['tool/call', 'tool/result', 'approval/asked', 'approval/decided', 'assistant/message', 'turn/end'].includes(event?.type))
        task.factRevision += 1
      if (event?.type === 'tool/call') {
        const id = event.data?.callId
        const name = event.data?.name
        if (typeof id === 'string' && id && typeof name === 'string' && name) {
          if (!task.tools.has(id)) task.tools.set(id, {
            name, outcome: 'pending',
            ...(name==='cua'?{cuaMethod:cuaMethod(event.data?.arguments)}:{}),
            ...(task.phoneMode==='pinky' && name==='mcp__pinky_dafeiyu__phone_launch'
              ? {launchTarget:nativePinkyLaunchTarget(name,event.data?.arguments)} : {}),
          })
          task.textAfterTools = false
          if (task.status !== 'cancel_requested') task.status = 'running'
        }
      } else if (event?.type === 'tool/result') {
        const message = event.data?.message
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
               (message.source.kind === 'tool' &&
                message.source.callId === block.toolCallId))) {
            callId = block.toolCallId
            isError = block.isError
          }
        }
        const tool = task.tools.get(callId)
        if (tool && typeof isError === 'boolean') {
          tool.outcome = isError || event.data?.error ? 'failed' : 'success'
          if(tool.outcome==='failed' && tool.name==='mcp__pinky_dafeiyu__phone_observe')
            tool.schemaRejected=rejectedObserveSchema(tool.name,message)
          if(tool.name==='cua')noteCuaResult(tool,message)
          if(tool.outcome==='success' && task.phoneMode==='pinky') {
            // R626: final direct action screen proof must be produced by the
            // same native tool call. Store only boolean; no screen data.
            tool.settledScreen=nativePinkySettledScreen(tool.name,message)
            // Tool-role producer-owned messages only. Parse their first
            // status line; do not retain the screen, summary or task ID
            // in any public receipt or persistent ledger.
            const status=delegatedPinkyResult(tool.name,message)
            if(status)tool.delegate=status
            if(tool.name==='mcp__pinky_dafeiyu__phone_launch' && tool.launchTarget){
              const app=settledPinkyLaunch(tool.name,message,tool.launchTarget)
              if(app)tool.launchConfirmed=app
            }
            if(tool.name==='mcp__pinky_dafeiyu__phone_observe'){
              tool.observedApp=settledPinkyScreenApp(tool.name,message)
            }
            if(tool.name==='mcp__pinky_dafeiyu__phone_type'){
              tool.typedScreenApp=settledPinkyScreenApp(tool.name,message)
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
        const {id,toolName} = event.data ?? {}
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
        const {id,outcome} = event.data ?? {}
        if (typeof id !== 'string' || !task.pendingApprovals.has(id) ||
            !['allowed-once','rejected','cancelled','unavailable'].includes(outcome)) {
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
          if (task.status !== 'cancel_requested')
            task.status = task.approvalOutstanding ? 'approval_needed' : 'running'
          markCompleted(task)
        }
      } else if (event?.type === 'assistant/message') {
        // DSH's own message block type is evidence; the raw private
        // reasoning text, signatures and tool arguments never leave Bridge.
        const blocks=event.data?.message?.content
        if(Array.isArray(blocks) && blocks.some(block=>
          block?.type==='reasoning' && typeof block.text==='string' &&
          block.text.trim().length>0))task.reasoningObserved=true
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

    return () => {
      for (const request of approvalRequests.values())request.finish('unavailable')
      for (const dispose of disposers.reverse()) dispose()
      // The native ToolRegistry returns an EXACT guard disposer. Without
      // releasing it, hot-loaded/rebound native Agents can retain an older
      // deny closure that defeats a valid new phone task. Releasing only
      // this Bridge's guard cannot widen another agent or bypass Pinky.
      for(const bound of byConversation.values())
        try {bound.phonePolicy?.guardDispose?.()} catch {}
      tasks.clear(); bySession.clear(); byTurn.clear(); byConversation.clear(); pendingConversations.clear(); endedConversations.clear()
      ledger?.close()
      growth?.close()
      memoryVault?.close()
    }
  })
}
