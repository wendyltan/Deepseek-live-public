/**
 * Consent-gated local Growth Ledger. No model calls, prompt interception,
 * tool execution or ReMe access. No raw task prompts are persisted. Only
 * reviewed candidates can affect activeFacts(); assistant suggestions require
 * a separate user-controlled OFF-by-default consent.
 */
import {createHash,randomUUID} from 'node:crypto'
import {existsSync, lstatSync, mkdirSync, openSync, closeSync,
  readFileSync, realpathSync, renameSync, statSync, unlinkSync, writeFileSync} from 'node:fs'
import {isAbsolute,join,relative,resolve,sep} from 'node:path'

const ID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const MAX_ITEMS=64, MAX_ACTIVE=20, MAX_VERSIONS=10, MAX_BYTES=512
const digest=v=>createHash('sha256').update(v).digest('hex')
const fail=s=>{throw new Error(s)}
function privateDir(root,path) {
 if(!isAbsolute(path))fail('growth_path_absolute_required')
 const base=realpathSync(root),logical=resolve(root),target=resolve(path)
 if(!target.startsWith(logical+sep))fail('growth_path_outside_project')
 const dir=resolve(base,relative(logical,target))
 if(!dir.startsWith(base+sep))fail('growth_path_outside_project')
 for(let cur=dir;cur.startsWith(base+sep);cur=resolve(cur,'..')) {
  if(existsSync(cur)&&lstatSync(cur).isSymbolicLink())fail('growth_path_symlink')
 }
 mkdirSync(dir,{recursive:true,mode:0o700})
 if(realpathSync(dir)!==dir||(statSync(dir).mode&0o077)!==0)fail('growth_directory_not_private')
 return dir
}
function atomic(path,content) {
 if(existsSync(path)&&(lstatSync(path).isSymbolicLink()||
   !lstatSync(path).isFile()))fail('growth_state_unsafe')
 const tmp=path+'.'+randomUUID()+'.tmp'
 try{writeFileSync(tmp,content,{flag:'wx',mode:0o600});renameSync(tmp,path)}
 finally{if(existsSync(tmp))unlinkSync(tmp)}
}
function validText(text) {
 if(typeof text!=='string'||!text.trim()||
    Buffer.byteLength(text)>MAX_BYTES)fail('growth_invalid_fact')
 return text.trim()
}
function clone(v){return structuredClone(v)}
function activeList(state) {
 return Object.values(state.facts).slice(-MAX_ACTIVE).map(item=>({text:item.text,id:item.id}))
}
function hashFacts(facts){
 return digest(facts.map(f=>f.text).join('\n'))
}
export function openGrowth(root,stateDir,{clock=()=>Date.now()}={}) {
 const dir=privateDir(root,stateDir)
 const lock=join(dir,'growth.lock'),owner=randomUUID()
 let fd
 try{fd=openSync(lock,'wx',0o600)}catch{fail('growth_already_open')}
 writeFileSync(fd,owner);closeSync(fd)
 const file=join(dir,'growth-v1.json')
 let state
 try {
  if(existsSync(file) &&
    (lstatSync(file).isSymbolicLink()||!lstatSync(file).isFile()||
       (statSync(file).mode&0o077)!==0))fail('growth_state_unsafe')
  const raw=existsSync(file)?readFileSync(file,'utf8'):null
  if(raw&&Buffer.byteLength(raw)>131072)fail('growth_state_oversize')
  state=raw?JSON.parse(raw):{
   format:1,revision:0,version:0,suggestions_enabled:false,candidates:{},facts:{},
   versions:[{version:0,sha256:digest(''),facts:[],at:clock()}],
  }
  if(state?.format!==1 || (state.suggestions_enabled!==undefined &&
       typeof state.suggestions_enabled!=='boolean') ||
      !Number.isSafeInteger(state.revision) ||
      !Number.isSafeInteger(state.version) || !state.candidates ||
      !state.facts || !Array.isArray(state.versions) ||
      Object.keys(state.candidates).length>MAX_ITEMS ||
      Object.keys(state.facts).length>MAX_ACTIVE ||
      state.versions.length>MAX_VERSIONS)fail('growth_invalid_state')
  if(state.revision<state.version || state.versions.length<1 ||
     !Number.isSafeInteger(state.versions.at(-1)?.version) ||
     state.versions.at(-1).version!==state.version)
    fail('growth_invalid_state')
  for(const [id,item] of Object.entries(state.candidates)) {
    if(!ID.test(id)||item?.id!==id ||
       !['new','accepted','rejected'].includes(item.status) ||
       !['user_explicit','assistant_suggested'].includes(item.source)||
       digest(validText(item.text))!==item.sha256)
      fail('growth_invalid_state')
  }
  for(const [id,fact] of Object.entries(state.facts)) {
    if(!ID.test(id)||fact?.id!==id||
       !['reviewed_user_explicit','reviewed_assistant_suggested'].includes(fact.source)||
       validText(fact.text)!==fact.text)
      fail('growth_invalid_state')
  }
  for(const version of state.versions) {
    if(!Number.isSafeInteger(version?.version)||!Array.isArray(version.facts)||
       version.facts.length>MAX_ACTIVE||
       version.sha256!==hashFacts(version.facts))fail('growth_invalid_state')
    for(const fact of version.facts)
      if(!ID.test(fact?.id??'')||validText(fact.text)!==fact.text)
        fail('growth_invalid_state')
  }
  if(state.versions.at(-1).sha256!==hashFacts(activeList(state)))
    fail('growth_integrity_failed')
 }catch(err){
  try{if(readFileSync(lock,'utf8')===owner)unlinkSync(lock)}catch{}
  throw err
 }
 let closed=false
 const ready=()=>{if(closed)fail('growth_closed')}
 function save(next) {
  ready()
  const data=JSON.stringify(next,null,2)+'\n'
  if(Buffer.byteLength(data)>131072)fail('growth_state_oversize')
  atomic(file,data)
  state=next
 }
 function version(){
  ready()
  const active=activeList(state)
  return {version:state.version,revision:state.revision,
   sha256:hashFacts(active),active_count:active.length,
   candidate_count:Object.values(state.candidates).filter(x=>x.status==='new').length,
   suggestions_enabled:state.suggestions_enabled===true}
 }
 function listCandidates(status='new') {
  ready()
  if(!['new','accepted','rejected','all'].includes(status))fail('growth_invalid_status')
  return Object.values(state.candidates)
    .filter(x=>status==='all'||x.status===status)
    .map(x=>clone(x))
 }
 function setSuggestionConsent({allow,expectedRevision,confirmed=false}={}) {
  ready()
  if(confirmed!==true)fail('growth_user_confirmation_required')
  if(typeof allow!=='boolean')fail('growth_invalid_consent')
  if(expectedRevision!==state.revision)fail('growth_revision_conflict')
  if((state.suggestions_enabled===true)===allow)return version()
  const next=clone(state)
  next.suggestions_enabled=allow
  next.revision++
  save(next)
  return version()
 }
 function propose({text,turn_id=null,source='user_explicit'}={}) {
  ready()
  text=validText(text)
  if(!['user_explicit','assistant_suggested'].includes(source) ||
      (source==='assistant_suggested' &&
        (state.suggestions_enabled!==true || turn_id===null)) ||
      (turn_id!==null &&
       (typeof turn_id!=='string'||!/^[A-Za-z0-9_-]{8,64}$/.test(turn_id))))
    fail('growth_invalid_proposal')
  const hash=digest(text)
  const duplicate=Object.values(state.candidates).find(x=>
    x.sha256===hash&&x.status!=='rejected')
  if(duplicate)return {id:duplicate.id,duplicate:true,revision:state.revision}
  if(Object.keys(state.candidates).length>=MAX_ITEMS)fail('growth_capacity')
  const next=clone(state),id=randomUUID()
  next.candidates[id]={id,text,sha256:hash,turn_id,source,status:'new',
    created_at:clock(),decided_at:null}
  next.revision++
  save(next)
  return {id,duplicate:false,revision:next.revision}
 }
 function decide({id,decision,expectedRevision,confirmed=false}={}) {
  ready()
  if(!ID.test(id??'')||!['accept','reject'].includes(decision)||
      expectedRevision!==state.revision)fail('growth_revision_conflict')
  if(confirmed!==true)fail('growth_user_confirmation_required')
  const item=state.candidates[id]
  if(!item||item.status!=='new')fail('growth_candidate_not_pending')
  if(decision==='accept' && Object.keys(state.facts).length>=MAX_ACTIVE)
    fail('growth_active_capacity')
  const next=clone(state),candidate=next.candidates[id]
  candidate.status=decision==='accept'?'accepted':'rejected'
  candidate.decided_at=clock()
  next.revision++
  if(decision==='accept') {
   next.facts[id]={id,text:candidate.text,
    source:candidate.source==='assistant_suggested'?'reviewed_assistant_suggested':'reviewed_user_explicit',at:clock()}
   next.version++
   const facts=activeList(next)
   next.versions.push({version:next.version,sha256:hashFacts(facts),facts,at:clock()})
   next.versions=next.versions.slice(-MAX_VERSIONS)
  }
  save(next)
  return version()
 }
 function rollback({toVersion,expectedRevision,confirmed=false}={}) {
  ready()
  if(!Number.isSafeInteger(toVersion)||expectedRevision!==state.revision)
    fail('growth_revision_conflict')
  if(confirmed!==true)fail('growth_user_confirmation_required')
  const found=state.versions.find(x=>x.version===toVersion)
  if(!found||found.sha256!==hashFacts(found.facts))
    fail('growth_version_unavailable')
  const next=clone(state)
  next.facts=Object.fromEntries(found.facts.map(x=>[x.id,{
   id:x.id,text:x.text,source:state.candidates[x.id]?.source==='assistant_suggested'?
     'reviewed_assistant_suggested':'reviewed_user_explicit',at:clock()}]))
  next.revision++;next.version++
  const facts=activeList(next)
  next.versions.push({version:next.version,sha256:hashFacts(facts),facts,at:clock()})
  next.versions=next.versions.slice(-MAX_VERSIONS)
  save(next)
  return version()
 }
 function activeFacts(limit=20) {
  ready()
  if(!Number.isSafeInteger(limit)||limit<0||limit>MAX_ACTIVE)fail('growth_invalid_limit')
  return limit===0?[]:activeList(state).slice(-limit).map(x=>x.text)
 }
 function close(){
  if(closed)return
  closed=true
  try{if(readFileSync(lock,'utf8')===owner)unlinkSync(lock)}catch{}
 }
 return {version,listCandidates,propose,setSuggestionConsent,decide,rollback,activeFacts,close}
}
