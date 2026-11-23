// Strict owner-driven Mac native memory action. No session scraping or auto writes.
// A trusted UI must obtain a separate confirmation for consent and each fact.
// Project paths are pinned; nothing here reads user's chats or recordings.
import {readFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {resolve} from 'node:path'
import {execFileSync} from 'node:child_process'
import {openManualMemory} from '../plugins/dsh-live-bridge/lib/manual-memory.js'
import {ROOT,VAULT,CONSENT_WORDS,SAVE_WORDS,listOwnerFacts,optIn,saveFact}
  from './r18_manual_memory_cli.mjs'
const self=resolve(fileURLToPath(import.meta.url))
export function applyAction(vault,action,input){
  if(!input||typeof input!=='object'||Array.isArray(input))throw Error('bad_action_payload')
  if(action==='status')return listOwnerFacts(vault)
  if(action==='consent'){
    if(Object.keys(input).sort().join(',')!=='confirm')throw Error('bad_consent_payload')
    return optIn(vault,input.confirm)
  }
  if(action==='save'){
    if(Object.keys(input).sort().join(',')!=='confirm,text')throw Error('bad_save_payload')
    return saveFact(vault,input.text,input.confirm)
  }
  throw Error('unsupported_native_memory_action')
}
// R309: the metadata-only sidecar is optional. If an outdated exporter
// fails *after* E1b commit, the user must still receive a true success
// receipt. It never affects the owner's canonical vault transaction.
export function tryRefreshOverview(run=execFileSync){
  try{
    run('/opt/homebrew/bin/python3',['-m','scripts.export_native_memory_overview',
      '--vault',VAULT],{cwd:ROOT,timeout:12000,stdio:'ignore'})
    return true
  }catch{return false}
}
function main(){
  const action=process.argv[2]
  if(!['status','consent','save'].includes(action))throw Error('invalid_action')
  const payload=readFileSync(0,'utf8')
  if(Buffer.byteLength(payload)>2048)throw Error('payload_too_large')
  const request=JSON.parse(payload||'{}')
  const vault=openManualMemory(ROOT,VAULT)
  let result
  try{result=applyAction(vault,action,request)}
  finally{vault.close()}
  // R309: E1b is the source of truth. This sidecar is a compatibility
  // snapshot only. If export fails AFTER a successful consent/write, report
  // the successful canonical action; the GUI must not falsely claim failure.
  const overview_current=action==='status' || tryRefreshOverview()
  console.log('NATIVE_MEMORY_RESULT '+JSON.stringify({
    action,ok:true,manual_write:result.manual_write ?? true,
    count:result.count ?? 1,revision:result.revision ?? null,auto_extraction:false,
    overview_current
  }))
}
if(process.argv[1]&&resolve(process.argv[1])===self){
  try{main()}catch(error){
    console.error('NATIVE_MEMORY_ERROR '+String(error.message||error).slice(0,110))
    process.exitCode=2
  }
}
