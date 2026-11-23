/** R584 - narrow, producer-trusted evidence of recovered navigation.
 * A failed tap followed by a successful tap is a recovery of an interaction,
 * NOT proof of shopping, sending, checkout, or any business completion.
 * Never reads/returns screenshots, user words, coordinates, token or tool args.
 */
const PREFIX='mcp__pinky_dafeiyu__phone_'

export function nativePinkyRecoveredNavigation(tools) {
  if(!tools||typeof tools.values!=='function')return null
  const rows=[...tools.values()]
  if(rows.length<4||rows.length>64||rows.some(r=>
    !r||typeof r.name!=='string'||!r.name.startsWith(PREFIX)||
    !['success','failed'].includes(r.outcome)))return null
  const failures=rows.flatMap((r,i)=>r.outcome==='failed'?[i]:[])
  if(failures.length!==1)return null
  const failedAt=failures[0]
  const failed=rows[failedAt]
  if(failed.name!==PREFIX+'tap')return null
  if(!rows.slice(0,failedAt).some(r=>
    r.name===PREFIX+'connect'&&r.outcome==='success'))return null
  const after=rows.slice(failedAt+1)
  if(!after.some(r=>r.name===PREFIX+'tap'&&r.outcome==='success'))return null
  if(after.some(r=>r.outcome!=='success'))return null
  if(rows.at(-1).name!==PREFIX+'release'||rows.at(-1).outcome!=='success')return null
  // The last action may have been a tap; a previous observe is not final
  // business proof. State remains failed until an explicit, verifiable
  // final result is available, but the earlier tap was demonstrably retried.
  return 'navigation_retried_final_unconfirmed'
}
