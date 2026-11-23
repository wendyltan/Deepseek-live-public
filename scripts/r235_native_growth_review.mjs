// Trusted Mac-only manual review transport. No DSH Agent, turn, audio or
// automatic learning. All writes require explicit confirmation from Swift UI.
// Production credentials must already exist as TWO different private files;
// this script never creates tokens, enables growth, or edits config.
import {readFileSync,lstatSync,statSync} from 'node:fs'
import {homedir} from 'node:os'
import {join} from 'node:path'
import http from 'node:http'
const BASE=join(homedir(),'.dsh','secrets')
const BRIDGE=join(BASE,'deepseek-live-bridge.token')
const ADMIN=join(BASE,'deepseek-live-growth-admin.token')
const URL_PATH='/dsh-live-bridge/memory-manage'
const ACTIONS=Object.freeze({
 status:'growth.version',list:'growth.list',propose:'growth.propose',
 accept:'growth.decide',reject:'growth.decide',rollback:'growth.rollback',
 consent:'consent',suggestions:'growth.suggestion-consent',
})
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
export function privateToken(path) {
 const s=lstatSync(path)
 if(!s.isFile()||s.isSymbolicLink()||s.nlink!==1||
    (s.mode & 0o077)!==0||(typeof process.getuid==='function'&&s.uid!==process.getuid())||
    s.size<32||s.size>256)throw new Error('review_private_credentials_unavailable')
 const value=readFileSync(path,'utf8').trim()
 if(value.length<32||value.length>256||!/^[\x21-\x7e]+$/.test(value))
   throw new Error('review_private_credentials_unavailable')
 return value
}
export function requestFor(action,body={}) {
 if(!Object.hasOwn(ACTIONS,action) || !body ||
    typeof body!=='object'||Array.isArray(body))throw new Error('review_invalid_action')
 const allowed={
  status:[],list:['status'],
  propose:['text'],
  accept:['id','expectedRevision'],reject:['id','expectedRevision'],
  rollback:['toVersion','expectedRevision'],consent:[],
  suggestions:['allow','expectedRevision'],
 }[action]
 if(Object.keys(body).some(k=>!allowed.includes(k)))throw new Error('review_unexpected_fields')
 const out={protocolVersion:1,action:ACTIONS[action]}
 if(action==='list') {
  if(body.status!==undefined && !['new','all','accepted','rejected'].includes(body.status))
   throw new Error('review_invalid_status')
  if(body.status)out.status=body.status
 }else if(action==='propose') {
  if(typeof body.text!=='string'||!body.text.trim()||
    Buffer.byteLength(body.text)>512)throw new Error('review_invalid_fact')
  out.text=body.text.trim()
  out.confirm='USER_EXPLICIT_GROWTH_PROPOSAL'
 }else if(action==='accept'||action==='reject'){
  if(!UUID.test(body.id??'')||!Number.isSafeInteger(body.expectedRevision)||
     body.expectedRevision<0)throw new Error('review_invalid_revision')
  out.id=body.id
  out.expectedRevision=body.expectedRevision
  out.decision=action
  out.confirm=action==='accept'?'ACCEPT_GROWTH_FACT':'REJECT_GROWTH_FACT'
 }else if(action==='rollback'){
  if(!Number.isSafeInteger(body.toVersion)||body.toVersion<0||
     !Number.isSafeInteger(body.expectedRevision)||body.expectedRevision<0)
    throw new Error('review_invalid_revision')
  out.toVersion=body.toVersion;out.expectedRevision=body.expectedRevision
  out.confirm='ROLLBACK_GROWTH_VERSION'
 }else if(action==='suggestions') {
  if(typeof body.allow!=='boolean' ||
     !Number.isSafeInteger(body.expectedRevision)||body.expectedRevision<0)
    throw new Error('review_invalid_consent')
  out.allow=body.allow
  out.expectedRevision=body.expectedRevision
  out.confirm='GROWTH_SUGGESTIONS_CONSENT'
 }else if(action==='consent'){
  out.confirm='MANUAL_MEMORY_CONSENT';out.allow=true
 }
 return out
}
export function postLocal(hostPort,token,admin,action,payload) {
 return new Promise((resolve,reject)=>{
  const json=JSON.stringify(requestFor(action,payload))
  const req=http.request({hostname:'127.0.0.1',port:hostPort,path:URL_PATH,
   method:'POST',agent:false,
   headers:{Authorization:'Bearer '+token,'x-dsh-live-memory-token':admin,
    'Content-Type':'application/json','Content-Length':Buffer.byteLength(json)},
   timeout:2500},res=>{
    const chunks=[];let bytes=0
    res.on('data',part=>{bytes+=part.length;if(bytes>100000){req.destroy(new Error('review_response_too_large'));return}
      chunks.push(part)})
    res.on('end',()=>{
      try{
       const body=JSON.parse(Buffer.concat(chunks).toString('utf8'))
       if(typeof body!=='object'||!body||Array.isArray(body))throw Error('review_invalid_reply')
       resolve({code:res.statusCode,body})
      }catch(err){reject(new Error('review_invalid_reply'))}
    })
  })
  req.on('timeout',()=>req.destroy(new Error('review_timeout')))
  req.on('error',()=>reject(new Error('review_service_unavailable')))
  req.end(json)
 })
}
async function main(){
 if(process.argv.length!==2)throw new Error('review_args_forbidden')
 const parts=[]
 for await(const b of process.stdin){parts.push(b);if(Buffer.concat(parts).length>4096)throw Error('review_request_too_large')}
 const item=JSON.parse(Buffer.concat(parts).toString('utf8'))
 const action=item?.action
 const params=item?.payload??{}
 const payload=requestFor(action,params)
 // Fail closed in a normal install. Do not quietly provision real admin
 // authorization or toggle the manual-memory/growth flags for the user.
 let bridge,admin
 try{
  bridge=privateToken(BRIDGE);admin=privateToken(ADMIN)
  if(bridge===admin)throw Error('same_token')
 }catch{
  console.log('GROWTH_REVIEW_RESULT '+JSON.stringify({ok:false,configured:false,
    error:'review_admin_not_configured'}))
  return
 }
 const result=await postLocal(3080,bridge,admin,action,params)
 const output={ok:result.code===200,configured:true,
  code:result.code,...result.body}
 console.log('GROWTH_REVIEW_RESULT '+JSON.stringify(output))
}
if(process.argv[1] && import.meta.url===new URL('file://'+process.argv[1]).href){
 try{await main()}catch(err){
  console.log('GROWTH_REVIEW_RESULT '+JSON.stringify({ok:false,configured:false,
   error:String(err.message||'review_failed').slice(0,70)}))
  process.exitCode=2
 }
}
