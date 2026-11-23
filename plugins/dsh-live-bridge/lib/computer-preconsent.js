/** R676: deliberate user preconsent applies only to native CUA application
 * access for any selected application. No implicit grant for other actions.
 * The native CUA provider still verifies code-signing identity and macOS TCC.
 */
import { lstatSync,readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
const file=join(homedir(),'Library/Application Support/Deepseek-live/companion-native/r676-computer-preconsent.json')
export function localMacPreconsent(){
  try{
    const s=lstatSync(file)
    if(!s.isFile()||s.isSymbolicLink()||s.nlink!==1||
       s.uid!==process.getuid()||(s.mode&0o077)!==0||
       s.size<50||s.size>1024)return false
    const j=JSON.parse(readFileSync(file,'utf8'))
    return j.schema===1&&j.allow_all_native_cua_apps===true&&
      j.chosen_by_mac_app===true&&
      j.scope==='native_cua_app_access_all_apps'
  }catch{return false}
}
export function preapprovedNativeCuaChoice(request,enabled){
  if(enabled!==true||request?.signal?.aborted||
     !Array.isArray(request?.questions)||request.questions.length!==1)
    return null
  const q=request.questions[0]
  if(q?.id!=='cua-app-access'||typeof q.question!=='string'||
     typeof q.detail!=='string'||!Array.isArray(q.options))return null
  const choices=q.options.map(x=>x?.label)
  if(choices[0]!=='Allow for this task'||choices[1]!=='Deny'||
     choices.length>3||
     (choices.length===3&&choices[2]!=='Always allow'))return null
  // These three fields must match the official CUA provider's
  // application-access prompt verbatim, not an arbitrary DSH question.
  // A trusted native CUA request is additionally bound to the live Agent,
  // tool and session by the caller.
  const name=q.question.slice(
    'Allow Computer Use to launch if needed, read, capture, and control '.length,
    -1)
  if(!q.question.startsWith(
       'Allow Computer Use to launch if needed, read, capture, and control ')||
     !q.question.endsWith('?')||!name||name.length>160||
     /[\r\n]/.test(name))return null
  const prefix='Application: '
  const marker='\nTask access applies to the selected application instance'
  if(!q.detail.startsWith(prefix)||!q.detail.includes(marker))return null
  const path=q.detail.slice(prefix.length,q.detail.indexOf(marker))
  if(!path.startsWith('/')||path.includes('\n')||
     path.length>1024)return null
  return {answers:[{id:'cua-app-access',selected:['Allow for this task']}]}
  return null
}
