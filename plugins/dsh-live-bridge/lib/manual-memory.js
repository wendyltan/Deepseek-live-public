/**
 * E1b local, explicit-only Markdown memory vault. NOT an automatic ReMe feed.
 * No model, speech, tool result, or session text is harvested here.
 * The caller must be a trusted, authenticated user interface (not an LLM).
 */
import { createHash, randomUUID } from 'node:crypto'
import { closeSync, existsSync, lstatSync, mkdirSync, openSync, readFileSync,
         realpathSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs'
import { isAbsolute, join, relative, resolve, sep } from 'node:path'

const ID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
function fail(message){throw new Error(message)}
function sha(data){return createHash('sha256').update(data).digest('hex')}
function atomic(path,data){
  const tmp=path+'.'+randomUUID()+'.tmp'
  try {
    writeFileSync(tmp,data,{flag:'wx',mode:0o600})
    renameSync(tmp,path)
  } finally {if(existsSync(tmp))unlinkSync(tmp)}
}
function safeDirectory(projectRoot,stateDir){
  if(!isAbsolute(stateDir))fail('memory_path_absolute_required')
  const root=realpathSync(projectRoot)
  const logical=resolve(projectRoot)
  const target=resolve(stateDir)
  const canonical=target.startsWith(logical+sep)?
    resolve(root,relative(logical,target)):target
  if(!canonical.startsWith(root+sep))fail('memory_path_outside_project')
  for(let cursor=canonical;cursor.startsWith(root+sep);cursor=resolve(cursor,'..')){
    if(existsSync(cursor)&&lstatSync(cursor).isSymbolicLink())fail('memory_symlink')
  }
  mkdirSync(canonical,{recursive:true,mode:0o700})
  if(realpathSync(canonical)!==canonical)fail('memory_symlink')
  if((statSync(canonical).mode & 0o077)!==0)fail('memory_directory_not_private')
  return canonical
}
export function openManualMemory(projectRoot,stateDir,clock=()=>Date.now()){
  const dir=safeDirectory(projectRoot,stateDir)
  const lock=join(dir,'memory.lock')
  const identity=randomUUID()
  let fd
  try {fd=openSync(lock,'wx',0o600)}
  catch {fail('memory_already_open')}
  writeFileSync(fd,identity)
  closeSync(fd)
  let closed=false
  const metaFile=join(dir,'memory-index-v1.json')
  if(existsSync(metaFile) && (lstatSync(metaFile).isSymbolicLink()||
     !lstatSync(metaFile).isFile())) {
    try{if(readFileSync(lock,'utf8')===identity)unlinkSync(lock)}catch{}
    fail('memory_invalid_index')
  }
  let index
  try {
    index=existsSync(metaFile)?JSON.parse(readFileSync(metaFile,'utf8')):{
      version:1,consent:{manual_write:false,auto_extraction:false},items:{},
    }
  }catch{
    try{if(readFileSync(lock,'utf8')===identity)unlinkSync(lock)}catch{}
    fail('memory_invalid_index')
  }
  function assertIndex(){
    if(index.version!==1||typeof index.consent?.manual_write!=='boolean'||
      index.consent.auto_extraction!==false||
      !index.items||typeof index.items!=='object'||Array.isArray(index.items))
      fail('memory_invalid_index')
    for(const [id,item] of Object.entries(index.items)){
      if(!ID.test(id)||typeof item?.hash!=='string'||
        !Number.isSafeInteger(item.revision)||item.revision<1)
        fail('memory_invalid_index')
      const path=join(dir,id+'.md')
      if(!existsSync(path)||lstatSync(path).isSymbolicLink()||
        !lstatSync(path).isFile()||sha(readFileSync(path))!==item.hash)
        fail('memory_integrity_failed')
    }
  }
  try {assertIndex()}catch(e){
    try{if(readFileSync(lock,'utf8')===identity)unlinkSync(lock)}catch{}
    throw e
  }
  function ready(){if(closed)fail('memory_closed')}
  function persist(){ready();atomic(metaFile,JSON.stringify(index,null,2)+'\n')}
  function memoryText(id){
    ready()
    if(!ID.test(id)||!index.items[id])fail('memory_unknown_id')
    const path=join(dir,id+'.md')
    const text=readFileSync(path,'utf8')
    if(sha(text)!==index.items[id].hash)fail('memory_integrity_failed')
    return text
  }
  // Consent is a trusted-user action. Auto learning is intentionally unavailable.
  function setManualConsent(allow){
    ready()
    if(typeof allow!=='boolean')fail('memory_consent_invalid')
    index.consent.manual_write=allow
    persist()
  }
  function list(){
    ready()
    return {consent:{...index.consent},
      items:Object.entries(index.items).map(([id,x])=>({
        id,revision:x.revision,source:x.source,created_at:x.created_at,
        updated_at:x.updated_at,
      }))}
  }
  function read(id){
    const x=index.items[id]
    return {id,...structuredClone(x),text:memoryText(id)}
  }
  function put({id=randomUUID(),text,source='user_explicit',expectedRevision=null}){
    ready()
    if(!index.consent.manual_write)fail('memory_user_consent_required')
    if(!ID.test(id)||typeof text!=='string'||!text.trim()||
      Buffer.byteLength(text)>8192||source!=='user_explicit')
      fail('memory_invalid_fact')
    const previous=index.items[id]
    if((previous?.revision??null)!==expectedRevision)fail('memory_revision_conflict')
    if(!previous && Object.keys(index.items).length>=128)fail('memory_capacity')
    const content=text.trim()+'\n'
    const path=join(dir,id+'.md')
    if(existsSync(path)&&!previous)fail('memory_orphan_file')
    if(existsSync(path)&&lstatSync(path).isSymbolicLink())fail('memory_symlink')
    const at=clock()
    atomic(path,content)
    index.items[id]={revision:(previous?.revision??0)+1,hash:sha(content),
      source,created_at:previous?.created_at??at,updated_at:at}
    persist()
    return {id,revision:index.items[id].revision}
  }
  // R308: one canonical owner vault. Source-scoped physical ESP32 STT facts
  // can enter ONLY through the trusted Mac bridge after verified capture and
  // the separate user's voice mode=auto consent. This does not activate
  // manual_write or authorize ReMe to harvest conversations.
  function putVerifiedVoice({text,category,value}) {
    ready()
    const labels={name:'称呼：',likes:'爱好：',dislikes:'不喜欢：'}
    if(!Object.hasOwn(labels,category)||typeof value!=='string'||
       value.length<2||value.length>35||
       !/^[\p{Script=Han}A-Za-z0-9、 ]+$/u.test(value)||
       typeof text!=='string'||text!==labels[category]+value||
       /密码|验证码|银行卡|身份证|住址|住在|病|诊断|病史|宗教|政治|手机号|账号|密钥|秘密|借贷|转账|付款|删除|关闭|执行/.test(value))
       fail('memory_voice_fact_not_allowed')
    const duplicate=Object.keys(index.items).find(id=>
      memoryText(id).trim()===text)
    if(duplicate)return {id:duplicate,revision:index.items[duplicate].revision,
                         already:true}
    if(Object.keys(index.items).length>=128)fail('memory_capacity')
    const id=randomUUID(),content=text+'\n',at=clock()
    const path=join(dir,id+'.md')
    if(existsSync(path))fail('memory_orphan_file')
    atomic(path,content)
    index.items[id]={revision:1,hash:sha(content),
      source:'verified_esp32_user_voice',created_at:at,updated_at:at}
    persist()
    return {id,revision:1,already:false}
  }
  function remove(id,expectedRevision){
    ready()
    const prior=index.items[id]
    if(!prior||prior.revision!==expectedRevision)fail('memory_revision_conflict')
    memoryText(id)
    // ReMe is NOT connected to this vault: removal cannot promise to purge
    // already-imported external index/backups. Prevent silent auto-import.
    unlinkSync(join(dir,id+'.md'))
    delete index.items[id]
    persist()
    return {removed:true,id,derived_index:'not_connected',backups:'not_verified'}
  }
  function exportAll(){
    ready()
    return {consent:{...index.consent},
      facts:Object.keys(index.items).map(id=>read(id))}
  }
  function close(){
    if(closed)return
    closed=true
    try{if(readFileSync(lock,'utf8')===identity)unlinkSync(lock)}catch{}
  }
  return {directory:dir,list,read,put,putVerifiedVoice,remove,exportAll,setManualConsent,close}
}
