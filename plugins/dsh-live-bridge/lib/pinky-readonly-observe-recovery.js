/** R682: proof for one *rejected argument schema* on a read-only search.
 *
 * A malformed phone_observe never reached the device. A later producer-
 * verified settled observation of the same searched app can recover the
 * requested SCREEN QUERY, but only if the original native turn completed.
 * Never treat navigation, writes, approvals, purchases or delegated jobs
 * as recovered merely because some later phone tool succeeded.
 * No screen text, tool arguments, device IDs or user data are exported.
 */
const P='mcp__pinky_dafeiyu__phone_'
const SAFE=new Set(['connect','launch','tap','type','observe','release','wait_for'])

export function rejectedObserveSchema(name,message) {
  if(name!==P+'observe' || message?.role!=='tool' ||
     message?.source?.kind!=='tool' ||
     !message.toolCallId || message.source.callId!==message.toolCallId ||
     message.isError!==true || !Array.isArray(message.content))return false
  const t=message.content.find(x=>x?.type==='text'&&typeof x.text==='string')?.text
  return typeof t==='string'&&t.length<=600&&
    /^Error: validating "arguments": validating root: unexpected additional properties \[[^\]]{1,80}\]/.test(t)
}
const UNSAFE=/(然后购买|接着购买|并且购买|然后下单|帮我下单|顺便下单|加入购物车|加进购物车|放进购物车|然后发送|顺便发送|发送消息|转账|付款给|提交订单|修改设置|修改地址|删除记录)/

function searchIntent(task) {
  const original=(String(task.prompt||'').split('本次用户原话：').at(-1)||'')
  return original.length<=600 &&
    /(手机|pinky|iphone)/i.test(original) &&
    /(搜索|搜一下|搜一搜)/.test(original) &&
    /(只看|只查看|只浏览|仅查看|仅浏览)/.test(original) &&
    !UNSAFE.test(original)
}
function trustworthyFinal(task) {
  return task && task.phoneMode==='pinky' &&
    task.turnEnd==='completed' && task.textAfterTools===true &&
    typeof task.text==='string' && !!task.text.trim() &&
    !task.approvalOutstanding && !task.approvalRejected &&
    !task.pendingApprovals?.size && task.phonePolicyApplied === true
}
function trustedRows(task) {
  const rows=task.tools instanceof Map?[...task.tools.values()]:[]
  if(rows.length<6||rows.length>16||rows.some(x=>!x||
     typeof x.name!=='string'||!x.name.startsWith(P)||
     !SAFE.has(x.name.slice(P.length))||
     !['success','failed'].includes(x.outcome)))return null
  const kinds=rows.map(x=>x.name.slice(P.length))
  if(kinds[0]!=='connect'||kinds.at(-1)!=='release'||
     kinds.filter(k=>k==='connect').length!==1||
     kinds.filter(k=>k==='release').length!==1||
     kinds.filter(k=>k==='type').length!==1||!kinds.includes('tap'))
      return null
  return {rows,kinds,typeAt:kinds.indexOf('type')}
}
export function completedReadonlySearch(task) {
  if(!trustworthyFinal(task)||!searchIntent(task))return false
  const source=trustedRows(task)
  if(!source)return false
  const {rows,kinds,typeAt}=source
  if(typeAt<=0||rows.some(x=>x.outcome!=='success'))return false
  const post=rows.slice(typeAt+1)
  // Must finish after one real settled, producer-correlated screen
  // observation of the same foreground app, then release the phone.
  // No further tap/key/send/write/delegated action after typing.
  if(post.length!==2||post[0].name!==P+'observe'||
     post[0].settledScreen!==true||post[0].outcome!=='success'||
     post[1].name!==P+'release'||post[1].outcome!=='success')
    return false
  const app=rows[typeAt].typedScreenApp
  const verified=post[0].observedApp
  return typeof app==='string'&&!!app&&typeof verified==='string'&&
    app.toLocaleLowerCase()===verified.toLocaleLowerCase()
}

export function recoveredReadonlySearch(task) {
  if(!trustworthyFinal(task)||!searchIntent(task))return false
  const source=trustedRows(task)
  if(!source)return false
  const {rows,kinds,typeAt}=source
  const failed=rows.flatMap((x,i)=>x.outcome==='failed'?[i]:[])
  if(failed.length!==1)return false
  const at=failed[0],failedRow=rows[at]
  if(failedRow.name!==P+'observe'||failedRow.schemaRejected!==true||
     typeAt<=0||typeAt>=at)return false
  const later=rows.slice(at+1)
  if(later.length!==2||later[0].name!==P+'observe'||
     later[0].outcome!=='success'||later[0].settledScreen!==true||
     later[1].name!==P+'release'||later[1].outcome!=='success')return false
  const typed=rows[typeAt].typedScreenApp
  const observed=later[0].observedApp
  return typeof typed==='string'&&!!typed&&typeof observed==='string'&&
    typed.toLocaleLowerCase()===observed.toLocaleLowerCase()
}
