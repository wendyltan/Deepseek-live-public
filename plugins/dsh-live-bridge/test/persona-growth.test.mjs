import assert from 'node:assert/strict'
import test from 'node:test'
import {mkdtempSync,rmSync,mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {openGrowth} from '../lib/persona-growth.js'
function fixture(fn){
 const root=mkdtempSync(join(tmpdir(),'dsh-growth-fixture-'))
 const dir=join(root,'private','growth')
 try{return fn(root,dir)}finally{rmSync(root,{recursive:true,force:true})}
}
test('no automatic extraction, bounded explicit proposal, and dedup',()=>fixture((root,dir)=>{
 const g=openGrowth(root,dir)
 try {
  assert.equal(g.listCandidates().length,0)
  assert.deepEqual(g.activeFacts(),[])
  assert.equal(g.version().version,0)
  assert.throws(()=>g.propose({text:'自动学习',source:'model'}),/growth_invalid_proposal/)
  assert.throws(()=>g.propose({text:'X'.repeat(600)}),/growth_invalid_fact/)
  const a=g.propose({text:'虚构测试事实：偏好短句',turn_id:'fixture_turn_001'})
  assert.ok(a.id)
  assert.equal(g.propose({text:'虚构测试事实：偏好短句'}).duplicate,true)
  assert.equal(g.listCandidates('new').length,1)
  assert.deepEqual(g.activeFacts(),[])
  assert.equal(g.version().active_count,0)
  assert.equal(g.version().candidate_count,1)
 }finally{g.close()}
}))
test('approval gate + rejection + versioned accept/rollback with monotonic revisions',()=>fixture((root,dir)=>{
 const g=openGrowth(root,dir)
 try {
  const original=g.propose({text:'虚构测试事实：爱白米饭'}).id
  assert.throws(()=>g.decide({id:original,decision:'accept',expectedRevision:1}),
    /growth_user_confirmation_required/)
  assert.throws(()=>g.decide({id:original,decision:'accept',expectedRevision:0,confirmed:true}),
    /growth_revision_conflict/)
  let value=g.decide({id:original,decision:'accept',expectedRevision:1,confirmed:true})
  assert.equal(value.version,1)
  assert.deepEqual(g.activeFacts(),['虚构测试事实：爱白米饭'])
  const second=g.propose({text:'虚构测试事实：喜欢清爽配色'}).id
  value=g.decide({id:second,decision:'accept',expectedRevision:3,confirmed:true})
  assert.equal(value.version,2)
  assert.equal(g.activeFacts().length,2)
  assert.throws(()=>g.rollback({toVersion:0,expectedRevision:4}),/growth_user_confirmation_required/)
  value=g.rollback({toVersion:1,expectedRevision:4,confirmed:true})
  assert.equal(value.version,3)
  assert.deepEqual(g.activeFacts(),['虚构测试事实：爱白米饭'])
  assert.equal(g.activeFacts(0).length,0)
  assert.equal(g.listCandidates('accepted').length,2)
  const reject=g.propose({text:'虚构测试事实：不要长期存储'}).id
  value=g.decide({id:reject,decision:'reject',expectedRevision:6,confirmed:true})
  assert.equal(value.version,3,'rejection is not an accepted persona version')
  assert.equal(g.listCandidates('rejected').length,1)
 }finally{g.close()}
}))
test('private restart restores versions and active facts; fails closed on tampered index',()=>fixture((root,dir)=>{
 let g=openGrowth(root,dir)
 const c=g.propose({text:'仅作为虚构测试事实。'})
 g.decide({id:c.id,decision:'accept',expectedRevision:1,confirmed:true})
 assert.throws(()=>openGrowth(root,dir),/growth_already_open/)
 g.close()
 g=openGrowth(root,dir)
 assert.equal(g.version().version,1)
 assert.deepEqual(g.activeFacts(),['仅作为虚构测试事实。'])
 g.close()
 const file=join(dir,'growth-v1.json')
 writeFileSync(file,'{"format":0}',{mode:0o600})
 assert.throws(()=>openGrowth(root,dir),/growth_invalid_state/)
}))

test('corrupted active fact or forged version fails before injecting saved text',()=>fixture((root,dir)=>{
 let g=openGrowth(root,dir)
 const proposal=g.propose({text:'虚构测试事实：认真记录'})
 g.decide({id:proposal.id,decision:'accept',expectedRevision:1,confirmed:true})
 g.close()
 const file=join(dir,'growth-v1.json')
 const x=JSON.parse(readFileSync(file,'utf8'))
 x.facts[proposal.id].text='被篡改的内容'
 writeFileSync(file,JSON.stringify(x),{mode:0o600})
 assert.throws(()=>openGrowth(root,dir),/growth_integrity_failed/)
}))

test('R236 suggestions remain OFF by default; require opted-in revision and cannot become persona without user review',()=>fixture((root,dir)=>{
 let g=openGrowth(root,dir)
 try{
  assert.equal(g.version().suggestions_enabled,false)
  assert.throws(()=>g.propose({text:'长期喜好：模板化建议',source:'assistant_suggested',
      turn_id:'r236_turn_abc001'}),/growth_invalid_proposal/)
  assert.throws(()=>g.setSuggestionConsent({allow:true,expectedRevision:0}),
      /growth_user_confirmation_required/)
  assert.throws(()=>g.setSuggestionConsent({allow:true,expectedRevision:1,confirmed:true}),
      /growth_revision_conflict/)
  assert.equal(g.setSuggestionConsent({allow:true,expectedRevision:0,confirmed:true}).revision,1)
  const x=g.propose({text:'日常聊天使用自然亲切的表达，减少模板化客服语气。',
    source:'assistant_suggested',turn_id:'r236_turn_abc001'})
  assert.equal(g.version().active_count,0)
  assert.deepEqual(g.activeFacts(),[])
  assert.equal(g.listCandidates()[0].source,'assistant_suggested')
  assert.equal(g.propose({text:'日常聊天使用自然亲切的表达，减少模板化客服语气。',
    source:'assistant_suggested',turn_id:'r236_turn_abc001'}).duplicate,true)
  assert.equal(g.setSuggestionConsent({allow:false,expectedRevision:2,confirmed:true}).revision,3)
  assert.throws(()=>g.propose({text:'后续建议',source:'assistant_suggested',
    turn_id:'r236_turn_abc002'}),/growth_invalid_proposal/)
  g.decide({id:x.id,decision:'accept',expectedRevision:3,confirmed:true})
  assert.equal(g.activeFacts().length,1)
  assert.equal(g.version().suggestions_enabled,false)
  g.close()
  g=openGrowth(root,dir)
  assert.equal(g.version().suggestions_enabled,false,'opt-out persists')
  assert.equal(g.activeFacts().length,1)
  assert.equal(g.rollback({toVersion:0,expectedRevision:4,confirmed:true}).version,2)
  assert.deepEqual(g.activeFacts(),[])
 }finally{g.close()}
}))
