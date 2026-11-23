/**
 * R310 single owner-facing editor for the existing canonical DSH persona.
 * No DSH Agent/model calls, chat inspection, credential access, or automatic
 * persona writes. Save requires exact user-provided SHA and explicit button
 * confirmation in the caller. Old deployed plugin rereads source only upon
 * creating a normal non-speech Agent; no claim of active-session hot reload.
 */
import {readFileSync,lstatSync,existsSync,mkdirSync,writeFileSync,renameSync,unlinkSync,
  chmodSync,statSync,realpathSync} from 'node:fs'
import {createHash,randomUUID} from 'node:crypto'
import {join,resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {homedir} from 'node:os'
const ROOT=resolve(fileURLToPath(new URL('..',import.meta.url)))
const SOURCE=join(ROOT,'app','companion_persona.txt')
const OLD_DEPLOY=join(homedir(),'.dsh','profiles','web','node_modules','dsh-live-bridge','lib','index.js')
const PROFILE=join(homedir(),'.dsh','profiles','web','cordis.patch.yml')
const GROWTH=join(ROOT,'private-runtime','growth','growth-v1.json')
const BACKUPS=join(ROOT,'private-runtime','persona-editor-backups')
const SHA=s=>createHash('sha256').update(s).digest('hex')
const fail=x=>{throw Error(x)}
function readPersona(){
 const st=lstatSync(SOURCE)
 if(!st.isFile()||st.isSymbolicLink()||st.uid!==process.getuid()||
    st.size<10||st.size>8192)fail('persona_file_unavailable')
 const text=readFileSync(SOURCE,'utf8')
 if(!text.trim()||text.includes('\0')||Buffer.byteLength(text)>8192)fail('persona_invalid')
 return {text,sha256:SHA(text),bytes:Buffer.byteLength(text)}
}
function layers(text){
 const rows=text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean)
 return {core:rows.slice(0,2).join('\n'),style:rows.slice(2).join('\n'),
   core_preview:rows[0]?.slice(0,130)||'',
   style_preview:rows.slice(2).find(x=>x.startsWith('你的性格'))?.slice(0,135)||
      rows[2]?.slice(0,135)||''}
}
function growthInfo(){
 try{
  const st=lstatSync(GROWTH)
  if(!st.isFile()||st.isSymbolicLink()||(st.mode&0o077)!==0||
     st.uid!==process.getuid()||st.size>131072)return {status:'unavailable'}
  const g=JSON.parse(readFileSync(GROWTH,'utf8'))
  if(g.format!==1||!Number.isSafeInteger(g.version)||
     !g.facts||!g.candidates)return {status:'unavailable'}
  return {status:'available',version:g.version,
    approved:Object.keys(g.facts).length,
    pending:Object.values(g.candidates).filter(x=>x.status==='new').length}
 }catch{return {status:'unavailable'}}
}
function dshInfo(){
 let fileConfigured=false,sourceUsed=false,layered=false,voiceUsesFull=false,version='unknown'
 let personaHotReloadReady=false,voicePersonaShortReady=false
 try{
  const text=readFileSync(PROFILE,'utf8')
  const piece=text.match(/(?:^|\n)- id: dsh-live-bridge\n([\s\S]*?)(?=\n- id:|\n#|\s*$)/)
  fileConfigured=!!piece&&/^\s+companionPersona:\s*true\s*$/m.test(piece[1])
  const code=readFileSync(OLD_DEPLOY,'utf8')
  sourceUsed=code.includes("join(root,'app','companion_persona.txt')") &&
    code.includes("dsh-live:whale-persona")
  layered=code.includes('dsh-live:whale-core')&&code.includes('dsh-live:whale-style')
  voiceUsesFull=!code.includes('if (!speechOnly && (process.env.DSH_LIVE_ENABLE_P1_PERSONA')
  // Verify the currently mounted bridge code, not a stale version label.
  // Source introspection is a capability check, never evidence that the
  // user's actual conversation has consumed the new text.
  personaHotReloadReady=code.includes('dsh-live:whale-persona') &&
    code.includes('const dynamicPersona=()=>') &&
    code.includes('lastGood=readPersona()')
  voicePersonaShortReady=code.includes('dsh-live:whale-voice-persona') &&
    code.includes('lastGoodVoice=readVoicePersona()')
  const p=JSON.parse(readFileSync(join(homedir(),'.dsh','profiles','web','node_modules','dsh-live-bridge','package.json'),'utf8'))
  version=String(p.version||'unknown')
 }catch{}
 return {configured:fileConfigured,reads_on_new_agent:sourceUsed,
  layered_runtime:layered,voice_full_persona:voiceUsesFull,plugin_version:version,
  active_session_verified:false,
  persona_hot_reload_ready:personaHotReloadReady,
  voice_persona_short_ready:voicePersonaShortReady}
}
export function status(){
 const p=readPersona()
 return {schema:1,source:'app/companion_persona.txt',...p,
   ...layers(p.text),growth:growthInfo(),dsh:dshInfo()}
}
export function save(input){
 if(!input||typeof input!=='object'||Array.isArray(input)||
    Object.keys(input).sort().join(',')!=='confirmation,expected_sha256,text')
   fail('invalid_persona_save_request')
 if(input.confirmation!=='确认保存这版人设')fail('persona_save_confirmation_required')
 if(typeof input.expected_sha256!=='string'||!/^[a-f0-9]{64}$/.test(input.expected_sha256))
   fail('invalid_persona_revision')
 if(typeof input.text!=='string'||input.text.includes('\0')||
    Buffer.byteLength(input.text)>8192||input.text.trim().length<30)
   fail('invalid_persona_content')
 const existing=readPersona()
 if(input.expected_sha256!==existing.sha256)fail('persona_revision_conflict')
 if(input.text===existing.text)return {saved:false,unchanged:true,...status()}
 const parent=resolve(SOURCE,'..')
 if(realpathSync(parent)!==parent||!statSync(parent).isDirectory())fail('persona_directory_unsafe')
 mkdirSync(BACKUPS,{recursive:true,mode:0o700})
 const backupSt=statSync(BACKUPS)
 if((backupSt.mode&0o077)!==0||backupSt.uid!==process.getuid()||
    lstatSync(BACKUPS).isSymbolicLink())fail('persona_backup_directory_unsafe')
 const backup=join(BACKUPS,'persona-'+existing.sha256.slice(0,18)+'-'+randomUUID()+'.txt')
 writeFileSync(backup,existing.text,{flag:'wx',mode:0o600})
 const temp=SOURCE+'.'+randomUUID()+'.tmp'
 try{
  writeFileSync(temp,input.text,{flag:'wx',mode:0o600})
  chmodSync(temp,lstatSync(SOURCE).mode&0o777)
  if(readPersona().sha256!==existing.sha256)fail('persona_revision_conflict')
  renameSync(temp,SOURCE)
 }finally{if(existsSync(temp))unlinkSync(temp)}
 const latest=readPersona()
 if(latest.sha256!==SHA(input.text))fail('persona_verify_failed')
 return {saved:true,unchanged:false,backup_created:true,
   ...status()}
}
const self=resolve(fileURLToPath(import.meta.url))
if(process.argv[1]&&realpathSync(resolve(process.argv[1]))===realpathSync(self)){
 const action=process.argv[2]
 if(!['status','save'].includes(action))process.exit(2)
 try{
  const input=action==='save'?JSON.parse(readFileSync(0,'utf8')):{}
  const result=action==='save'?save(input):status()
  process.stdout.write('R310_PERSONA_RESULT '+JSON.stringify({ok:true,action,...result})+'\n')
 }catch(e){
  process.stderr.write('R310_PERSONA_ERROR '+String(e.message||'failed').slice(0,120)+'\n')
  process.exitCode=2
 }
}
