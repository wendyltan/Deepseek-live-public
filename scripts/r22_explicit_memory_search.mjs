/** Read only upon explicit user-issued query. Never inside idle / TTS / DSH tool. */
import {fileURLToPath} from 'node:url'
import {resolve} from 'node:path'
import {openManualMemory} from '../plugins/dsh-live-bridge/lib/manual-memory.js'
import {queryUserApprovedMemory} from '../plugins/dsh-live-bridge/lib/manual-memory-query.js'
import {ROOT,VAULT} from './r18_manual_memory_cli.mjs'
export function searchExplicit(query,{root=ROOT,vaultDir=VAULT}={}){
  const vault=openManualMemory(root,vaultDir)
  try{return queryUserApprovedMemory(vault,query)}finally{vault.close()}
}
if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const query=process.argv.slice(2).join(' ')
  try{
    if(!query || query.length>200)throw new Error('manual_query_invalid')
    const result=searchExplicit(query)
    console.log(JSON.stringify(result))
  }catch(err){console.error('MANUAL_MEMORY_LOOKUP_UNAVAILABLE',err.message);process.exitCode=2}
}
