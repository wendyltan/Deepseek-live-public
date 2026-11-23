import assert from 'node:assert/strict'
import test from 'node:test'
import {mkdtempSync,mkdirSync,readFileSync,writeFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {openPersona} from '../lib/persona-runtime.js'

function fixture(){
 const dir=mkdtempSync(join(tmpdir(),'dsh-bridge-persona-test-'))
 mkdirSync(join(dir,'app'))
 const snap=join(dir,'private-persona')
 const previous=process.env.DSH_LIVE_PERSONA_SNAPSHOT_DIR
 process.env.DSH_LIVE_PERSONA_SNAPSHOT_DIR=snap
 return {dir,snap,close(){
   if(previous===undefined)delete process.env.DSH_LIVE_PERSONA_SNAPSHOT_DIR
   else process.env.DSH_LIVE_PERSONA_SNAPSHOT_DIR=previous
   rmSync(dir,{recursive:true,force:true})
 }}
}
test('P0 invalid core or missing file does not abort, and source is observable',()=>{
 const x=fixture()
 try {
  const data=openPersona(x.dir)
  assert.equal(data.metadata().source,'fallback')
  assert.match(data.core(),/大肥鱼/)
  writeFileSync(join(x.dir,'app','companion_persona.txt'),'我是鱼。\n不冒充工具。\n轻快但认真。')
  const fresh=data.metadata()
  assert.equal(fresh.source,'file')
  assert.ok(fresh.sha256.length===64)
  assert.ok(fresh.bytes<8192)
  assert.deepEqual(Object.keys(fresh.layers),['core','style','dynamic','memory'])
  assert.equal(data.core(),'我是鱼。\n不冒充工具。')
  assert.equal(data.style(),'轻快但认真。')
  assert.ok(data.metadata(true).bytes<400)
 }finally{x.close()}
})
test('P0 snapshot survives original file loss and can hot-update next turn',()=>{
 const x=fixture()
 try {
  const original=join(x.dir,'app','companion_persona.txt')
  writeFileSync(original,'身份证明。\n我不虚构执行。\n自然一些。')
  const data=openPersona(x.dir)
  const one=data.metadata()
  assert.equal(one.source,'file')
  assert.ok(readFileSync(join(x.snap,'snapshot-v1.json'),'utf8').includes(one.sha256))
  writeFileSync(original,'\n')
  assert.equal(data.metadata().source,'snapshot')
  assert.equal(data.core(),'身份证明。\n我不虚构执行。')
  writeFileSync(original,'身份仍然明确。\n说清事实。\n新的表达方式。')
  const two=data.metadata()
  assert.equal(two.source,'file')
  assert.notEqual(one.sha256,two.sha256)
  assert.equal(data.style(),'新的表达方式。')
 }finally{x.close()}
})
test('P0 no snapshot and no original gets a bounded built-in default',()=>{
 const x=fixture()
 try{
  const data=openPersona(x.dir)
  assert.equal(data.metadata().source,'fallback')
  assert.ok(data.metadata().bytes<300)
  assert.ok(data.health().warning_count>0)
 }finally{x.close()}
})
