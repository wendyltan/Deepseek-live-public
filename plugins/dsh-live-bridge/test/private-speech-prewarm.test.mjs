import test from 'node:test'
import assert from 'node:assert/strict'
import { PrivateSpeechPrewarm } from '../lib/private-speech-prewarm.js'

const owner={id:'dsh-session-owned-01'}
const base=()=>new PrivateSpeechPrewarm({agentId:owner.id,taskId:'task-01',sessionId:owner.id,nativeTurn:1})
const start={type:'start',attemptId:'attempt-a',revision:1,turn:1,step:0}
function chunk(index, type, text, revision=1){
  return {type:'chunk',attemptId:'attempt-a',revision,index,
          time:1000+index,chunk:{type,index,text}}
}
const end={type:'end',attemptId:'attempt-a',revision:1,index:0,
           outcome:{kind:'committed',eventType:'assistant/message',seq:10}}

test('native scoped attempt yields private proposals, only verified final settlement releases sentences',()=>{
  const p=base()
  assert.deepEqual(p.feed({id:'foreign-agent'},start),[])
  assert.deepEqual(p.feed(owner,start),[])
  assert.deepEqual(p.feed(owner,chunk(0,'reasoning-delta','SECRET PRIVATE REASONING。')),[])
  assert.deepEqual(p.feed(owner,chunk(1,'text-delta','本鱼在呢。')),[
    {kind:'prewarm_only',task_id:'task-01',session_id:owner.id,attempt_id:'attempt-a',step:0,
      from:0,to:5,text:'本鱼在呢。'}
  ])
  assert.equal(p.feed(owner,chunk(2,'text-delta','今天开心！')).length,1)
  assert.deepEqual(p.feed(owner,{...end,index:3}),[])
  const good=p.finalize({status:'answered',turnEnd:'completed',finalText:'本鱼在呢。今天开心！'})
  assert.deepEqual(good.map(x=>x.text),['本鱼在呢。','今天开心！'])
  assert.ok(good.every(x=>x.kind==='verified_sentence'))
  assert.equal(JSON.stringify(good).includes('SECRET'),false)
})
test('wrong chunk index and foreign attempts fail closed',()=>{
  const p=base();p.feed(owner,start)
  assert.deepEqual(p.feed(owner,chunk(2,'text-delta','错序。')),[])
  assert.equal(p.status,'invalid')
  assert.deepEqual(p.finalize({status:'answered',turnEnd:'completed',finalText:'错序。'}),[])
})
test('abandoned attempts and failed turn never release speech',()=>{
  for(const outcome of [
    {kind:'abandoned'},
    {kind:'committed',eventType:'assistant/attempt',seq:5},
  ]){
    const p=base();p.feed(owner,start);p.feed(owner,chunk(0,'text-delta','没完成。'))
    p.feed(owner,{...end,index:1,outcome})
    assert.deepEqual(p.finalize({status:'answered',turnEnd:'completed',finalText:'没完成。'}),[])
  }
  const failed=base();failed.feed(owner,start);failed.feed(owner,chunk(0,'text-delta','会做完。'))
  failed.feed(owner,{...end,index:1})
  assert.deepEqual(failed.finalize({status:'failed',turnEnd:'error',finalText:'会做完。'}),[])
})
test('late tool call or pending approval suppresses prewarm candidates',()=>{
  for(const eventType of ['tool/call','approval/asked']){
    const p=base();p.feed(owner,start)
    p.feed(owner,chunk(0,'text-delta','已经完成。'))
    p.nativeEvent(eventType)
    p.feed(owner,{...end,index:1})
    assert.deepEqual(p.finalize({status:'completed',turnEnd:'completed',finalText:'已经完成。',
      executionVerified:true}),[])
  }
})
test('tool-call-delta and altered final text disallow speculated result',()=>{
  const p=base();p.feed(owner,start)
  p.feed(owner,chunk(0,'text-delta','马上完成。'))
  p.feed(owner,{...chunk(1,'tool-call-delta',''),chunk:{type:'tool-call-delta',index:0,id:'call-1',argumentsDelta:'sensitive arguments'}})
  p.feed(owner,{...end,index:2})
  assert.deepEqual(p.finalize({status:'completed',turnEnd:'completed',finalText:'马上完成。',executionVerified:true}),[])
  const q=base();q.feed(owner,start)
  q.feed(owner,chunk(0,'text-delta','结果成功。'))
  q.feed(owner,{...end,index:1})
  assert.deepEqual(q.finalize({status:'answered',turnEnd:'completed',finalText:'结果失败。'}),[])
})
test('cancel and oversized text invalidate pending prewarm safely',()=>{
  const p=base();p.feed(owner,start)
  p.feed(owner,chunk(0,'text-delta','不再念。'))
  p.nativeEvent('cancel_requested')
  p.feed(owner,{...end,index:1})
  assert.deepEqual(p.finalize({status:'answered',turnEnd:'completed',finalText:'不再念。'}),[])
  const q=new PrivateSpeechPrewarm({agentId:owner.id,taskId:'t',sessionId:'s',nativeTurn:1,maxChars:100})
  q.feed(owner,start);q.feed(owner,chunk(0,'text-delta','文'.repeat(101)+'。'))
  assert.equal(q.status,'overflow')
})
test('never accept mismatched revisions and task/agent ownership',()=>{
  const p=base();p.feed(owner,start)
  p.feed(owner,chunk(0,'text-delta','错版本。',2))
  assert.equal(p.status,'invalid')
  const q=base();q.feed(owner,start)
  q.feed({id:'other'},chunk(0,'text-delta','应该忽略。'))
  assert.equal(q.text,'')
  const r=base();r.feed(owner,{...start,turn:2})
  assert.equal(r.status,'invalid');assert.equal(r.closed,true)
})
