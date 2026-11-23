import test from 'node:test'
import {strict as assert} from 'node:assert'
import {completedReadonlySearch,rejectedObserveSchema,recoveredReadonlySearch} from '../lib/pinky-readonly-observe-recovery.js'
const p='mcp__pinky_dafeiyu__phone_'
const row=(name,other={})=>({name:p+name,outcome:'success',...other})
const own=(error=true,text='Error: validating "arguments": validating root: unexpected additional properties ["intent"]')=>({
  role:'tool',source:{kind:'tool',callId:'call1'},toolCallId:'call1',
  isError:error,content:[{type:'text',text}]
})
const make=(mutator=()=>{})=>{
  const arr=[
    row('connect'),row('launch'),row('tap'),
    row('type',{typedScreenApp:'Example'}),
    row('observe',{outcome:'failed',schemaRejected:true}),
    row('observe',{observedApp:'Example',settledScreen:true}),
    row('release'),
  ]
  const data={phoneMode:'pinky',phonePolicyApplied:true,
    prompt:'本次用户原话：帮我在手机上搜索手冲咖啡滤纸，只看搜索结果，不要购买下单或修改任何东西',
    turnEnd:'completed',textAfterTools:true,text:'搜索结果第一个商品是：HERO 滤纸',
    approvalOutstanding:false,approvalRejected:false,pendingApprovals:new Set(),
    tools:new Map(arr.map((x,i)=>[String(i),x]))}
  mutator(data,arr)
  data.tools=new Map(arr.map((x,i)=>[String(i),x]))
  return data
}
test('real native phone_observe argument error is trusted only with producer provenance',()=>{
  assert.equal(rejectedObserveSchema(p+'observe',own()),true)
  assert.equal(rejectedObserveSchema(p+'tap',own()),false)
  assert.equal(rejectedObserveSchema(p+'observe',own(false)),false)
  assert.equal(rejectedObserveSchema(p+'observe',own(true,'Error: unknown phone error')),false)
  assert.equal(rejectedObserveSchema(p+'observe',{...own(),source:{kind:'tool',callId:'other'}}),false)
  assert.equal(rejectedObserveSchema(p+'observe',{...own(),role:'assistant'}),false)
  assert.equal(rejectedObserveSchema(p+'observe',own(true,'Error: validating "arguments": validating root: unexpected additional properties ["intent"]')),true)
})
test('only a single schema-rejected observe followed by settled same-app reobserve',()=>{
  assert.equal(recoveredReadonlySearch(make()),true)
  const negatives=[
    t=>{t.phoneMode='readonly'},
    t=>{t.phonePolicyApplied=false},
    t=>{t.turnEnd='aborted'},
    t=>{t.textAfterTools=false},
    t=>{t.approvalOutstanding=true},
    t=>{t.approvalRejected=true},
    t=>{t.pendingApprovals.add('waiting')},
    t=>{t.text=''},
    t=>{t.prompt='打开手机淘宝，把商品加入购物车'},
    t=>{t.prompt='帮我在手机淘宝上搜索商品，然后下单'},
    (t,r)=>{r[4].schemaRejected=false},
    (t,r)=>{r[4].outcome='success'},
    (t,r)=>{r[5].outcome='failed'},
    (t,r)=>{r[5].settledScreen=false},
    (t,r)=>{r[5].observedApp='Other'},
    (t,r)=>{r[3].typedScreenApp=null},
    (t,r)=>{r[6].outcome='failed'},
    (t,r)=>{r.splice(5,0,row('tap'))},
    (t,r)=>{r.splice(6,0,row('task_run'))},
    (t,r)=>{r.splice(6,0,row('observe',{outcome:'success',observedApp:'Example'}))},
    (t,r)=>{r.splice(4,0,row('tap',{outcome:'failed'}))},
  ]
  for(const [i,mutate] of negatives.entries()){
    const t=make(mutate)
    assert.equal(recoveredReadonlySearch(t),false,'negative '+i)
  }
})

test('R683 complete all-success phone search is verified with a real final observed screen',()=>{
  const happy=make((t,r)=>{r.splice(4,1)})
  assert.equal(completedReadonlySearch(happy),true)
  const attacks=[
    t=>{t.prompt='帮我在手机上搜索滤纸然后下单，只看结果'},
    t=>{t.phoneMode='readonly'},
    t=>{t.approvalOutstanding=true},
    t=>{t.turnEnd='aborted'},
    t=>{t.textAfterTools=false},
    (t,r)=>{r[3].typedScreenApp=null},
    (t,r)=>{r[4].observedApp='Other App'},
    (t,r)=>{r[4].settledScreen=false},
    (t,r)=>{r[4].outcome='failed'},
    (t,r)=>{r.splice(4,0,row('tap'))},
    (t,r)=>{r.splice(4,0,row('observe',{settledScreen:true,observedApp:'Example'}))},
    (t,r)=>{r.splice(5,0,row('task_run'))},
  ]
  for(const [i,mutate] of attacks.entries()){
    const subject=make((t,r)=>{r.splice(4,1);mutate(t,r)})
    assert.equal(completedReadonlySearch(subject),false,'negative '+i)
  }
})
