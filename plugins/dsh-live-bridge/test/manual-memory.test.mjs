import assert from 'node:assert/strict'
import test from 'node:test'
import {existsSync,mkdtempSync,readFileSync,rmSync,symlinkSync,writeFileSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {openManualMemory} from '../lib/manual-memory.js'

function fixture(){
 const root=mkdtempSync(join(tmpdir(),'whale-e1b-manual-'))
 return {root,dir:join(root,'private-memory'),close(){rmSync(root,{recursive:true,force:true})}}
}
test('explicit consent, Markdown edit with revision, restart, export and delete',()=>{
 const f=fixture();let store
 try{
  store=openManualMemory(f.root,f.dir,()=>1000)
  assert.equal(store.list().consent.manual_write,false)
  assert.equal(store.list().consent.auto_extraction,false)
  assert.throws(()=>store.put({text:'fictional-user-fact'}),/consent_required/)
  store.setManualConsent(true)
  const one=store.put({text:'虚构事实：喜欢香草布丁'})
  assert.equal(one.revision,1)
  assert.equal(readFileSync(join(f.dir,one.id+'.md'),'utf8'),'虚构事实：喜欢香草布丁\n')
  assert.throws(()=>store.put({id:one.id,text:'modified',expectedRevision:0}),/revision_conflict/)
  const two=store.put({id:one.id,text:'虚构事实：喜欢草莓布丁',expectedRevision:1})
  assert.equal(two.revision,2)
  store.close()
  store=openManualMemory(f.root,f.dir)
  assert.equal(store.read(one.id).text,'虚构事实：喜欢草莓布丁\n')
  assert.equal(store.exportAll().facts.length,1)
  store.setManualConsent(false)
  assert.throws(()=>store.put({text:'should be denied'}),/consent_required/)
  assert.deepEqual(store.remove(one.id,2),{removed:true,id:one.id,
    derived_index:'not_connected',backups:'not_verified'})
  assert.equal(store.list().items.length,0)
  assert.equal(existsSync(join(f.dir,one.id+'.md')),false)
 }finally{store?.close();f.close()}
})
test('rejects concurrency, path escape and symlink; detects tampering',()=>{
 const f=fixture();let store
 try{
  assert.throws(()=>openManualMemory(f.root,tmpdir()),/outside_project/)
  symlinkSync(tmpdir(),join(f.root,'bad-link'))
  assert.throws(()=>openManualMemory(f.root,join(f.root,'bad-link','vault')),/symlink/)
  store=openManualMemory(f.root,f.dir)
  assert.throws(()=>openManualMemory(f.root,f.dir),/already_open/)
  store.setManualConsent(true)
  const one=store.put({text:'fictional safe text'})
  writeFileSync(join(f.dir,one.id+'.md'),'tampered')
  assert.throws(()=>store.read(one.id),/integrity_failed/)
  store.close();store=null
  assert.throws(()=>openManualMemory(f.root,f.dir),/integrity_failed/)
 }finally{store?.close();f.close()}
})
test('no auto-extraction consent or free-form source field; manual-only remains opt-in',()=>{
 const f=fixture();let store
 try{
  store=openManualMemory(f.root,f.dir)
  store.setManualConsent(true)
  assert.throws(()=>store.put({text:'sample',source:'auto_extraction'}),/invalid_fact/)
  assert.throws(()=>store.setManualConsent('yes'),/consent_invalid/)
  assert.equal(store.exportAll().consent.auto_extraction,false)
 }finally{store?.close();f.close()}
})
