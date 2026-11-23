import assert from 'node:assert/strict'
import test from 'node:test'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createReadVolumeTool, installReadonlyScope, READ_VOLUME_TOOL } from '../lib/mac-readonly.js'

test('read-only volume tool uses fixed project root and exposes no path or file content', async () => {
  const dir=mkdtempSync(join(tmpdir(),'dsh-live-volume-'))
  try {
    const tool=createReadVolumeTool(dir)
    assert.equal(tool.name, READ_VOLUME_TOOL)
    assert.deepEqual(tool.parameters.properties, {})
    assert.equal(tool.parameters.additionalProperties,false)
    const value=JSON.parse(await tool.execute({}, {signal:new AbortController().signal}))
    assert.equal(value.scope,'deepseek_live_project_volume')
    assert.equal(value.contents_read,false)
    assert.equal(value.readonly,true)
    assert.ok(value.free_gb>=0 && value.total_gb>0 && value.free_gb<=value.total_gb)
    assert.equal(JSON.stringify(value).includes(dir),false)
    assert.deepEqual(tool.output.render({},JSON.stringify(value))[0].type,'text')
  } finally {rmSync(dir,{recursive:true,force:true})}
})

test('read-only tool refuses pre-aborted calls', async()=>{
  const controller=new AbortController()
  controller.abort()
  await assert.rejects(createReadVolumeTool(tmpdir()).execute({}, {signal:controller.signal}),
    /operation_cancelled/)
})

test('Agent setup denies all inherited tools and guards even unexpected scoped execution',()=>{
  const called=[]
  const ctx={ tools: {
    restrict(value){called.push(['restrict',value])},
    guard(fn){called.push(['guard',fn])},
    register(tool){called.push(['register',tool])},
  }}
  installReadonlyScope(ctx,tmpdir())
  assert.deepEqual(called[0],['restrict',{allow:[]}])
  assert.equal(called[2][1].name,READ_VOLUME_TOOL)
  assert.equal(called[1][1]({name:READ_VOLUME_TOOL}),undefined)
  assert.match(called[1][1]({name:'bash'}),/readonly_scope/)
  assert.match(called[1][1]({name:'run_code'}),/readonly_scope/)
  assert.match(called[1][1]({name:'write_file'}),/readonly_scope/)
})

test('missing Agent-scoped guard capabilities fail closed',()=>{
  assert.throws(()=>installReadonlyScope({},tmpdir()),/policy_unavailable/)
  assert.throws(()=>installReadonlyScope({tools:{restrict(){},register(){}}},tmpdir()),/policy_unavailable/)
})
