/**
 * Opt-in private DSH session binding ledger. No keys, raw prompts or speech.
 * DSH remains the source for conversation history and actual model events.
 *
 * This does NOT delete expired native DSH logs or extracted ReMe memories.
 */
import { createHash, randomUUID } from 'node:crypto'
import { closeSync, existsSync, lstatSync, mkdirSync, openSync, readFileSync,
         realpathSync, renameSync, rmdirSync, unlinkSync, writeFileSync } from 'node:fs'
import { isAbsolute, join, resolve, relative, sep } from 'node:path'

const MAX_BYTES = 256 * 1024
const MAX_TURNS = 512
const MAX_AGE_DAYS = 3650
const TERMINAL = new Set(['answered', 'completed', 'failed', 'cancelled'])
const ID = /^[A-Za-z0-9_-]{8,64}$/
function fail(msg) { throw new Error(msg) }

export function turnDigest(conversation, prompt) {
  return createHash('sha256').update(JSON.stringify([conversation ?? null, prompt])).digest('hex')
}

function getSafeDirectory(projectRoot, input) {
  if (!isAbsolute(input)) fail('session_state_path_must_be_absolute')
  const logicalRoot = resolve(projectRoot)
  const root = realpathSync(logicalRoot)
  const logicalRequested = resolve(input)
  // macOS /var and /tmp may alias /private/var and /private/tmp.
  // Canonicalize only paths already lexically inside the requested root.
  const requested = logicalRequested.startsWith(logicalRoot + sep)
    ? resolve(root, relative(logicalRoot, logicalRequested))
    : logicalRequested
  if (!requested.startsWith(root + sep)) fail('session_state_must_be_in_project')
  // Never traverse a symlink when writing a private state directory.
  for (let cursor = requested; cursor.startsWith(root + sep); cursor = resolve(cursor, '..')) {
    if (existsSync(cursor) && lstatSync(cursor).isSymbolicLink())
      fail('session_state_symlink_forbidden')
  }
  mkdirSync(requested, {recursive:true,mode:0o700})
  const actual = realpathSync(requested)
  if (actual !== requested) fail('session_state_symlink_forbidden')
  return actual
}
function writeAtomic(path, data) {
  const temp = path + '.' + randomUUID() + '.tmp'
  try {
    const json = JSON.stringify(data)
    if (Buffer.byteLength(json) > MAX_BYTES) fail('session_state_capacity')
    writeFileSync(temp, json + '\n', {flag:'wx',mode:0o600})
    renameSync(temp,path)
  } finally {
    if (existsSync(temp)) unlinkSync(temp)
  }
}
function validBinding(item) {
  return item && typeof item==='object' && typeof item.session_id==='string' &&
    /^[0-9a-f-]{36}$/i.test(item.session_id) &&
    Number.isSafeInteger(item.last_at) && item.last_at > 0 &&
    typeof item.selected?.provider==='string' && !!item.selected.provider &&
    typeof item.selected?.model==='string' && !!item.selected.model
}
export function openBindingLedger(projectRoot, location, clock=()=>Date.now()) {
  const dir = getSafeDirectory(projectRoot, location)
  const path = join(dir,'bindings-v1.json')
  const lock = join(dir,'bindings-v1.lock')
  const identity = randomUUID()
  let fd
  try { fd = openSync(lock,'wx',0o600) }
  catch(err) {
    if (err?.code !== 'EEXIST') throw err
    // Recover a crashed owner only when its recorded PID is provably absent.
    // The exclusive takeover directory serializes competing restarts.
    const takeover = lock + '.takeover'
    try { mkdirSync(takeover,{mode:0o700}) }
    catch { fail('session_state_already_owned') }
    try {
      if (!lstatSync(lock).isFile()) fail('session_state_lock_invalid')
      const original = readFileSync(lock,'utf8')
      const previous = JSON.parse(original)
      if (!Number.isSafeInteger(previous.pid) || previous.pid <= 0 ||
          typeof previous.identity !== 'string') fail('session_state_lock_invalid')
      let gone = false
      try { process.kill(previous.pid,0) }
      catch(e) { if(e?.code === 'ESRCH') gone=true }
      if (!gone) fail('session_state_already_owned')
      if(readFileSync(lock,'utf8') !== original) fail('session_state_lock_changed')
      unlinkSync(lock)
      fd = openSync(lock,'wx',0o600)
    } finally { rmdirSync(takeover) }
  }
  writeFileSync(fd, JSON.stringify({pid:process.pid,identity})+'\n')
  closeSync(fd)
  let closed = false
  try {
    const owner = createHash('sha256').update(realpathSync(projectRoot)).digest('hex')
    let data = {
      version:1, owner, resume_days:30, bindings:{}, turns:{},
    }
    if (existsSync(path)) {
      const stat=lstatSync(path)
      if (!stat.isFile() || stat.size > MAX_BYTES) fail('session_state_invalid')
      data=JSON.parse(readFileSync(path,'utf8'))
      if (data?.version!==1 || data.owner!==owner ||
          !Number.isInteger(data.resume_days) ||
          data.resume_days<0 || data.resume_days>MAX_AGE_DAYS ||
          !data.bindings || !data.turns ||
          Array.isArray(data.bindings) || Array.isArray(data.turns)) fail('session_state_invalid')
      for (const [id, entry] of Object.entries(data.bindings)) {
        if (!ID.test(id) || !validBinding(entry)) fail('session_state_invalid')
      }
      for (const [id, entry] of Object.entries(data.turns)) {
        if (!ID.test(id) || typeof entry?.digest!=='string' ||
            typeof entry?.task_id!=='string' || !ID.test(entry.turn_id) ||
            !['interrupted','accepted','running','cancel_requested','ended',...TERMINAL].includes(entry.status)) fail('session_state_invalid')
      }
    } else writeAtomic(path,data)
    function save() {
      if (closed) fail('session_state_closed')
      writeAtomic(path,data)
    }
    function binding(id) {
      const x=data.bindings[id]
      if (!x) return null
      // 0 disables recovery across process restarts; it does not erase native logs.
      if (data.resume_days===0 || clock() - x.last_at > data.resume_days*86400000) {
        return {expired:true,...structuredClone(x)}
      }
      return {expired:false,...structuredClone(x)}
    }
    function putBinding(id, sessionId, selected, searchEnabled) {
      if (!ID.test(id) || !validBinding({session_id:sessionId,selected,last_at:clock()}))
        fail('session_binding_invalid')
      const previous=data.bindings[id]?.web_search_enabled
      const persisted=typeof searchEnabled==='boolean'?searchEnabled:previous
      data.bindings[id]={session_id:sessionId,selected:{...selected},last_at:clock(),
        ...(typeof persisted==='boolean'?{web_search_enabled:persisted}:{})}
      save()
    }
    function touch(id) {
      if (data.bindings[id]) { data.bindings[id].last_at=clock(); save() }
    }
    function getTurn(id) { return data.turns[id] ? structuredClone(data.turns[id]) : null }
    function getTask(taskId) {
      const item=Object.values(data.turns).find(x=>x.task_id===taskId)
      return item ? structuredClone(item) : null
    }
    function reserveTurn(id,conversation,prompt,taskId) {
      if (data.turns[id]) fail('session_turn_already_reserved')
      if(Object.keys(data.turns).length >= MAX_TURNS) fail('session_turn_ledger_full')
      data.turns[id] = {turn_id:id,task_id:taskId,conversation,
        digest:turnDigest(conversation,prompt),status:'interrupted',at:clock()}
      save()
    }
    function finishTurn(task) {
      if(!data.turns[task.turn]) return
      if(!TERMINAL.has(task.status)) return
      const record=data.turns[task.turn]
      record.status=task.status
      record.session_id=task.session ?? null
      record.text=(task.text ?? '').slice(0,6000)
      record.failure=task.failure ?? null
      record.tools=[...task.tools.values()].map(x=>({name:x.name,outcome:x.outcome}))
      record.finished_at=clock()
      save()
    }
    function endConversation(id) {
      if (!ID.test(id)) fail('session_binding_invalid')
      // Unknown native outcomes must not be discarded: a tool could have
      // executed before the process crashed. Keep its idempotency tombstone.
      for (const record of Object.values(data.turns)) {
        if (record.conversation===id && !TERMINAL.has(record.status) &&
            record.status!=='ended') fail('session_pending_turn')
      }
      delete data.bindings[id]
      for (const record of Object.values(data.turns)) {
        if (record.conversation!==id) continue
        delete record.text
        delete record.failure
        delete record.tools
        record.status='ended'
      }
      save()
    }
    function setResumeDays(days) {
      if(!Number.isInteger(days)||days<0||days>MAX_AGE_DAYS) fail('session_resume_days_invalid')
      data.resume_days=days; save()
    }
    function close() {
      if(closed)return
      closed=true
      try {
        const file=JSON.parse(readFileSync(lock,'utf8'))
        if(file.identity===identity)unlinkSync(lock)
      }catch{}
    }
    return {directory:dir,binding,putBinding,touch,getTurn,getTask,reserveTurn,finishTurn,
      setResumeDays,endConversation,get resumeDays(){return data.resume_days},close}
  }catch(err) {
    try {if(existsSync(lock)) {
      const file=JSON.parse(readFileSync(lock,'utf8'))
      if(file.identity===identity)unlinkSync(lock)
    }}catch{}
    throw err
  }
}
