import test from 'node:test'
import {strict as assert} from 'node:assert'
import {nativePinkySettledScreen,nativePinkyDirectFinalized} from '../lib/pinky-direct-finalization-proof.js'
const pre='mcp__pinky_dafeiyu__phone_'
const row=(name,more={})=>({name:pre+name,outcome:'success',...more})
const result=(text,more={})=>({
  role:'tool',source:{kind:'tool',callId:'c123'},toolCallId:'c123',
  isError:false,content:[{type:'text',text}],...more
})
const settled='settled · device: phone\nscreen 1080x2400 · app: Example\n[1] view'

const check=xs=>nativePinkyDirectFinalized(new Map(xs.map((x,i)=>[i,x])))
test('producer-trusted settled screen is a proof of read, not business success',()=>{
  assert.equal(nativePinkySettledScreen(pre+'tap',result(settled)),true)
  assert.equal(nativePinkySettledScreen(pre+'observe',result(settled)),true)
  for(const bad of [
    result('running · device: phone\nscreen 1080x2400 · app: Example'),
    result('settled · task finished without a screen'),
    result(settled,{source:{kind:'assistant',callId:'c123'}}),
    result(settled,{source:{kind:'tool',callId:'wrong'}}),
    result(settled,{isError:true}),
    result(settled,{toolCallId:'wrong'}),
    result('settled · device: phone\nscreen unknown · app: Example'),
  ]) assert.equal(nativePinkySettledScreen(pre+'tap',bad),false)
  assert.equal(nativePinkySettledScreen('other_tool',result(settled)),false)
})

test('generic direct calls finalize across apps and action sequences',()=>{
  const good=[
    row('connect'),row('launch'),row('tap'),row('type'),
    row('tap'),row('observe',{settledScreen:true}),row('release')]
  assert.equal(check(good),true)
  assert.equal(check([row('connect'),row('tap',{settledScreen:true}),row('release')]),true)
  assert.equal(check([row('connect'),row('launch'),row('swipe'),
    row('key',{settledScreen:true}),row('release')]),true)
  assert.equal(check([row('connect'),row('tap'),row('wait_for',{settledScreen:true}),
    row('release')]),true)
  // Real 14-operation pattern, no cart/WeChat/source text in the proof.
  assert.equal(check([row('connect'),row('launch'),row('tap'),row('type'),
    row('tap'),row('observe'),...Array.from({length:7},()=>row('tap')),
    row('tap',{settledScreen:true}),row('release')]),true)
})

test('R686 observed phone_handoff recovery BEFORE verified final action is general direct success',()=>{
  // Exact name/order of the latest eight real native Pinky receipts.
  const actual=[row('connect'),row('handoff'),row('handoff'),row('launch'),
    row('tap'),row('type'),row('observe',{settledScreen:true}),row('release')]
  assert.equal(check(actual),true)
  assert.equal(nativePinkySettledScreen(pre+'handoff',result(settled)),false)
  // A handoff does not count as a settled view, and a handoff AFTER the
  // latest action invalidates the proof of the last screen.
  const bad=[
    [row('connect'),row('handoff'),row('release')],
    [row('connect'),row('handoff'),row('observe',{settledScreen:true}),row('release')],
    [row('connect'),row('handoff'),row('tap'),row('observe'),row('release')],
    [row('connect'),row('handoff',{outcome:'failed'}),row('tap'),
      row('observe',{settledScreen:true}),row('release')],
    [row('connect'),row('tap'),row('handoff'),row('observe',{settledScreen:true}),row('release')],
    [row('connect'),row('tap'),row('observe',{settledScreen:true}),
      row('handoff'),row('release')],
    [row('connect'),row('handoff'),row('tap'),row('observe',{settledScreen:true}),
      row('task_run'),row('release')],
  ]
  for(const sequence of bad)assert.equal(check(sequence),false,
    sequence.map(r=>r.name).join('|'))
})

test('pending, failed, crossed, delegated or stale screens are never success',()=>{
  const negatives=[
    [row('connect'),row('tap',{settledScreen:true,outcome:'failed'}),row('release')],
    [row('connect'),row('tap',{settledScreen:true,outcome:'pending'}),row('release')],
    [row('connect'),row('tap',{settledScreen:true})],
    [row('connect'),row('observe',{settledScreen:true}),row('release')],
    [row('connect'),row('observe',{settledScreen:true}),row('tap'),row('release')],
    [row('connect'),row('tap'),row('observe',{settledScreen:false}),row('release')],
    [row('connect'),row('tap',{settledScreen:true}),row('launch'),row('release')],
    [row('connect'),row('tap',{settledScreen:true}),row('tap'),row('release')],
    [row('connect'),row('task_run',{settledScreen:true}),row('task_wait'),row('release')],
    [row('connect'),row('tap',{settledScreen:true}),row('device'),row('release')],
    [row('connect'),{name:'web_search',outcome:'success',settledScreen:true},row('release')],
    [row('connect'),row('connect'),row('tap',{settledScreen:true}),row('release')],
    [row('connect'),row('tap',{settledScreen:true}),row('release'),row('release')],
    [row('tap',{settledScreen:true}),row('release')],
    [row('connect'),row('tap',{settledScreen:true}),row('release',{outcome:'failed'})],
  ]
  for(const rows of negatives)assert.equal(check(rows),false,
    rows.map(x=>x.name).join(','))
})
