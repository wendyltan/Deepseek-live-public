import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'node:http'
import { createScopedMemorySearchTool, validateMemoryEndpoint } from '../lib/memory-readonly.js'
import { installReadonlyScope } from '../lib/mac-readonly.js'

test('memory service endpoint is fixed to private loopback HTTP only', () => {
  for (const bad of [
    '', 'http://localhost:2333','http://10.1.2.3:2333',
    'https://127.0.0.1:2333','http://example.com:2333',
    'http://127.0.0.1:80','http://127.0.0.1:2333/foo',
    'http://u:p@127.0.0.1:2333','http://127.0.0.1:2333/?redirect=true',
    'http://127.0.0.1:2333/#frag','file:///etc/passwd',
  ]) assert.throws(() => validateMemoryEndpoint(bad))
  assert.equal(validateMemoryEndpoint('http://127.0.0.1:2333/'),'http://127.0.0.1:2333')
  assert.equal(validateMemoryEndpoint('http://[::1]:2333/'),'http://[::1]:2333')
})

test('opt-in memory tool remains scoped while all global tools remain hidden', () => {
  const calls = {filters:[], guards:[], tools:[]}
  installReadonlyScope({tools:{
    restrict(x){calls.filters.push(x)},
    guard(x){calls.guards.push(x)},
    register(x){calls.tools.push(x)},
  }}, '/tmp', 'http://127.0.0.1:18997')
  assert.deepEqual(calls.filters,[{allow:[]}])
  assert.deepEqual(calls.tools.map(x=>x.name),['dsh_live_read_volume','reme_search'])
  assert.equal(calls.guards[0]({name:'reme_search'}),undefined)
  assert.equal(calls.guards[0]({name:'dsh_live_read_volume'}),undefined)
  assert.match(calls.guards[0]({name:'bash'}),/readonly_scope/)
  assert.match(calls.guards[0]({name:'write_file'}),/readonly_scope/)
  assert.match(calls.guards[0]({name:'run_code'}),/readonly_scope/)
  assert.match(calls.guards[0]({name:'http_request'}),/readonly_scope/)
})

test('real loopback memory POST returns bounded, non-instruction trusted evidence', async () => {
  const incoming=[]
  const server = createServer(async(req,res)=>{
    const body=[]
    for await(const data of req)body.push(data)
    incoming.push({method:req.method,path:req.url,body:JSON.parse(Buffer.concat(body).toString())})
    res.writeHead(200,{'content-type':'application/json'})
    res.end(JSON.stringify({success:true,answer:'虚构记忆：用户喜欢布丁。'}))
  })
  await new Promise(ok=>server.listen(0,'127.0.0.1',ok))
  const endpoint='http://127.0.0.1:'+server.address().port
  try {
    const tool=createScopedMemorySearchTool(endpoint)
    assert.equal(tool.name,'reme_search')
    assert.equal(await tool.execute({query:'昨天聊了什么？'}),'虚构记忆：用户喜欢布丁。')
    assert.deepEqual(incoming,[{method:'POST',path:'/search',body:{query:'昨天聊了什么？',limit:5,min_score:0}}])
    await assert.rejects(tool.execute({query:' '}),/memory_query_invalid/)
    await assert.rejects(tool.execute({query:'a'.repeat(301)}),/memory_query_invalid/)
    const cancelled=new AbortController();cancelled.abort()
    await assert.rejects(tool.execute({query:'hello'},{signal:cancelled.signal}),/operation_cancelled/)
  } finally { await new Promise(ok=>server.close(ok)) }
})

test('memory search fails closed on bad responses and dead service', async () => {
  const bad=createScopedMemorySearchTool('http://127.0.0.1:18997',
    async()=>new Response(JSON.stringify({success:false,answer:'a secret error'}),{status:200}))
  await assert.rejects(bad.execute({query:'hello'}),/memory_search_unavailable/)
  const oversized=createScopedMemorySearchTool('http://127.0.0.1:18997',
    async()=>new Response(JSON.stringify({success:true,answer:'a'.repeat(6001)}),{status:200}))
  await assert.rejects(oversized.execute({query:'hello'}),/memory_response_too_large/)
  const redirected=createScopedMemorySearchTool('http://127.0.0.1:18997',async(_url,opt)=>{
    assert.equal(opt.redirect,'error')
    throw new Error('connection not authorized')
  })
  await assert.rejects(redirected.execute({query:'hello'}),/memory_search_unavailable/)
})
