/**
 * E1b laboratory-only retention custodian. NEVER point this at a live DSH_HOME
 * or a shared ReMe workspace. No production deletion path is exposed.
 *
 * Each test session has its own ReMe workspace, so its Markdown AND
 * BM25/file-catalog/graph indices can be erased together. A shared index
 * cannot be selectively forgotten by deleting one Markdown source file.
 */
import { createHash } from 'node:crypto'
import { existsSync, lstatSync, readFileSync, readdirSync, realpathSync, unlinkSync, rmdirSync } from 'node:fs'
import { basename, dirname, join, resolve, sep } from 'node:path'

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const MAX_FILES=2000
const MAX_CONTENT=32*1024*1024
function fail(message){throw new Error(message)}
function digest(value){return createHash('sha256').update(value).digest('hex')}
function safeNode(path,base) {
  const absolute=resolve(path)
  if(absolute!==base && !absolute.startsWith(base+sep)) fail('retention_path_escape')
  for(let p=absolute;p!==base && p.startsWith(base+sep);p=dirname(p))
    if(existsSync(p) && lstatSync(p).isSymbolicLink()) fail('retention_symlink')
  if(existsSync(base) && lstatSync(base).isSymbolicLink()) fail('retention_symlink')
  return absolute
}
function walkFiles(path,base,output) {
  safeNode(path,base)
  if(!existsSync(path)) return
  const stat=lstatSync(path)
  if(stat.isDirectory()){
    for(const name of readdirSync(path)){
      if(name==='.'||name==='..') fail('retention_invalid_name')
      walkFiles(join(path,name),base,output)
    }
  }else if(stat.isFile()){
    if(output.length>=MAX_FILES || stat.size>MAX_CONTENT) fail('retention_capacity')
    output.push({path,size:stat.size,sha256:digest(readFileSync(path))})
  }else fail('retention_nonregular')
}
function isolationBase(projectRoot,fixtureRoot){
  const project=realpathSync(projectRoot)
  const laboratory=join(project,'tmp','c2-s3-e1b-isolated')
  const actual=resolve(fixtureRoot)
  if(!actual.startsWith(laboratory+sep) || !existsSync(actual))
    fail('retention_fixture_only')
  for(let p=actual;p.startsWith(project+sep);p=dirname(p))
    if(lstatSync(p).isSymbolicLink()) fail('retention_symlink')
  if(realpathSync(actual)!==actual) fail('retention_symlink')
  const markerPath=join(actual,'isolation.json')
  safeNode(markerPath,actual)
  if(!existsSync(markerPath)) fail('retention_fixture_only')
  const marker=JSON.parse(readFileSync(markerPath,'utf8'))
  if(marker?.kind!=='deepseek-live-e1b-disposable-fixture'||
     marker?.acknowledged_test_data!==true||
     marker?.host_stopped!==true||
     !Array.isArray(marker.sessions)) fail('retention_fixture_only')
  const ids=new Set()
  for(const item of marker.sessions){
    if(!UUID.test(item?.id??'')||ids.has(item.id)||
       !Number.isSafeInteger(item?.expires_at)||item.expires_at<1)
      fail('retention_fixture_invalid')
    ids.add(item.id)
  }
  return {actual,marker}
}
function scopedFiles(fixture,id){
  const home=join(fixture,'dsh-home')
  const buckets=join(home,'sessions')
  const results=[]
  if(existsSync(buckets)){
    safeNode(buckets,fixture)
    for(const bucket of readdirSync(buckets)){
      const dir=safeNode(join(buckets,bucket),fixture)
      if(!lstatSync(dir).isDirectory()) fail('retention_invalid_layout')
      const session=safeNode(join(dir,id),fixture)
      if(existsSync(session)){
        for(const name of readdirSync(session))
          if(!['session.v4.jsonl.zstd','session.lock'].includes(name))
            fail('retention_unrecognized_session_file')
        walkFiles(session,fixture,results)
      }
    }
  }
  const projection=join(home,'storages','session_projcache','sessions',id+'.json')
  walkFiles(projection,fixture,results)
  // Never clean a shared ReMe index: a session must own the entire workspace.
  const reme=join(fixture,'reme-by-session',id)
  walkFiles(reme,fixture,results)
  return results.sort((a,b)=>a.path.localeCompare(b.path))
}
export function planFixtureRetention(projectRoot,fixtureRoot,{now=Date.now()}={}){
  const {actual,marker}=isolationBase(projectRoot,fixtureRoot)
  if(!Number.isSafeInteger(now)||now<1) fail('retention_invalid_clock')
  const entries=[]
  for(const item of marker.sessions){
    const expired=now>=item.expires_at
    const files=expired ? scopedFiles(actual,item.id) : []
    entries.push({session_id:item.id,expired,files})
  }
  const revision=digest(JSON.stringify({fixture:actual,marker,entries}))
  return {fixture:actual,revision,entries,mode:'dry_run',external_backups:'not_verified'}
}
/** Explicit two-step lab confirmation only; never a production/user-data API. */
export function executeFixtureRetention(projectRoot,fixtureRoot,{revision,confirm,now=Date.now()}={}){
  if(confirm!=='DELETE_DISPOSABLE_FIXTURE_ONLY') fail('retention_confirmation_required')
  const plan=planFixtureRetention(projectRoot,fixtureRoot,{now})
  if(revision!==plan.revision) fail('retention_plan_changed')
  const erased=[]
  for(const item of plan.entries.filter(x=>x.expired)){
    for(const file of item.files){
      safeNode(file.path,plan.fixture)
      const current=lstatSync(file.path)
      if(!current.isFile()||current.size!==file.size||
         digest(readFileSync(file.path))!==file.sha256) fail('retention_plan_changed')
    }
  }
  // Deletion can be partial after an OS failure: never falsely report total
  // completion. Caller must rerun plan and verify all known copies.
  for(const item of plan.entries.filter(x=>x.expired)){
    for(const file of item.files){
      unlinkSync(file.path)
      erased.push(file.path)
    }
    const roots=[
      join(plan.fixture,'dsh-home','sessions'),
      join(plan.fixture,'reme-by-session',item.session_id),
    ]
    for(const root of roots){
      if(!existsSync(root))continue
      const paths=[]
      function collectDirs(dir){
        if(!existsSync(dir))return
        safeNode(dir,plan.fixture)
        for(const name of readdirSync(dir)){
          const child=join(dir,name)
          if(lstatSync(child).isDirectory())collectDirs(child)
        }
        paths.push(dir)
      }
      if(root.endsWith('/sessions')){
        for(const bucket of readdirSync(root)){
          const session=join(root,bucket,item.session_id)
          if(existsSync(session))collectDirs(session)
        }
      }else collectDirs(root)
      for(const dir of paths) if(existsSync(dir) && readdirSync(dir).length===0) rmdirSync(dir)
    }
  }
  const check=planFixtureRetention(projectRoot,fixtureRoot,{now})
  if(check.entries.some(x=>x.expired&&x.files.length))fail('retention_incomplete')
  return {mode:'fixture_only',erased_files:erased.length,
    erased_sessions:plan.entries.filter(x=>x.expired).map(x=>x.session_id),
    external_backups:'not_verified'}
}
