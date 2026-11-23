/** R308 single canonical E1b memory for manual + verified user voice.
 * CLI only; no models, recordings, conversation scraping or external API.
 * Machine output returned only to a local Mac caller (never log private facts).
 */
import {readFileSync,existsSync,lstatSync} from 'node:fs'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {openManualMemory} from '../plugins/dsh-live-bridge/lib/manual-memory.js'
import {ROOT,VAULT} from './r18_manual_memory_cli.mjs'
const thisFile=resolve(fileURLToPath(import.meta.url))
const HOME=process.env.HOME
const PREF=HOME+'/Library/Application Support/Deepseek-live/companion-native/memory-candidate-mode.json'
const LEGACY=HOME+'/Library/Application Support/Deepseek-live/companion-native/memory-auto-v1.json'
const SOURCE='verified_esp32_user_voice'
const labels={name:'称呼：',likes:'爱好：',dislikes:'不喜欢：'}
const HEX=/^[a-f0-9]{32}$/
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i
function safeJson(file,max){
 if(!existsSync(file))return null
 const st=lstatSync(file)
 if(!st.isFile()||st.isSymbolicLink()||(st.mode&0o077)!==0||
    st.uid!==process.getuid()||st.size<2||st.size>max)throw Error('private_memory_input_unsafe')
 return JSON.parse(readFileSync(file,'utf8'))
}
function isVoiceFact(f){
 return f&&typeof f==='object'&&!Array.isArray(f)&&
  Object.keys(f).sort().join(',')==='category,text,value'&&
  Object.hasOwn(labels,f.category)&&typeof f.value==='string'&&
  f.value.length>=2&&f.value.length<=35&&
  /^[\p{Script=Han}A-Za-z0-9、 ]+$/u.test(f.value)&&
  f.text===labels[f.category]+f.value&&f.text.length<=55&&
  !/密码|验证码|银行卡|身份证|住址|住在|病|诊断|病史|宗教|政治|手机号|账号|密钥|秘密|借贷|转账|付款|删除|关闭|执行/.test(f.value)
}
function manualStatus(vault){
 const s=vault.list()
 return {count:s.items.length,manual_write:s.consent.manual_write}
}
export function act(vault,action,input,options={}){
 if(!input||typeof input!=='object'||Array.isArray(input))throw Error('bad_input')
 if(action==='status'){
  const base=manualStatus(vault)
  const items=vault.list().items.map(x=>{
   const v=vault.read(x.id)
   return {id:x.id,revision:x.revision,source:x.source,
     text:v.text.trim().slice(0,512),updated_at_unix:Math.floor(x.updated_at/1000)}
  })
  return {...base,items}
 }
 if(action==='lookup'){
  const query=input.query
  if(typeof query!=='string'||!query.trim()||query.length>600)throw Error('invalid_memory_query')
  const text=query.toLocaleLowerCase().normalize('NFKC')
  const terms=text.match(/[\p{Script=Han}]{2,}|[a-z0-9]{3,}/gu)||[]
  const ngrams=new Set(terms.flatMap(t=>/[\p{Script=Han}]/u.test(t)?
    Array.from({length:Math.max(0,t.length-1)},(_,i)=>t.slice(i,i+2)):[t]))
  const personal=/我是谁|我叫什么|你认识我|关于我|我的(?:名字|称呼)|记得我/.test(query)
  const scored=[]
  for(const row of vault.list().items){
   if(!['user_explicit',SOURCE].includes(row.source))continue
   const fact=vault.read(row.id).text.trim().slice(0,140)
   const low=fact.toLocaleLowerCase().normalize('NFKC')
   let score=0
   for(const t of ngrams){if(low.includes(t))score++}
   if(/名字|称呼|你认识我|我是谁/.test(query)&&fact.startsWith('称呼：'))score+=4
   if(/喜欢|偏好|推荐|咖啡|兴趣|爱好/.test(query)&&/^(爱好：|不喜欢：)/.test(fact))score+=2
   if(personal&&fact.startsWith('称呼：'))score+=0.5
   if(score>0)scored.push({score,id:row.id,text:fact})
  }
  scored.sort((a,b)=>b.score-a.score||a.id.localeCompare(b.id))
  const facts=[]
  for(const x of scored.slice(0,4)){
    if(facts.includes(x.text))continue
    if(JSON.stringify([...facts,x.text]).length>700)continue
    facts.push(x.text)
  }
  return {facts}
 }
 if(action==='remember'){
  const f=input.fact
  const config=options.config??PREF
  if(!isVoiceFact(f))throw Error('memory_voice_fact_not_allowed')
  const mode=safeJson(config,512)
  if(mode?.schema!==1||mode.mode!=='auto')return {status:'disabled'}
  const stored=vault.putVerifiedVoice(f)
  return {status:stored.already?'already_saved':'saved',category:f.category}
 }
 if(action==='remove'){
  if(input.confirm!=='确认删除这一条记忆'||!UUID.test(input.id)||
    !Number.isSafeInteger(input.revision)||input.revision<1)
    throw Error('memory_removal_confirmation_required')
  const result=vault.remove(input.id,input.revision)
  return {removed:result.removed===true}
 }
 if(action==='migrate'){
  const file=options.legacy??LEGACY
  const old=safeJson(file,32768)
  if(old===null)return {imported:0,skipped:0,total:0}
  if(old.schema!==1||!Array.isArray(old.items)||old.items.length>64)
    throw Error('legacy_store_invalid')
  let imported=0,skipped=0
  for(const row of old.items){
   if(!row||typeof row!=='object'||Object.keys(row).sort().join(',')!==
       'category,created_at,id,source,text,value'||!HEX.test(row.id)||
       row.source!==SOURCE||!Number.isSafeInteger(row.created_at)||
       !isVoiceFact({category:row.category,value:row.value,text:row.text}))
     throw Error('legacy_memory_item_invalid')
  }
  for(const row of old.items){
   const result=vault.putVerifiedVoice({category:row.category,value:row.value,text:row.text})
   if(result.already)skipped++
   else imported++
  }
  return {imported,skipped,total:old.items.length}
 }
 throw Error('unsupported_memory_action')
}
if(process.argv[1]&&resolve(process.argv[1])===thisFile){
 const action=process.argv[2]
 if(!['status','lookup','remember','remove','migrate'].includes(action))process.exit(2)
 const raw=readFileSync(0,'utf8')
 if(Buffer.byteLength(raw)>4096)process.exit(2)
 let vault
 try{
  const input=JSON.parse(raw||'{}')
  vault=openManualMemory(ROOT,VAULT)
  const answer=act(vault,action,input)
  console.log('R308_UNIFIED_RESULT '+JSON.stringify({ok:true,...answer}))
 }catch(err){
  console.error('R308_UNIFIED_ERROR '+String(err?.message||'failed').slice(0,90))
  process.exitCode=2
 }finally{vault?.close()}
}
