import test from 'node:test'
import {strict as assert} from 'node:assert'
import {nativePinkyRecoveredNavigation as status} from '../lib/pinky-recovered-step-proof.js'
const p='mcp__pinky_dafeiyu__phone_'
const row=(name,outcome='success')=>({name:p+name,outcome})
const proof=a=>status(new Map(a.map((v,i)=>[String(i),v])))
test('one native failed tap followed by successful native navigation & release is recovered only',()=>{
 const actual=[row('connect'),row('launch'),row('tap','failed'),
   row('tap'),row('type'),row('tap'),row('observe'),row('tap'),row('release')]
 assert.equal(proof(actual),'navigation_retried_final_unconfirmed')
})
test('never promote a business result or paper over unrecovered failures',()=>{
 for(const rows of [
  [row('connect'),row('tap','failed'),row('release')],
  [row('connect'),row('tap','failed'),row('tap','failed'),row('tap'),row('release')],
  [row('connect'),row('type','failed'),row('type'),row('release')],
  [row('connect','failed'),row('tap','failed'),row('tap'),row('release')],
  [row('connect'),row('tap','failed'),row('tap'),row('release','failed')],
  [row('connect'),row('tap','failed'),row('tap')],
  [row('connect'),row('tap','failed'),{name:'web_search',outcome:'success'},row('tap'),row('release')],
 ]) assert.equal(proof(rows),null)
})
