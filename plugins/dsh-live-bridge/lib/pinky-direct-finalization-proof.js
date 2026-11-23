/** R626 generic finalization of a single *direct* native phone task.
 *
 * Do not infer app-specific business outcomes from successful tool transport.
 * Proves only that the original official task ran to completion and has
 * a producer-correlated settled phone screen at/after its last action.
 * No screenshots, text, identities, counts or tool arguments are exported.
 */
const PREFIX='mcp__pinky_dafeiyu__phone_'
const SCREEN_ALLOWED=new Set(['connect','apps','observe','launch','tap','type',
  'swipe','key','wait_for','release'])
// R686: phone_handoff is a producer-confirmed connection recovery step.
// It may occur BEFORE the last real phone action, but never count as an
// action, terminal result, or evidence of a settled screen.
const DIRECT_ALLOWED=new Set([...SCREEN_ALLOWED,'handoff'])
const MODIFIERS=new Set(['launch','tap','type','swipe','key'])
const READS=new Set(['observe','wait_for'])

export function nativePinkySettledScreen(name,message) {
  if(typeof name!=='string'||!name.startsWith(PREFIX)||
     !SCREEN_ALLOWED.has(name.slice(PREFIX.length))||
     message?.role!=='tool'||message?.source?.kind!=='tool'||
     typeof message?.toolCallId!=='string'||!message.toolCallId||
     message.source.callId!==message.toolCallId||
     message.isError!==false||!Array.isArray(message.content))
    return false
  const text=message.content.find(x=>x?.type==='text'&&
    typeof x.text==='string')?.text
  if(typeof text!=='string'||text.length>120000)return false
  const lines=text.split('\n')
  return /^settled(?:\s*·|$)/.test(lines[0]||'')&&
    lines.slice(1,6).some(x=>
      /^screen\s+\d{2,5}x\d{2,5}\s*·\s*app:\s*\S/i.test(x))
}

export function nativePinkyDirectFinalized(tools) {
  if(!tools||typeof tools.values!=='function')return false
  const rows=[...tools.values()]
  if(rows.length<3||rows.length>64||
    rows.some(r=>r?.outcome!=='success'||typeof r.name!=='string'||
      !r.name.startsWith(PREFIX)))return false
  const kinds=rows.map(r=>r.name.slice(PREFIX.length))
  if(kinds.some(k=>!DIRECT_ALLOWED.has(k))||kinds[0]!=='connect'||
     kinds.at(-1)!=='release'||kinds.filter(k=>k==='connect').length!==1||
     kinds.filter(k=>k==='release').length!==1)return false
  const last=kinds.reduce((prev,k,i)=>MODIFIERS.has(k)?i:prev,-1)
  if(last<1||last>=kinds.length-1)return false
  // Anything after the final action must only read/wait for a screen.
  if(kinds.slice(last+1,-1).some(k=>!READS.has(k)))return false
  // The action's own settled screen counts; alternatively a subsequent
  // observe/wait_for. A screen *before* the last action is stale.
  return rows.slice(last,-1).some(r=>r.settledScreen===true)
}
