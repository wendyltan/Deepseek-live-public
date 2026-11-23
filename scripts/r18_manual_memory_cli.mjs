/* R18: privacy-first manual memory consent and per-fact review.
 * Uses the existing E1b vault; never reads DSH chats, audio or transcripts.
 * No LLM, no ReMe autosave, no network, no arbitrary path argument in CLI.
 */
import {createInterface} from 'node:readline/promises'
import {stdin,stdout} from 'node:process'
import {fileURLToPath} from 'node:url'
import {resolve,join} from 'node:path'
import {openManualMemory} from '../plugins/dsh-live-bridge/lib/manual-memory.js'

export const ROOT=resolve(fileURLToPath(new URL('..',import.meta.url)))
export const VAULT=join(ROOT,'tmp','companion-memory-e1b')
export const CONSENT_WORDS='同意手动保存'
export const SAVE_WORDS='确认保存这一条'
export const DELETE_WORDS='确认仅删除本地这一条'

export function listOwnerFacts(vault) {
 const state=vault.list()
 return {count:state.items.length,manual_write:state.consent.manual_write,
         auto_extraction:state.consent.auto_extraction,
         facts:state.items.map(x=>({id:x.id,revision:x.revision,source:x.source}))}
}
export function optIn(vault,confirmed){
 if(confirmed!==CONSENT_WORDS)throw new Error('manual_consent_not_confirmed')
 vault.setManualConsent(true)
 return listOwnerFacts(vault)
}
export function saveFact(vault,text,confirmed){
 if(confirmed!==SAVE_WORDS)throw new Error('fact_not_confirmed')
 if(typeof text!=='string'||!text.trim()||text.length>1024)
   throw new Error('invalid_manual_fact')
 const item=vault.put({text:text.trim(),source:'user_explicit'})
 return {id:item.id,revision:item.revision,source:'user_explicit'}
}
export function deleteFact(vault,id,revision,confirmed){
 if(confirmed!==DELETE_WORDS)throw new Error('deletion_not_confirmed')
 if(typeof id!=='string'||!/^[0-9a-fA-F-]{36}$/.test(id)||
    !Number.isSafeInteger(revision)||revision<1)
   throw new Error('invalid_deletion_identity')
 // This only removes the E1b local item, NOT all DSH history/backups.
 return vault.remove(id,revision)
}
export async function main(action,args=process.argv.slice(3)){
 if(!['status','consent','save','delete'].includes(action)||args.length>(action==='delete'?2:0))
   throw new Error('unsupported_memory_action')
 const vault=openManualMemory(ROOT,VAULT)
 try{
  if(action==='status'){console.log('E1B_OWNER_LOCAL_ONLY',JSON.stringify(listOwnerFacts(vault)));return}
  if(!stdin.isTTY)throw new Error('interactive_tty_required_for_memory_changes')
  const consolePrompt=createInterface({input:stdin,output:stdout})
  try{
   if(action==='consent'){
    console.log('仅准许用户一条条确认后手动保存；自动抓取始终关闭。')
    const phrase=await consolePrompt.question('如同意请输入「'+CONSENT_WORDS+'」: ')
    console.log('MANUAL_MEMORY_CONSENT_RESULT',
                JSON.stringify(optIn(vault,phrase)));return
   }
   if(action==='save'){
    if(!vault.list().consent.manual_write)throw new Error('manual_memory_consent_off')
    const text=await consolePrompt.question('请亲自输入一条希望记住的事实: ')
    console.log('仅保存此条，不读取聊天或语音，不同步云端。')
    const phrase=await consolePrompt.question('输入「'+SAVE_WORDS+'」确认: ')
    console.log('MANUAL_FACT_SAVED',JSON.stringify(saveFact(vault,text,phrase)));return
   }
   if(action==='delete'){
    if(args.length!==2)throw new Error('delete_requires_id_and_revision')
    console.log('只撤销这一个本地E1b事实，不代表所有派生索引或历史都已删除。')
    const phrase=await consolePrompt.question('输入「'+DELETE_WORDS+'」确认: ')
    console.log('MANUAL_FACT_DELETION',JSON.stringify(
        deleteFact(vault,args[0],Number(args[1]),phrase)));return
   }
  }finally{consolePrompt.close()}
 }finally{vault.close()}
}
if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 main(process.argv[2]||'status').catch(e=>{
  console.error('E1B_MANUAL_ONLY',e.message||'unavailable')
  process.exitCode=2
 })
}
