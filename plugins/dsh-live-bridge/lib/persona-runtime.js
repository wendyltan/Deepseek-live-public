/** Local-only persona, independently recoverable from invalid/unmounted source.
 * No DSH Agent creation, tool permission, model call, or user-turn logging.
 */
import { createHash, randomUUID } from 'node:crypto'
import { existsSync, lstatSync, mkdirSync, readFileSync, renameSync,
         statSync, writeFileSync, unlinkSync } from 'node:fs'
import { homedir } from 'node:os'
import { isAbsolute, join } from 'node:path'

const FALLBACK_CORE='你叫 DeepSeek，形象是一只蓝色 Q 版大肥鱼。对用户诚实，不能假称已执行工具。'
const FALLBACK_STYLE='日常用自然简短的中文，优先15–45字；遇到技术问题认真回答，避免括号动作和机械重复。'
const VOICE_FALLBACK='我是 DeepSeek，也叫大肥鱼。日常说话自然简短，通常15到45字；技术问题认真准确回答。不念括号动作，不冒充工具执行。'
const MAX_TOTAL_BYTES=8192
const DIGEST=x=>createHash('sha256').update(x).digest('hex')
function safeText(s,max=MAX_TOTAL_BYTES){
 if(typeof s!=='string'||!s.trim()||Buffer.byteLength(s)>max)throw new Error('persona_file_invalid')
 return s.trim()
}
function splitOriginal(text){
 const rows=safeText(text).split(/\r?\n/).map(x=>x.trim()).filter(Boolean)
 // Identity and non-fabrication must remain in the immutable core.
 return {core:rows.slice(0,2).join('\n'),style:rows.slice(2).join('\n')||FALLBACK_STYLE}
}
function snapDir(){
 const val=process.env.DSH_LIVE_PERSONA_SNAPSHOT_DIR ||
   join(process.env.DSH_HOME || join(homedir(),'.dsh'),'state','dsh-live-bridge','persona')
 if(!isAbsolute(val))throw new Error('persona_snapshot_path_not_absolute')
 return val
}
function writeSnapshot(file,data){
 const dir=snapDir()
 mkdirSync(dir,{recursive:true,mode:0o700})
 if(lstatSync(dir).isSymbolicLink()||(statSync(dir).mode&0o077)!==0)
   throw new Error('persona_snapshot_directory_unsafe')
 const dest=join(dir,file),tmp=dest+'.'+randomUUID()+'.tmp'
 if(existsSync(dest)&&(!lstatSync(dest).isFile()||lstatSync(dest).isSymbolicLink()))
   throw new Error('persona_snapshot_file_unsafe')
 try {
   writeFileSync(tmp,data,{flag:'wx',mode:0o600})
   renameSync(tmp,dest)
 } finally {if(existsSync(tmp))unlinkSync(tmp)}
}
function readSnapshot(file){
 const p=join(snapDir(),file)
 if(!existsSync(p)||!lstatSync(p).isFile()||lstatSync(p).isSymbolicLink()||
    (statSync(p).mode&0o077)!==0)return null
 const blob=readFileSync(p,'utf8')
 if(Buffer.byteLength(blob)>20000)return null
 const parsed=JSON.parse(blob)
 if(parsed?.version!==1||typeof parsed?.core!=='string'||
    typeof parsed?.style!=='string')return null
 const core=safeText(parsed.core),style=safeText(parsed.style)
 if(parsed.sha256!==DIGEST(core+'\n'+style))return null
 return {core,style}
}
function sourceLayers(root){
 const full=join(root,'app','companion_persona.txt')
 const base=splitOriginal(readFileSync(full,'utf8'))
 const coreFile=join(root,'app','persona_core.txt')
 const styleFile=join(root,'app','persona_style.txt')
 const core=existsSync(coreFile)?safeText(readFileSync(coreFile,'utf8')):base.core
 const style=existsSync(styleFile)?safeText(readFileSync(styleFile,'utf8')):base.style
 if(Buffer.byteLength(core+'\n'+style)>MAX_TOTAL_BYTES)throw new Error('persona_too_large')
 return {core,style}
}
export function openPersona(root,{snapshot=true}={}){
 let warnCount=0
 let lastGoodVoice=VOICE_FALLBACK
 function voice(){
   // R312 accepted: the spoken persona tracks the owner-approved local V1
   // document without a model call or extra Agent, with last-good fallback.
   try {
     const raw=safeText(readFileSync(join(root,'app','companion_persona.txt'),'utf8'))
     const rows=raw.split(/\r?\n/).filter(Boolean).slice(0,7)
       .map(row=>row.split('。')[0].slice(0,76)).filter(Boolean)
     const result='【大肥鱼语音人格】'+rows.join('；')+
       '。自然、简洁、准确地回答；不要朗读舞台动作。'
     if(Buffer.byteLength(result)>1600)throw Error('voice_persona_too_long')
     lastGoodVoice=result
   }catch{warnCount++}
   return lastGoodVoice
 }
 function load(){
   try {
     const layers=sourceLayers(root)
     if(snapshot) {
       try {
         const existing=readSnapshot('snapshot-v1.json')
         if(!existing||existing.core!==layers.core||existing.style!==layers.style)
           writeSnapshot('snapshot-v1.json',JSON.stringify({
             version:1,core:layers.core,style:layers.style,
             sha256:DIGEST(layers.core+'\n'+layers.style)
           })+'\n')
       }catch {warnCount++ /* snapshot failure is observable, not a turn failure */ }
     }
     return {...layers,source:'file'}
   }catch{
     if(snapshot){
       try {
         const layers=readSnapshot('snapshot-v1.json')
         if(layers)return {...layers,source:'snapshot'}
       }catch{}
     }
     warnCount++
     return {core:FALLBACK_CORE,style:FALLBACK_STYLE,source:'fallback'}
   }
 }
 function metadata(speechOnly=false){
   const p=load()
   const text=speechOnly?voice():p.core+'\n'+p.style
   return Object.freeze({
     version:0,sha256:DIGEST(text),bytes:Buffer.byteLength(text),
     layers:speechOnly?{core:Buffer.byteLength(voice()),style:0,dynamic:0,memory:0}:{
       core:Buffer.byteLength(p.core),style:Buffer.byteLength(p.style),dynamic:0,memory:0,
     },source:p.source,
   })
 }
 const core=()=>load().core
 const style=()=>load().style
 const health=()=>({...metadata(),warning_count:warnCount})
 return {load,core,style,voice,metadata,health}
}
