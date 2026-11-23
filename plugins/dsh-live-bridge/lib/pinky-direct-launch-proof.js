/** R573: positive proof for a single app-opening command using trusted Pinky
 * tool result and the foreground screen header. No screen data is published.
 */
const PREFIX = 'mcp__pinky_dafeiyu__phone_'
const SIMPLE = new Set(['connect','apps','observe','launch','release'])
const APP = /^[\p{L}\p{N}][\p{L}\p{N} ._+-]{0,47}$/u

export function nativePinkyLaunchTarget(name, raw) {
  if (name !== PREFIX+'launch') return null
  let args=raw
  if (typeof raw==='string') {
    if (raw.length>4096) return null
    try {args=JSON.parse(raw)}catch{return null}
  }
  if(!args||typeof args!=='object'||Array.isArray(args)||
     typeof args.app!=='string')return null
  const app=args.app.normalize('NFKC').trim()
  if(!APP.test(app)||app.includes('..'))return null
  return app
}

export function settledPinkyScreenApp(name, message) {
  if(![PREFIX+'launch',PREFIX+'observe',PREFIX+'type'].includes(name)||
     message?.role!=='tool'||message?.source?.kind!=='tool'||
     typeof message?.toolCallId!=='string'||!message.toolCallId||
     message?.source?.callId!==message.toolCallId||
     message?.isError!==false||!Array.isArray(message.content))return null
  const first=message.content.find(x=>x?.type==='text'&&typeof x.text==='string')
  if(!first||first.text.length>120000)return null
  const lines=first.text.split('\n')
  if(!/^settled(?:\s*·|$)/.test(lines[0]||''))return null
  const head=lines.slice(1,5).find(x=>
    /^screen\s+\d{2,5}x\d{2,5}\s*·\s*app:\s*/i.test(x))
  if(!head)return null
  const match=/^screen\s+\d{2,5}x\d{2,5}\s*·\s*app:\s*([^·\r\n]{1,100})/i.exec(head)
  if(!match)return null
  const observed=match[1].split(/\s+\(/,1)[0].normalize('NFKC').trim()
  return APP.test(observed) ? observed : null
}

export function settledPinkyLaunch(name, message, target) {
  if (name!==PREFIX+'launch'||typeof target!=='string'||!APP.test(target))
    return null
  const observed=settledPinkyScreenApp(name,message)
  return observed?.toLocaleLowerCase()===target.toLocaleLowerCase() ? target : null
}

export function nativePinkyConfirmedLaunch(tools) {
  if(!tools||typeof tools.values!=='function')return null
  const rows=[...tools.values()]
  const phone=rows.filter(r=>r?.name?.startsWith(PREFIX))
  if(!phone.length||rows.some(r=>r?.outcome!=='success')||
     phone.some(r=>!SIMPLE.has(r.name.slice(PREFIX.length))))return null
  const launch=phone.filter(r=>r.name===PREFIX+'launch')
  if(launch.length!==1||!launch[0].launchConfirmed)return null
  const at=phone.indexOf(launch[0])
  if(!phone.slice(0,at).some(r=>r.name===PREFIX+'connect')||
     !phone.slice(at+1).some(r=>r.name===PREFIX+'release'))return null
  // A later observe can prove the phone has left that app again. Do not
  // announce that the target is now open in that case.
  if(phone.slice(at+1).some(r=>r.name===PREFIX+'observe' &&
       r.observedApp?.toLocaleLowerCase() !==
       launch[0].launchConfirmed.toLocaleLowerCase()))return null
  return launch[0].launchConfirmed
}


/** R614: producer-correlated proof that typing ended on an actual screen.
 * Does not expose the text, recipient, app contents or claim that a
 * message was delivered. The caller must independently verify that the
 * user explicitly requested a draft WITHOUT sending it.
 */
export function nativePinkyConfirmedUnsentDraft(tools) {
  if (!tools||typeof tools.values!=='function') return false
  const rows=[...tools.values()]
  if (rows.length<3||rows.length>64||
      rows.some(x=>x?.outcome!=='success' ||
        typeof x.name!=='string'||!x.name.startsWith(PREFIX))) return false
  const kinds=rows.map(x=>x.name.slice(PREFIX.length))
  const allowed=new Set(['connect','apps','observe','launch','tap','type',
                          'swipe','key','wait_for','release'])
  if (kinds.some(x=>!allowed.has(x))||
      kinds[0]!=='connect'||kinds.at(-1)!=='release') return false
  // A draft must be the LAST modifying action. Any later tap/key/launch
  // could have submitted or moved the text; a screen read is permitted.
  const lastType=kinds.lastIndexOf('type')
  if(lastType<1 || kinds.slice(lastType+1,-1).some(x=>x!=='observe'))return false
  // A native "success" receipt alone is not proof of an actual post-type
  // screen. Require the settled screen header from the typing result OR
  // a later genuine observe. Both are producer owned / callId matched.
  const type=rows[lastType]
  const followingScreens=rows.slice(lastType+1,-1).filter(x=>
      x.name===PREFIX+'observe' && typeof x.observedApp==='string')
  const app=followingScreens.at(-1)?.observedApp || type.typedScreenApp
  if(typeof app!=='string'||!APP.test(app))return false
  // A later screen reporting a different foreground app invalidates the
  // earlier edit-page evidence. No stale application/target confirmation.
  if(type.typedScreenApp && followingScreens.some(x=>
      x.observedApp.toLocaleLowerCase() !== type.typedScreenApp.toLocaleLowerCase()))
      return false
  return true
}
