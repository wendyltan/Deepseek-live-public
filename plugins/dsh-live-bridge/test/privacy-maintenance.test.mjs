import assert from 'node:assert/strict'
import test from 'node:test'
import {randomUUID} from 'node:crypto'
import {existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync} from 'node:fs'
import {join, dirname, resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {planFixtureRetention, executeFixtureRetention} from '../lib/privacy-maintenance.js'

const PROJECT=resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const ROOT=join(PROJECT,'tmp','c2-s3-e1b-isolated')
function fixture(){
  mkdirSync(ROOT,{recursive:true})
  const dir=mkdtempSync(join(ROOT,'test-'))
  const expired=randomUUID(),other=randomUUID()
  const bucket=join(dir,'dsh-home','sessions','--test-workspace--')
  const proj=join(dir,'dsh-home','storages','session_projcache','sessions')
  const old=join(bucket,expired),keep=join(bucket,other)
  for(const path of [old,keep,proj,
      join(dir,'reme-by-session',expired,'metadata','keyword_index'),
      join(dir,'reme-by-session',expired,'digest'),
      join(dir,'reme-by-session',other,'digest')])mkdirSync(path,{recursive:true})
  writeFileSync(join(old,'session.v4.jsonl.zstd'),'fiction-v4-session')
  writeFileSync(join(old,'session.lock'),'')
  writeFileSync(join(keep,'session.v4.jsonl.zstd'),'KEEP-V4')
  writeFileSync(join(proj,expired+'.json'),'fiction-projection')
  writeFileSync(join(proj,other+'.json'),'KEEP-PROJ')
  writeFileSync(join(dir,'reme-by-session',expired,'digest','fact.md'),'fiction-fact')
  writeFileSync(join(dir,'reme-by-session',expired,'metadata','keyword_index','bm25.pkl'),'fiction-index')
  writeFileSync(join(dir,'reme-by-session',other,'digest','other.md'),'KEEP-REME')
  writeFileSync(join(dir,'isolation.json'),JSON.stringify({
    kind:'deepseek-live-e1b-disposable-fixture',
    acknowledged_test_data:true,host_stopped:true,
    sessions:[{id:expired,expires_at:100},{id:other,expires_at:999999}],
  }))
  return {dir,expired,other,old,keep,proj,close(){rmSync(dir,{recursive:true,force:true})}}
}
test('preview is non-destructive; execute removes only expired DSH, projection and isolated ReMe index',()=>{
  const f=fixture()
  try{
    const p=planFixtureRetention(PROJECT,f.dir,{now:200})
    assert.equal(p.mode,'dry_run')
    assert.equal(p.entries.find(x=>x.session_id===f.expired).files.length,5)
    assert.equal(existsSync(join(f.old,'session.v4.jsonl.zstd')),true)
    assert.throws(()=>executeFixtureRetention(PROJECT,f.dir,{revision:p.revision,now:200}),/confirmation/)
    const result=executeFixtureRetention(PROJECT,f.dir,{
      revision:p.revision,now:200,confirm:'DELETE_DISPOSABLE_FIXTURE_ONLY'})
    assert.deepEqual(result.erased_sessions,[f.expired])
    assert.equal(result.erased_files,5)
    assert.equal(existsSync(f.old),false)
    assert.equal(existsSync(join(f.proj,f.expired+'.json')),false)
    assert.equal(existsSync(join(f.dir,'reme-by-session',f.expired)),false)
    assert.equal(readFileSync(join(f.keep,'session.v4.jsonl.zstd'),'utf8'),'KEEP-V4')
    assert.equal(readFileSync(join(f.dir,'reme-by-session',f.other,'digest','other.md'),'utf8'),'KEEP-REME')
    assert.equal(result.external_backups,'not_verified')
  }finally{f.close()}
})
test('changes after preview invalidate the execution plan',()=>{
  const f=fixture()
  try{
    const p=planFixtureRetention(PROJECT,f.dir,{now:200})
    writeFileSync(join(f.old,'session.v4.jsonl.zstd'),'modified AFTER plan')
    assert.throws(()=>executeFixtureRetention(PROJECT,f.dir,{
      revision:p.revision,confirm:'DELETE_DISPOSABLE_FIXTURE_ONLY',now:200}),/plan_changed/)
    assert.equal(existsSync(join(f.old,'session.v4.jsonl.zstd')),true)
  }finally{f.close()}
})
test('symlinks, unknown native files, missing marker, and non-fixture paths fail closed',()=>{
  const f=fixture()
  try{
    const data=join(f.old,'session.v4.jsonl.zstd')
    rmSync(data)
    symlinkSync(join(f.keep,'session.v4.jsonl.zstd'),data)
    assert.throws(()=>planFixtureRetention(PROJECT,f.dir,{now:200}),/symlink/)
    rmSync(data)
    writeFileSync(join(f.old,'unknown.secret'),'must-not-touch')
    assert.throws(()=>planFixtureRetention(PROJECT,f.dir,{now:200}),/unrecognized/)
    assert.throws(()=>planFixtureRetention(PROJECT,join(PROJECT,'tmp','c2-s3-e0-isolated'),{now:200}),/fixture_only/)
    rmSync(join(f.dir,'isolation.json'))
    assert.throws(()=>planFixtureRetention(PROJECT,f.dir,{now:200}),/fixture_only/)
  }finally{f.close()}
})
test('a non-expired session and its files remain untouched',()=>{
  const f=fixture()
  try{
    const p=planFixtureRetention(PROJECT,f.dir,{now:50})
    assert.equal(p.entries.every(x=>!x.expired && !x.files.length),true)
    const r=executeFixtureRetention(PROJECT,f.dir,{now:50,revision:p.revision,confirm:'DELETE_DISPOSABLE_FIXTURE_ONLY'})
    assert.equal(r.erased_files,0)
    assert.equal(existsSync(join(f.old,'session.v4.jsonl.zstd')),true)
  }finally{f.close()}
})
