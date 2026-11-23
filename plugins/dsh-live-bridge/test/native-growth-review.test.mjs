import assert from 'node:assert/strict'
import test from 'node:test'
import {requestFor,postLocal} from '../../../scripts/r235_native_growth_review.mjs'
import {createServer} from 'node:http'
const uuid='12345678-1234-4234-8234-123456789abc'
test('R235 native helper accepts only scoped explicit user actions',()=>{
 assert.deepEqual(requestFor('status'),{protocolVersion:1,action:'growth.version'})
 assert.deepEqual(requestFor('list',{status:'new'}),{
  protocolVersion:1,action:'growth.list',status:'new'})
 assert.deepEqual(requestFor('consent'),{protocolVersion:1,action:'consent',
  confirm:'MANUAL_MEMORY_CONSENT',allow:true})
 assert.equal(requestFor('propose',{text:'虚构审查内容'}).confirm,
  'USER_EXPLICIT_GROWTH_PROPOSAL')
 assert.equal(requestFor('accept',{id:uuid,expectedRevision:1}).confirm,'ACCEPT_GROWTH_FACT')
 assert.equal(requestFor('reject',{id:uuid,expectedRevision:1}).confirm,'REJECT_GROWTH_FACT')
 assert.equal(requestFor('rollback',{toVersion:0,expectedRevision:2}).confirm,
  'ROLLBACK_GROWTH_VERSION')
 assert.deepEqual(requestFor('suggestions',{allow:true,expectedRevision:3}),{
  protocolVersion:1,action:'growth.suggestion-consent',allow:true,
  expectedRevision:3,confirm:'GROWTH_SUGGESTIONS_CONSENT'})

 for(const invalid of [
  ['debug',{}],['status',{extra:true}],['propose',{text:''}],
  ['propose',{text:'x'.repeat(520)}],
  ['rollback',{toVersion:-1,expectedRevision:0}],
  ['accept',{id:'malicious',expectedRevision:1}],
  ['suggestions',{allow:'true',expectedRevision:1}],
  ['suggestions',{allow:true,expectedRevision:-1}],
  ['accept',{id:uuid,expectedRevision:0,confirmation:'yes'}],
 ]) assert.throws(()=>requestFor(invalid[0],invalid[1]))
})
test('R235 helper uses HTTP POST exact loopback, dual tokens, no redirects or credentials leaked to reply',async()=>{
 let seen
 const server=createServer((req,res)=>{
  seen={method:req.method,path:req.url,headers:req.headers}
  let body=''
  req.on('data',c=>body+=c)
  req.on('end',()=>{
   seen.body=JSON.parse(body)
   res.writeHead(200,{'Content-Type':'application/json'})
   res.end(JSON.stringify({ok:true,revision:2,version:1}))
  })
 })
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve))
 try{
  const result=await postLocal(server.address().port,'synthetic-bridge-token-1234567890123456',
   'synthetic-admin-token-12345678901234567',
   'accept',{id:uuid,expectedRevision:2})
  assert.equal(result.code,200)
  assert.equal(result.body.version,1)
  assert.equal(seen.method,'POST')
  assert.equal(seen.path,'/dsh-live-bridge/memory-manage')
  assert.match(seen.headers.authorization,/^Bearer synthetic-bridge-token/)
  assert.equal(seen.headers['x-dsh-live-memory-token'],
   'synthetic-admin-token-12345678901234567')
  assert.equal(seen.body.confirm,'ACCEPT_GROWTH_FACT')
  assert.equal(seen.body.protocolVersion,1)
  assert.ok(!JSON.stringify(result).includes('synthetic-admin-token'))
 }finally{await new Promise(resolve=>server.close(resolve))}
})
