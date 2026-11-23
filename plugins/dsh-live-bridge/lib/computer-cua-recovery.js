/** R678: scoped recovery of the official CUA preselection-only error.
 * Three exact native events are required:
 *  (1) getState fails with APP_ACCESS_REQUIRED before getApp;
 *  (2) getApp succeeds and returns a native app handle;
 *  (3) getState succeeds with that same handle and a window snapshot.
 * The original first failure is retained in tool receipts. Never recover
 * permission refusal, denied TCC, mutation, unsupported tools or other errors.
 * No application screen/text or tool arguments are persisted or exposed.
 */
import {createHash} from 'node:crypto'
const ERROR='Error: APP_ACCESS_REQUIRED: Select the application with getApp before reading or controlling it'

export function cuaMethod(args){
  if(typeof args!=='string'||args.length>8192)return null
  try{
    const q=JSON.parse(args)
    if(!q||typeof q!=='object'||Array.isArray(q))return null
    return ['getState','getApp'].includes(q.method)&&
      q.params&&typeof q.params==='object'&&!Array.isArray(q.params)
      ? q.method : null
  }catch{return null}
}
function nativeText(message){
  if(message?.role!=='tool'||message?.source?.kind!=='tool'||
     !Array.isArray(message?.content)||message.content.length!==1)
    return null
  const t=message.content[0]
  return t?.type==='text'&&typeof t.text==='string'&&
    t.text.length<=100000 ? t.text : null
}
function fingerprint(s){
  return createHash('sha256').update(s,'utf8').digest('hex').slice(0,32)
}
export function noteCuaResult(tool,message){
  if(tool?.name!=='cua'||!tool.cuaMethod)return
  const text=nativeText(message)
  if(text===null)return
  if(tool.cuaMethod==='getState'&&
     message.isError===true&&text.trim()===ERROR){
    tool.cuaPreselectionMissing=true
    return
  }
  if(message.isError!==false)return
  let parsed
  try{parsed=JSON.parse(text)}catch{return}
  if(!parsed||Array.isArray(parsed)||typeof parsed!=='object'||
     typeof parsed.appHandle!=='string'||parsed.appHandle.length<8||
     parsed.appHandle.length>512||!Number.isSafeInteger(parsed.pid)||
     parsed.pid<=0)return
  const hash=fingerprint(parsed.appHandle)
  if(tool.cuaMethod==='getApp'){
    if(typeof parsed.name==='string'&&parsed.name.length>0&&
       parsed.name.length<=160)
      tool.cuaSelectedHandleHash=hash
  }else if(tool.cuaMethod==='getState'&&
    Array.isArray(parsed.windows)&&parsed.windows.length>0&&
    parsed.windows.length<=100&&
    typeof parsed.tree==='string'&&parsed.tree.length>0)
    tool.cuaObservedHandleHash=hash
}
export function verifiedCuaPreselectionRecovery(task){
  if(task?.phoneMode==='pinky'||task?.turnEnd!=='completed'||
     task?.textAfterTools!==true||typeof task?.text!=='string'||
     !task.text.trim()||task.approvalRejected===true||
     task.approvalOutstanding===true||
     !/查看|看看|当前|现在|页面|窗口|标签|读取|哪个|什么|在哪/.test(task.prompt??'')||
     /删除|发送|购买|支付|点击|修改|移动|发布|输入|重命名|安装|关掉|关闭/.test(task.prompt??''))
    return false
  const tools=[...(task.tools?.values?.()??[])]
  if(tools.length!==3||tools.some(t=>t.name!=='cua'))return false
  const [first,second,third]=tools
  return first.cuaMethod==='getState'&&
    first.outcome==='failed'&&first.cuaPreselectionMissing===true&&
    second.cuaMethod==='getApp'&&second.outcome==='success'&&
    typeof second.cuaSelectedHandleHash==='string'&&
    third.cuaMethod==='getState'&&third.outcome==='success'&&
    second.cuaSelectedHandleHash===third.cuaObservedHandleHash
}
