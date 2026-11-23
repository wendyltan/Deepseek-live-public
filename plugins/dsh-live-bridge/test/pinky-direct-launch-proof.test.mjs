import test from 'node:test'
import {strict as assert} from 'node:assert'
import {nativePinkyLaunchTarget,settledPinkyLaunch,nativePinkyConfirmedLaunch,nativePinkyConfirmedUnsentDraft,settledPinkyScreenApp} from '../lib/pinky-direct-launch-proof.js'

const pre='mcp__pinky_dafeiyu__phone_'
const msg=(text, extra={})=>({
  role:'tool',source:{kind:'tool',callId:'c123'},toolCallId:'c123',
  isError:false,content:[{type:'text',text}],...extra
})
const screen=(name,status='settled')=>
  status+' · device: iPhone\nscreen 1080x2400 · app: '+name+
  ' (com.example.app) · portrait · keyboard hidden\n[1] button "Continue" @50,90'
const row=(name,extra={})=>({name:pre+name,outcome:'success',...extra})
test('Pinky production app argument must be a bounded exact name',()=>{
  assert.equal(nativePinkyLaunchTarget(pre+'launch',JSON.stringify({app:'淘宝',intent:'启动软件'})),'淘宝')
  for(const bad of ['https://taobao.com','../../foobar','','a'.repeat(200),123,null]){
    assert.equal(nativePinkyLaunchTarget(pre+'launch',JSON.stringify({app:bad})),null)
  }
  assert.equal(nativePinkyLaunchTarget(pre+'tap',JSON.stringify({app:'淘宝'})),null)
  assert.equal(nativePinkyLaunchTarget(pre+'launch','invalid json'),null)
})
test('producer-owned settled app screen positively proves one launch',()=>{
  const x=msg(screen('淘宝'))
  assert.equal(settledPinkyLaunch(pre+'launch',x,'淘宝'),'淘宝')
  assert.equal(settledPinkyLaunch(pre+'launch',x,'微信'),null)
  assert.equal(settledPinkyLaunch(pre+'launch',msg(screen('淘宝商家版')),'淘宝'),null)
  assert.equal(settledPinkyLaunch(pre+'launch',msg(screen('淘宝','uncertain')),'淘宝'),null)
  assert.equal(settledPinkyLaunch(pre+'launch',msg(screen('淘宝','approval_pending')),'淘宝'),null)
  assert.equal(settledPinkyLaunch(pre+'launch',msg('settled · success, no phone screen'),'淘宝'),null)
  assert.equal(settledPinkyLaunch(pre+'launch',msg(screen('淘宝'),{isError:true}),'淘宝'),null)
  assert.equal(settledPinkyLaunch(pre+'launch',msg(screen('淘宝'),{source:{kind:'assistant',callId:'c123'}}),'淘宝'),null)
  assert.equal(settledPinkyLaunch(pre+'launch',msg(screen('淘宝'),{toolCallId:'unmatched'}),'淘宝'),null)
  assert.equal(settledPinkyLaunch(pre+'launch',msg('settled\nfalse text app: 淘宝'),'淘宝'),null)
})
test('positive report requires same clean connect launch release and no other write',()=>{
 const a=[
  row('connect'),
  row('launch',{launchConfirmed:'淘宝'}),
  row('release')
 ]
 assert.equal(nativePinkyConfirmedLaunch(new Map(a.map((v,i)=>[i,v]))),'淘宝')
 assert.equal(nativePinkyConfirmedLaunch(new Map([
  [0,a[0]],[1,a[1]],[2,row('observe',{observedApp:'淘宝'})],[3,a[2]]
 ])),'淘宝')
 assert.equal(nativePinkyConfirmedLaunch(new Map([
  [0,a[0]],[1,a[1]],[2,row('observe',{observedApp:'微信'})],[3,a[2]]
 ])),null)
 assert.equal(nativePinkyConfirmedLaunch(new Map(a.slice(0,2).map((v,i)=>[i,v]))),null)
 assert.equal(nativePinkyConfirmedLaunch(new Map([['x',row('release')],['y',a[1]],['z',row('connect')]])),null)
})
test('no success on partial or multi-step tasks, failed tools, mismatched target',()=>{
 const a=[row('connect'),row('launch',{launchConfirmed:'淘宝'}),row('release')]
 const cases=[
  [a[0],a[1],row('tap'),a[2]],
  [a[0],row('launch',{launchConfirmed:'淘宝',outcome:'failed'}),a[2]],
  [a[0],row('launch',{launchConfirmed:null}),a[2]],
  [a[0],a[1],row('launch',{launchConfirmed:'淘宝'}),a[2]],
  [row('connect',{outcome:'failed'}),a[1],a[2]],
  [a[0],a[1],row('release',{outcome:'failed'})],
  [a[0],row('apps',{outcome:'failed'}),a[1],a[2]],
 ]
 for(const arr of cases)
  assert.equal(nativePinkyConfirmedLaunch(new Map(arr.map((v,i)=>[i,v]))),null)
})

test('R614 verified unsent draft requires final native screen and no send-capable step',()=>{
 const settled=settledPinkyScreenApp(pre+'type',msg(screen('微信')))
 assert.equal(settled,'微信')
 const yes=[row('connect'),row('tap'),row('type',{typedScreenApp:settled}),row('release')]
 const check=arr=>nativePinkyConfirmedUnsentDraft(new Map(arr.map((v,i)=>[i,v])))
 assert.equal(check(yes),true)
 assert.equal(check([row('connect'),row('tap'),row('type'),
    row('observe',{observedApp:'微信'}),row('release')]),true)
 // The six exact tool types observed in the R618 completed official
 // native turn; synthetic headers avoid storing any real user content.
 assert.equal(check([
    row('connect'),row('launch'),row('tap'),
    row('type',{typedScreenApp:'微信'}),
    row('observe',{observedApp:'微信'}),row('release')
 ]),true)
 assert.equal(check([row('connect'),row('type',{typedScreenApp:'微信'}),
    row('observe',{observedApp:'支付宝'}),row('release')]),false)
 for(const no of [
   [row('connect'),row('type'),row('release')], // missing screen
   [row('connect'),row('type',{typedScreenApp:'微信'}),row('tap'),row('release')],
   [row('connect'),row('type',{typedScreenApp:'微信'}),row('key'),row('release')],
   [row('connect'),row('type',{typedScreenApp:'微信'}),row('phone_send'),row('release')],
   [row('connect'),row('type',{typedScreenApp:'微信'}),row('release',{outcome:'failed'})],
   [row('connect'),row('type',{typedScreenApp:'微信'}),row('task_wait'),row('release')],
   [row('type',{typedScreenApp:'微信'}),row('release')],
   [row('connect'),row('type',{typedScreenApp:'微信'})],
 ])assert.equal(check(no),false)
 assert.equal(settledPinkyScreenApp(pre+'type',msg(screen('微信'),{isError:true})),null)
 assert.equal(settledPinkyScreenApp(pre+'type',msg(screen('微信'),{source:{kind:'assistant',callId:'c123'}})),null)
 assert.equal(settledPinkyScreenApp(pre+'type',msg(screen('微信','pending'))),null)
})
