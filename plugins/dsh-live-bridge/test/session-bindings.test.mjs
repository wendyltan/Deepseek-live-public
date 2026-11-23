import assert from 'node:assert/strict'
import test from 'node:test'
import { mkdtempSync, rmSync, existsSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { openBindingLedger, turnDigest } from '../lib/session-bindings.js'

const dummySession='881e7d1a-9a98-4ffb-ad8b-42492494606c'
const owner={provider:'offline-test',model:'deterministic-local'}
function fixture() {
 const root=mkdtempSync(join(tmpdir(),'whale-private-ledger-'))
 return {root,dir:join(root,'tmp/isolated-state'),close(){rmSync(root,{recursive:true,force:true})}}
}
test('private ledger retains binding and terminal turn across clean reload',()=>{
 const f=fixture()
 let store
 try{
   store=openBindingLedger(f.root,f.dir,()=>1700000000000)
   store.putBinding('e1_real_conversation',dummySession,owner)
   store.reserveTurn('e1_real_turn_01','e1_real_conversation','一个虚构问题','test-task-one')
   assert.equal(store.getTurn('e1_real_turn_01').digest,
     turnDigest('e1_real_conversation','一个虚构问题'))
   store.finishTurn({turn:'e1_real_turn_01',status:'answered',session:dummySession,
     text:'这是确定性回复',failure:null,tools:new Map()})
   assert.equal(store.binding('e1_real_conversation').selected.model,'deterministic-local')
   assert.equal(store.getTurn('e1_real_turn_01').status,'answered')
   const state=readFileSync(join(f.dir,'bindings-v1.json'),'utf8')
   assert.equal(state.includes('一个虚构问题'),false,'no raw prompt copies')
   assert.equal(existsSync(join(f.dir,'bindings-v1.lock')),true)
   store.close()
   assert.equal(existsSync(join(f.dir,'bindings-v1.lock')),false)
   store=openBindingLedger(f.root,f.dir,()=>1700000000500)
   assert.equal(store.binding('e1_real_conversation').expired,false)
   assert.equal(store.getTurn('e1_real_turn_01').text,'这是确定性回复')
 }finally{store?.close();f.close()}
})

test('0 or expired resume window denies old native Session reuse without pretending to erase logs',()=>{
 const f=fixture()
 let now=1700000000000,store
 try {
  store=openBindingLedger(f.root,f.dir,()=>now)
  store.putBinding('e1_expired_conversation',dummySession,owner)
  now += 31*86400000
  assert.equal(store.binding('e1_expired_conversation').expired,true)
  store.setResumeDays(3650)
  assert.equal(store.binding('e1_expired_conversation').expired,false)
  store.setResumeDays(0)
  assert.equal(store.binding('e1_expired_conversation').expired,true)
  assert.throws(()=>store.setResumeDays(-1),/invalid/)
  assert.throws(()=>store.setResumeDays(3651),/invalid/)
  assert.equal(store.resumeDays,0)
 }finally{store?.close();f.close()}
})

test('locked state cannot be opened by concurrent Host or outside workspace',()=>{
 const f=fixture()
 let store
 try{
   store=openBindingLedger(f.root,f.dir)
   assert.throws(()=>openBindingLedger(f.root,f.dir),/already_owned/)
   assert.throws(()=>openBindingLedger(f.root,tmpdir()),/must_be_in_project/)
   assert.throws(()=>openBindingLedger(f.root,'state'),/absolute/)
 }finally{store?.close();f.close()}
})

test('symlink escape and corrupted state fail closed',()=>{
 const f=fixture()
 let store
 try {
   symlinkSync(tmpdir(),join(f.root,'external'))
   assert.throws(()=>openBindingLedger(f.root,join(f.root,'external/state')),/symlink/)
   store=openBindingLedger(f.root,f.dir)
   store.close();store=null
   const state=join(f.dir,'bindings-v1.json')
   writeFileSync(state,'{"version":27}')
   assert.throws(()=>openBindingLedger(f.root,f.dir),/invalid/)
 }finally{store?.close();f.close()}
})

test('in-progress turn keeps explicit unknown outcome on next process',()=>{
 const f=fixture()
 let store
 try{
  store=openBindingLedger(f.root,f.dir)
  store.reserveTurn('e1_orphan_turn_01','e1_orphan_conversation','will not repeat','native-task-02')
  store.close()
  store=openBindingLedger(f.root,f.dir)
  assert.equal(store.getTurn('e1_orphan_turn_01').status,'interrupted')
  assert.equal(store.getTurn('e1_orphan_turn_01').task_id,'native-task-02')
  assert.throws(()=>store.reserveTurn('e1_orphan_turn_01','e1_orphan_conversation','repeat','native-task-03'),/already_reserved/)
 }finally{store?.close();f.close()}
})

test('abruptly exited state owner can be recovered but a live PID cannot be stolen',()=>{
 const f=fixture()
 let store
 try{
   store=openBindingLedger(f.root,f.dir)
   const lock=join(f.dir,'bindings-v1.lock')
   assert.throws(()=>openBindingLedger(f.root,f.dir),/already_owned/)
   store.close()
   store=null
   writeFileSync(lock,JSON.stringify({pid:999999999,identity:'prior_crashed_owner'}))
   store=openBindingLedger(f.root,f.dir)
   assert.equal(store.resumeDays,30)
   assert.equal(existsSync(lock),true)
 } finally {store?.close();f.close()}
})

test('B zero-day explicit end scrubs terminal reply and refuses native reuse after reopen',()=>{
 const f=fixture()
 let store
 try{
   store=openBindingLedger(f.root,f.dir,()=>1700000000000)
   store.putBinding('p1_end_user_001',dummySession,owner)
   store.reserveTurn('p1_end_turn_001','p1_end_user_001','fictional private input','task_one_123456')
   store.finishTurn({turn:'p1_end_turn_001',status:'answered',session:dummySession,
     text:'fictional private reply',failure:null,tools:new Map()})
   assert.equal(store.getTask('task_one_123456').text,'fictional private reply')
   store.endConversation('p1_end_user_001')
   assert.equal(store.binding('p1_end_user_001'),null)
   assert.equal(store.getTask('task_one_123456').status,'ended')
   assert.equal(store.getTask('task_one_123456').text,undefined)
   assert.equal(readFileSync(join(f.dir,'bindings-v1.json'),'utf8').includes('fictional private reply'),false)
   store.close()
   store=openBindingLedger(f.root,f.dir)
   assert.equal(store.binding('p1_end_user_001'),null)
   assert.equal(store.getTask('task_one_123456').status,'ended')
 }finally{store?.close();f.close()}
})

test('C2-S4d per-conversation search preference persists without overwriting model selection',()=>{
 const f=fixture()
 let store
 try {
   store=openBindingLedger(f.root,f.dir,()=>1700000000000)
   store.putBinding('native_search_conversation',dummySession,owner,false)
   assert.equal(store.binding('native_search_conversation').web_search_enabled,false)
   store.putBinding('native_search_conversation',dummySession,{provider:'offline-test',model:'new-native-model'},true)
   assert.equal(store.binding('native_search_conversation').web_search_enabled,true)
   store.putBinding('native_search_conversation',dummySession,owner)
   assert.equal(store.binding('native_search_conversation').web_search_enabled,true)
   store.close()
   store=openBindingLedger(f.root,f.dir,()=>1700000000010)
   assert.equal(store.binding('native_search_conversation').web_search_enabled,true)
   store.putBinding('native_search_conversation',dummySession,owner,false)
   assert.equal(store.binding('native_search_conversation').web_search_enabled,false)
 }finally{store?.close();f.close()}
})
