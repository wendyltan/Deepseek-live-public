import assert from 'node:assert/strict'
import test from 'node:test'
import { EventEmitter } from 'node:events'
import { mkdtempSync, rmSync, readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply, Config } from '../lib/index.js'
import { boundedComputerQuestion } from '../lib/computer-questions.js'

test('profile configuration exposes only explicit native mode and private token file path', () => {
  const defaults=Config.parse({})
  assert.equal(defaults.toolMode,'legacy')
  assert.equal(defaults.bridgeTokenFile,'')
  const actual=Config.parse({
    manualMemory:true,personaGrowth:true,
    memoryAdminTokenFile:'/some/private/admin',manualMemoryDir:'/some/private/memory',
    personaGrowthDir:'/some/private/growth',
    workspaceRoot:'/some/project',bridgeTokenFile:'/some/private/token',
    toolMode:'native',webPresetId:'deepseek-live-web',visibleModels:'deepseek-flash',
    companionFacts:true,companionPersona:true,
  })
  assert.equal(actual.toolMode,'native')
  assert.equal(actual.manualMemory,true)
  assert.equal(actual.personaGrowth,true)
  assert.equal(Config.parse({}).manualMemory,false)
  assert.equal(Config.parse({}).personaGrowth,false)
  assert.equal(Config.parse({}).sessionRecovery,false)
  assert.equal(Config.parse({sessionRecovery:true,sessionStateDir:'/private/only'}).sessionRecovery,true)
  assert.equal(actual.webPresetId,'deepseek-live-web')
  assert.throws(()=>Config.parse({webPresetId:'standard'}))
  assert.equal(actual.companionFacts,true)
  assert.throws(()=>Config.parse({toolMode:'danger-full-access'}))
})

const token = 'test-live-bridge-' + '1'.repeat(50)
const adminToken='test-e1b-memory-admin-' + '2'.repeat(48)

function fixture({ key = token, root = true, failCreate = false, manualMemory=false, profileMemory=false,
                   personaGrowth=false,
                   companionFacts=false, companionPersona=false, companionApproval=false,
                   priorApprovalForwarder=false,nativeToolCatalog=null,scopedExtraTools=[],
                   webPresetFixture=false,webPresetFailure=false,webPresetConfigured=false,
                   defaultModel = { provider: 'offline-test', model: 'deterministic-local' },
                   nativeModels = [
                     {provider:'offline-test',id:'deterministic-local',name:'Fixture Flash'},
                     {provider:'offline-test',id:'deterministic-pro',name:'Fixture Pro'}
                   ],modelCatalogFailure=false } = {}) {
  const savedToken = process.env.DSH_LIVE_BRIDGE_TOKEN
  const savedRoot = process.env.DSH_LIVE_WORKSPACE_ROOT
  const savedMemoryFlag=process.env.DSH_LIVE_ENABLE_MANUAL_MEMORY
  const savedMemoryDir=process.env.DSH_LIVE_MANUAL_MEMORY_DIR
  const savedAdmin=process.env.DSH_LIVE_MEMORY_ADMIN_TOKEN
  const savedGrowthFlag=process.env.DSH_LIVE_ENABLE_PERSONA_GROWTH
  const savedGrowthDir=process.env.DSH_LIVE_PERSONA_GROWTH_DIR
  const savedPersonaSnapshot=process.env.DSH_LIVE_PERSONA_SNAPSHOT_DIR
  const savedCompanionFacts=process.env.DSH_LIVE_ENABLE_COMPANION_FACTS
  const savedCompanionApproval=process.env.DSH_LIVE_ENABLE_COMPANION_APPROVAL
  const savedApprovalTool=process.env.DSH_LIVE_APPROVAL_TOOL
  if(companionApproval) {
    process.env.DSH_LIVE_ENABLE_COMPANION_APPROVAL='1'
    process.env.DSH_LIVE_APPROVAL_TOOL='dsh_live_approval_probe'
  } else {
    delete process.env.DSH_LIVE_ENABLE_COMPANION_APPROVAL
    delete process.env.DSH_LIVE_APPROVAL_TOOL
  }
  if(companionFacts)process.env.DSH_LIVE_ENABLE_COMPANION_FACTS='1'
  else delete process.env.DSH_LIVE_ENABLE_COMPANION_FACTS
  const dir = mkdtempSync(join(tmpdir(), 'dsh-live-bridge-test-'))
  if(personaGrowth){
    process.env.DSH_LIVE_ENABLE_PERSONA_GROWTH='1'
    process.env.DSH_LIVE_PERSONA_GROWTH_DIR=join(dir,'private-growth')
  }else{
    delete process.env.DSH_LIVE_ENABLE_PERSONA_GROWTH
    delete process.env.DSH_LIVE_PERSONA_GROWTH_DIR
  }
  process.env.DSH_LIVE_PERSONA_SNAPSHOT_DIR=join(dir,'private-persona')
  if (companionPersona) {
    mkdirSync(join(dir,'app'))
    writeFileSync(join(dir,'app','companion_persona.txt'),
      '你叫 DeepSeek。你是一条喜欢吃饭的小肥鱼，回答正事要准确。')
  }

  if (key) process.env.DSH_LIVE_BRIDGE_TOKEN = key
  else delete process.env.DSH_LIVE_BRIDGE_TOKEN
  if (root) process.env.DSH_LIVE_WORKSPACE_ROOT = dir
  else delete process.env.DSH_LIVE_WORKSPACE_ROOT
  const nativeMemoryConfig=profileMemory ? (()=>{
    const file=join(dir,'native-private-admin.token')
    writeFileSync(file,adminToken,{mode:0o600})
    return {manualMemory:true,personaGrowth:true,
      memoryAdminTokenFile:file,manualMemoryDir:join(dir,'native-private-memory'),
      personaGrowthDir:join(dir,'native-private-growth')}
  })() : {}
  if(manualMemory) {
    process.env.DSH_LIVE_ENABLE_MANUAL_MEMORY='1'
    process.env.DSH_LIVE_MANUAL_MEMORY_DIR=join(dir,'private-memory')
    process.env.DSH_LIVE_MEMORY_ADMIN_TOKEN=adminToken
  } else {
    delete process.env.DSH_LIVE_ENABLE_MANUAL_MEMORY
    delete process.env.DSH_LIVE_MANUAL_MEMORY_DIR
    delete process.env.DSH_LIVE_MEMORY_ADMIN_TOKEN
  }

  const routes = new Map(), handlers = new Map(), disposed = []
  // The official browser forwarder may already own the waterfall before
  // the companion Agent is composed; prepend must win for the safe fixture.
  if(priorApprovalForwarder) handlers.set('approval/request',new Set([
    ()=>'unavailable',
  ]))
  let created = 0
  const agents = []
  const presetMounts = []
  const presetTools = new WeakMap()
  const personaSections = []
  const personaContexts = []
  const ctx = {
    get(name) {
      if(name !== 'agentPresets' || !webPresetFixture)return undefined
      return {async mount(agentCtx, id) {
        presetMounts.push({id,ctx:agentCtx})
        if(webPresetFailure || id!=='deepseek-live-web') throw new Error('preset_mount_denied')
        presetTools.set(agentCtx,new Set(['web_search','web_fetch']))
        return {id}
      }}
    },
    llm: { async listModels(provider) {
      if(modelCatalogFailure)throw new Error('offline catalog read failed')
      return nativeModels
    }, async resolveCallConfig(route) {
      if (route.model === 'invalid-model') throw new Error('model unavailable')
      return { ...route }
    } },
    agentDefaultModel: { currentSelection() { return defaultModel } },
    agents: { async create(options) {
      created += 1
      if (failCreate) throw new Error('private failure diagnostic')
      const agent = {
        id: options.sessionId,
        status: 'idle',
        session: {
          id: options.sessionId, events: [],
          append(type, data) { this.events.push({type, data}) },
          requestHeader() { return this.header },
        },
        followed: [], cancels: [],
        followup(message) { this.followed.push(message) },
        cancel(cause) { this.cancels.push(cause) },
      }
      const scopedMasks=[],scopedGuards=[]
      if (options.setup) {
        const agentCtx = {
          on(name, handler, options={}) {
            const listeners=handlers.get(name)??new Set()
            if(options?.prepend) handlers.set(name,new Set([handler,...listeners]))
            else {listeners.add(handler);handlers.set(name,listeners)}
            return ()=>handlers.get(name)?.delete(handler)
          },
          ...(companionPersona ? {systemPrompt:{
            getSectionOrder(name){
              assert.equal(name,'DEPLOYMENT_PERSONA_PREFIX')
              return 100
            },
            section(spec){personaSections.push(spec);return ()=>{}},
            getContextOrder(name){assert.equal(name,'WEB_SURFACE');return 210},
            context(spec){personaContexts.push(spec);return ()=>{}},
          }} : {}),
          tools: {
            schemas(scope){
              // Preset tools are visible only in the owning Agent's scope.
              if(scope!==agent)return []
              const filtered=[...(nativeToolCatalog??[]),...(presetTools.get(agentCtx)??[])]
                .filter(name=>scopedMasks.every(mask=>!mask.active||
                  (mask.filter.allow===undefined||mask.filter.allow.includes(name))&&
                  (mask.filter.deny===undefined||!mask.filter.deny.includes(name))))
              return [...new Set([...filtered,...scopedExtraTools])].map(name=>({name}))
            },
            restrict(filter) {
              const mask={filter,active:true}
              scopedMasks.push(mask)
              return ()=>{mask.active=false}
            }, guard(fn) {
              scopedGuards.push(fn)
              return ()=>{const i=scopedGuards.indexOf(fn);if(i>=0)scopedGuards.splice(i,1)}
            }, register() {},
          },
        }
        await options.setup(agentCtx, agent)
      }
      agents.push({ options, agent, scopedMasks,scopedGuards })
      return { agent }
    } },
    webServer: { register({ path, kind, handler }) {
      assert.equal(kind, 'exact')
      routes.set(path, handler)
      return () => routes.delete(path)
    } },
    effect(factory) { disposed.push(factory()) },
    on(kind, handler) {
      const set = handlers.get(kind) ?? new Set()
      set.add(handler); handlers.set(kind, set)
      return () => set.delete(handler)
    },
  }
  apply(ctx, {
    ...(webPresetConfigured?{toolMode:'native',webPresetId:'deepseek-live-web'}:{}),
    ...(companionPersona?{companionPersona:true}:{}),
    ...nativeMemoryConfig,
  })
  const runHooks = async (name, data, data2) => {
    for (const hook of handlers.get(name) ?? []) await hook(data, data2)
  }
  const askApproval = (request) => {
    const handler=[...(handlers.get('approval/request')??[])][0]
    return handler?handler(request,()=>Promise.resolve('unavailable')):
      Promise.resolve('unavailable')
  }
  async function call(path, { method = 'GET', body, bearer = token, admin='', ip = '127.0.0.1' } = {}) {
    const handler = routes.get('/dsh-live-bridge' + path)
    if (!handler) throw new Error('not registered ' + path)
    return await new Promise((resolve, reject) => {
      const req = new EventEmitter()
      req.method = method
      req.headers = bearer ? { authorization: 'Bearer ' + bearer } : {}
      if(admin)req.headers['x-dsh-live-memory-token']=admin
      req.socket = { remoteAddress: ip }
      const resp = {
        code: 0, headers: {}, content: '',
        writeHead(code, headers) { this.code = code; this.headers = headers },
        end(content = '') { this.content = content; resolve({ code: this.code, headers: this.headers, body: JSON.parse(content) }) },
      }
      Promise.resolve(handler(req, resp)).catch(reject)
      queueMicrotask(() => {
        if (body !== undefined) req.emit('data', Buffer.from(typeof body === 'string' ? body : JSON.stringify(body)))
        req.emit('end')
      })
    })
  }
  const askComputer = (request) => {
    const handler=[...(handlers.get('user-questions/request')??[])][0]
    return handler?handler(request,()=>Promise.resolve({answers:[]})):
      Promise.resolve({answers:[]})
  }
  const close = () => {
    for (const d of disposed) d()
    if (savedToken === undefined) delete process.env.DSH_LIVE_BRIDGE_TOKEN
    else process.env.DSH_LIVE_BRIDGE_TOKEN = savedToken
    if (savedRoot === undefined) delete process.env.DSH_LIVE_WORKSPACE_ROOT
    else process.env.DSH_LIVE_WORKSPACE_ROOT = savedRoot
    for(const [name,value] of [
      ['DSH_LIVE_ENABLE_MANUAL_MEMORY',savedMemoryFlag],
      ['DSH_LIVE_MANUAL_MEMORY_DIR',savedMemoryDir],
      ['DSH_LIVE_MEMORY_ADMIN_TOKEN',savedAdmin],
      ['DSH_LIVE_ENABLE_PERSONA_GROWTH',savedGrowthFlag],
      ['DSH_LIVE_PERSONA_GROWTH_DIR',savedGrowthDir],
      ['DSH_LIVE_PERSONA_SNAPSHOT_DIR',savedPersonaSnapshot],
      ['DSH_LIVE_ENABLE_COMPANION_FACTS',savedCompanionFacts],
      ['DSH_LIVE_ENABLE_COMPANION_APPROVAL',savedCompanionApproval],
      ['DSH_LIVE_APPROVAL_TOOL',savedApprovalTool],
    ]) {
      if(value===undefined)delete process.env[name]
      else process.env[name]=value
    }
    rmSync(dir, { recursive: true, force: true })
  }
  return { dir, agents, presetMounts, personaSections, personaContexts, call, runHooks, askApproval, askComputer, close,
    get created() { return created } }
}

const input = (turn = 'turn_00000001', prompt = '查看磁盘剩余空间') =>
  ({ protocolVersion: 1, turn_id: turn, prompt })
const query = (task) => ({ protocolVersion: 1, task_id: task.task_id })

test('companion persona is installed only in the owning native Agent system-prompt scope',async()=>{
  const f=fixture({companionPersona:true})
  try{
    assert.equal(f.personaSections.length,0,'no eager session or global prompt')
    const bind=await f.call('/bind',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_persona_owned_session1'
    }})
    assert.equal(bind.code,200)
    assert.equal(f.personaSections.length,2)
    assert.equal(f.personaSections[0].name,'dsh-live:whale-core')
    assert.equal(f.personaSections[1].name,'dsh-live:whale-style')
    assert.equal(f.personaSections[0].order,101)
    assert.equal(f.personaSections[1].order,102)
    assert.match(f.personaSections[0].text(),/喜欢吃饭的小肥鱼/)
    assert.equal(f.agents[0].agent.followed.length,0,
      'installing system prompt must not start a paid turn')
    await f.call('/bind',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_persona_owned_session1'
    }})
    assert.equal(f.personaSections.length,2,'no duplicate sections on rebind')
  }finally{f.close()}
  const disabled=fixture()
  try{
    const bound=await disabled.call('/bind',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_other_session_0002'
    }})
    assert.equal(bound.code,200)
    assert.equal(disabled.personaSections.length,0)
  }finally{disabled.close()}
})

test('P0-1 speechOnly gets bounded whale identity without widening tool/model scope',async()=>{
 const f=fixture({companionPersona:true,nativeToolCatalog:['shell','web_search']})
 try {
  const id='speech_p0_whale_0011223344556677889900'
  const res=await f.call('/speech-bind',{method:'POST',body:{protocolVersion:1,conversation_id:id}})
  assert.equal(res.code,200)
  assert.equal(f.personaSections.length,1)
  assert.equal(f.personaSections[0].name,'dsh-live:whale-voice')
  assert.ok(Buffer.byteLength(f.personaSections[0].text())<=400)
  assert.match(f.personaSections[0].text(),/大肥鱼/)
  assert.equal(f.agents[0].options.agentOptions.maxTokens,320)
  assert.deepEqual(f.agents[0].scopedMasks[0].filter,{allow:[]})
  assert.equal(f.created,1,'binding does not make a paid model request')
 } finally{f.close()}
})

test('P0-2/P0-4 missing persona remains bindable and reports fallback without leaked text',async()=>{
 const f=fixture({companionPersona:true})
 try {
  writeFileSync(join(f.dir,'app','companion_persona.txt'),' ')
  const bind=await f.call('/bind',{method:'POST',body:{
    protocolVersion:1,conversation_id:'p0_missing_persona_session01'}})
  assert.equal(bind.code,200)
  const health=(await f.call('/health')).body
  assert.equal(health.persona.source,'fallback')
  assert.ok(health.persona.bytes<300)
  assert.equal(typeof health.persona.sha256,'string')
  const task=(await f.call('/submit',{method:'POST',
    body:{...input('p0_persona_turn00001','仅做隔离fixture测试'),
      conversation_id:'p0_missing_persona_session01'}})).body
  assert.equal(task.persona.source,'fallback')
  assert.deepEqual(Object.keys(task.persona.layers),['core','style','dynamic','memory'])
  assert.ok(!JSON.stringify(task).includes('你叫 DeepSeek'))
  assert.deepEqual(task.tools,[])
  assert.equal(f.agents[0].agent.followed.length,1)
 }finally{f.close()}
})

test('P1-1/P1-2 persona sections and context hot-update within the same Agent',async()=>{
 const f=fixture({companionPersona:true})
 try {
  const id='p1_dynamic_whale_session001'
  const bind=await f.call('/bind',{method:'POST',
    body:{protocolVersion:1,conversation_id:id}})
  assert.equal(bind.code,200)
  assert.deepEqual(f.personaSections.map(x=>x.name),[
    'dsh-live:whale-core','dsh-live:whale-style'])
  assert.equal(f.personaContexts.length,1)
  assert.equal(f.personaContexts[0].name,'dsh-live:whale-dynamic')
  assert.equal(f.personaContexts[0].order,211)
  const first=f.personaSections[0].text()
  writeFileSync(join(f.dir,'app','companion_persona.txt'),
    '我是大肥鱼新版身份。\n不冒充工具。\n下一轮风格已经更新。')
  assert.notEqual(f.personaSections[0].text(),first)
  assert.equal(f.personaSections[1].text(),'下一轮风格已经更新。')
  assert.ok(Buffer.byteLength(f.personaContexts[0].text())<1200)
  assert.equal(f.created,1,'no Agent recreation')
 }finally{f.close()}
})

test('P2 growth explicitly consented candidate/review/rollback, no hidden extraction or model call',async()=>{
 const f=fixture({manualMemory:true,companionPersona:true,personaGrowth:true})
 const call=(body,admin=adminToken,bearer=token)=>f.call('/memory-manage',{
   method:'POST',body:{protocolVersion:1,...body},admin,bearer,
 })
 try {
   const health=(await f.call('/health')).body
   assert.equal(health.growth.version,0)
   assert.equal(health.growth.active_count,0)
   assert.equal((await call({action:'growth.propose',text:'虚构事实：喜欢蓝色',
     confirm:'USER_EXPLICIT_GROWTH_PROPOSAL'})).code,403)
   assert.equal((await call({action:'consent',allow:true,
     confirm:'MANUAL_MEMORY_CONSENT'})).code,200)
   assert.equal((await call({action:'growth.propose',text:'虚构事实：喜欢蓝色',
     confirm:'USER_EXPLICIT_GROWTH_PROPOSAL'},'bad-token')).code,403)
   assert.equal((await call({action:'growth.propose',text:'虚构事实：喜欢蓝色'})).code,400)
   const created=(await call({action:'growth.propose',text:'虚构事实：喜欢蓝色',
     turn_id:'manual_turn_001',confirm:'USER_EXPLICIT_GROWTH_PROPOSAL'})).body
   assert.ok(created.id)
   assert.equal((await call({action:'growth.propose',text:'虚构事实：喜欢蓝色',
     confirm:'USER_EXPLICIT_GROWTH_PROPOSAL'})).body.duplicate,true)
   assert.equal((await call({action:'growth.decide',id:created.id,decision:'accept',
     expectedRevision:1})).code,400)
   assert.equal((await call({action:'growth.decide',id:created.id,decision:'accept',
     expectedRevision:0,confirm:'ACCEPT_GROWTH_FACT'})).code,409)
   assert.equal((await call({action:'growth.version'})).body.active_count,0)
   assert.equal((await call({action:'growth.decide',id:created.id,decision:'accept',
     expectedRevision:1,confirm:'ACCEPT_GROWTH_FACT'})).body.version,1)
   assert.equal((await call({action:'growth.list',status:'accepted'})).body.candidates.length,1)
   assert.equal((await f.call('/health')).body.growth.active_count,1)
   const bind=await f.call('/bind',{method:'POST',body:{
     protocolVersion:1,conversation_id:'growth_demo_offline001',
   }})
   assert.equal(bind.code,200)
   assert.equal(f.personaContexts.length,1)
   const dynamic=f.personaContexts[0].text()
   assert.match(dynamic,/虚构事实：喜欢蓝色/)
   assert.ok(Buffer.byteLength(dynamic)<1200)
   assert.equal((await call({action:'growth.rollback',toVersion:0,
     expectedRevision:2,confirm:'ROLLBACK_GROWTH_VERSION'})).body.version,2)
   assert.doesNotMatch(f.personaContexts[0].text(),/喜欢蓝色/)
   assert.equal(f.created,1,'only explicit /bind creates an Agent, no model requests')
   assert.equal(f.agents[0].agent.followed.length,0)
 }finally{f.close()}
})

test('R236 native production profile config reads private admin file without environment token',async()=>{
 const f=fixture({profileMemory:true,companionPersona:true})
 const call=body=>f.call('/memory-manage',{method:'POST',body:{protocolVersion:1,...body},admin:adminToken})
 try {
  assert.equal((await call({action:'growth.version'})).code,200)
  assert.equal((await call({action:'growth.version'})).body.suggestions_enabled,false)
  assert.equal((await call({action:'growth.suggestion-consent',allow:true,expectedRevision:0,
    confirm:'GROWTH_SUGGESTIONS_CONSENT'})).code,403,'consent still mandatory')
  assert.equal((await call({action:'consent',allow:true,
    confirm:'MANUAL_MEMORY_CONSENT'})).code,200)
  assert.equal((await call({action:'growth.suggestion-consent',allow:true,expectedRevision:0,
    confirm:'GROWTH_SUGGESTIONS_CONSENT'})).code,200)
  assert.equal((await call({action:'growth.version'})).body.suggestions_enabled,true)
  assert.equal((await f.call('/memory-manage',{method:'POST',body:{
    protocolVersion:1,action:'growth.version'},admin:'wrong'})).code,403)
 }finally{f.close()}
})

test('R236 native turn can suggest but never self-approve; opt out and rejected/failing turns are safe',async()=>{
 const f=fixture({manualMemory:true,companionPersona:true,personaGrowth:true})
 const call=body=>f.call('/memory-manage',{method:'POST',body:{protocolVersion:1,...body},admin:adminToken})
 try{
  const cons=await call({action:'consent',allow:true,confirm:'MANUAL_MEMORY_CONSENT'})
  assert.equal(cons.code,200)
  let current=(await call({action:'growth.version'})).body
  assert.equal(current.suggestions_enabled,false)
  assert.equal((await call({action:'growth.suggestion-consent',allow:true,expectedRevision:current.revision,
    confirm:'GROWTH_SUGGESTIONS_CONSENT'},)).code,200)
  current=(await call({action:'growth.version'})).body
  assert.equal(current.suggestions_enabled,true)
  const conversation='r236_growth_conversation_001'
  const bind=await f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:conversation}})
  assert.equal(bind.code,200)
  const turn='r236_first_turn_001'
  const result=await f.call('/submit',{method:'POST',body:{
    protocolVersion:1,conversation_id:conversation,turn_id:turn,
    prompt:'以后我希望你说话自然一点，别太官方',
  }})
  assert.equal(result.code,202)
  const a=f.agents[0].agent
  await f.runHooks('session/event',a.session,{type:'assistant/message',data:{
   message:{content:[{type:'text',text:'收到。'}]}}})
  await f.runHooks('session/event',a.session,{type:'turn/end',data:{reason:{kind:'completed'}}})
  await f.runHooks('agent/status',{agent:a,status:'idle'})
  current=(await call({action:'growth.version'})).body
  assert.equal(current.candidate_count,1)
  assert.equal(current.active_count,0)
  assert.equal(f.created,1)
  let list=(await call({action:'growth.list'})).body.candidates
  assert.equal(list[0].source,'assistant_suggested')
  assert.equal(list[0].text,'日常聊天使用自然亲切的表达，减少模板化客服语气。')
  assert.equal((await f.call('/submit',{method:'POST',body:{
   protocolVersion:1,conversation_id:conversation,turn_id:turn,
   prompt:'以后我希望你说话自然一点，别太官方'}})).body.idempotent,true)
  assert.equal((await call({action:'growth.version'})).body.candidate_count,1)
  assert.equal((await call({action:'growth.suggestion-consent',allow:false,expectedRevision:current.revision,
    confirm:'GROWTH_SUGGESTIONS_CONSENT'})).code,200)
  assert.equal((await call({action:'growth.decide',id:list[0].id,decision:'reject',
    expectedRevision:current.revision+1,confirm:'REJECT_GROWTH_FACT'})).code,200)
  assert.equal((await call({action:'growth.version'})).body.active_count,0)
  const rejected=(await call({action:'growth.list',status:'rejected'})).body.candidates
  assert.equal(rejected.length,1)
  assert.ok(!f.personaContexts[0].text().includes('自然亲切'))
  // New conversations/turns after opt-out must never create a suggestion.
  const off=await f.call('/submit',{method:'POST',body:{
    protocolVersion:1,conversation_id:conversation,turn_id:'r236_second_turn_002',
    prompt:'大肥鱼你平时请尽量回答简洁一点',
  }})
  assert.equal(off.code,202)
  await f.runHooks('session/event',a.session,{type:'assistant/message',data:{
   message:{content:[{type:'text',text:'好的。'}]}}})
  await f.runHooks('session/event',a.session,{type:'turn/end',data:{reason:{kind:'completed'}}})
  await f.runHooks('agent/status',{agent:a,status:'idle'})
  assert.equal((await call({action:'growth.version'})).body.candidate_count,0)
  assert.equal((await call({action:'growth.version'})).body.version,0)
  current=(await call({action:'growth.version'})).body
  assert.equal((await call({action:'growth.suggestion-consent',allow:true,
    expectedRevision:current.revision,confirm:'GROWTH_SUGGESTIONS_CONSENT'})).code,200)
  const failed=await f.call('/submit',{method:'POST',body:{
    protocolVersion:1,conversation_id:conversation,turn_id:'r236_failed_turn_003',
    prompt:'以后我希望你说话自然一点，别太官方',
  }})
  assert.equal(failed.code,202)
  await f.runHooks('session/event',a.session,{type:'turn/end',data:{reason:{kind:'blocked'}}})
  await f.runHooks('agent/status',{agent:a,status:'idle'})
  assert.equal((await call({action:'growth.version'})).body.candidate_count,0,
    'native blocked turn never proposes despite consent')
 }finally{f.close()}
})
test('V7/V9 reviewed growth restores exactly the prior persona hash within same Agent',async()=>{
 const f=fixture({manualMemory:true,companionPersona:true,personaGrowth:true})
 const call=body=>f.call('/memory-manage',{
   method:'POST',body:{protocolVersion:1,...body},admin:adminToken,
 })
 try{
  assert.equal((await call({action:'consent',allow:true,
    confirm:'MANUAL_MEMORY_CONSENT'})).code,200)
  const a=(await call({action:'growth.propose',text:'测试事实一：喜欢夏天',
    confirm:'USER_EXPLICIT_GROWTH_PROPOSAL'})).body.id
  assert.equal((await call({action:'growth.decide',id:a,decision:'accept',
    expectedRevision:1,confirm:'ACCEPT_GROWTH_FACT'})).body.version,1)
  assert.equal((await f.call('/bind',{method:'POST',body:{
    protocolVersion:1,conversation_id:'same_agent_snapshot_001'}})).code,200)
  const original=(await f.call('/health')).body.persona
  const text=f.personaContexts[0].text()
  assert.equal(original.version,1)
  assert.ok(original.bytes<=8192)
  assert.ok(original.layers.memory>0)
  assert.match(text,/测试事实一/)
  const b=(await call({action:'growth.propose',text:'测试事实二：喜欢森林',
    confirm:'USER_EXPLICIT_GROWTH_PROPOSAL'})).body.id
  assert.equal((await call({action:'growth.decide',id:b,decision:'accept',
    expectedRevision:3,confirm:'ACCEPT_GROWTH_FACT'})).body.version,2)
  assert.notEqual((await f.call('/health')).body.persona.sha256,original.sha256)
  const rolled=(await call({action:'growth.rollback',toVersion:1,
    expectedRevision:4,confirm:'ROLLBACK_GROWTH_VERSION'})).body
  assert.equal(rolled.version,3)
  const restored=(await f.call('/health')).body.persona
  assert.equal(restored.sha256,original.sha256)
  assert.equal(restored.version,3)
  assert.equal(restored.bytes,original.bytes)
  assert.equal(f.personaContexts[0].text(),text)
  assert.equal(f.created,1)
 }finally{f.close()}
})

test('V7 upper bound prevents approved facts from exceeding original 8192-byte ceiling',async()=>{
 const f=fixture({manualMemory:true,companionPersona:true,personaGrowth:true})
 const call=body=>f.call('/memory-manage',{
   method:'POST',body:{protocolVersion:1,...body},admin:adminToken,
 })
 try{
  const source=join(f.dir,'app','companion_persona.txt')
  writeFileSync(source,'身份。\n真实性。\n'+('中'.repeat(2718)))
  assert.equal((await call({action:'consent',allow:true,
     confirm:'MANUAL_MEMORY_CONSENT'})).code,200)
  const p=(await call({action:'growth.propose',text:'仅供预算验证的测试事实',
     confirm:'USER_EXPLICIT_GROWTH_PROPOSAL'})).body
  assert.equal((await call({action:'growth.decide',id:p.id,decision:'accept',
    expectedRevision:1,confirm:'ACCEPT_GROWTH_FACT'})).code,200)
  assert.equal((await f.call('/bind',{method:'POST',body:{
    protocolVersion:1,conversation_id:'bounded_growth_agent_001'}})).code,200)
  const health=(await f.call('/health')).body
  assert.equal(health.persona.source,'file')
  assert.ok(health.persona.bytes<=8192)
  assert.equal(f.personaContexts[0].text(),'')
  assert.equal(health.persona.layers.memory,0)
 }finally{f.close()}
})

test('disabled bridge fails closed before secrets exist', async () => {
  const f = fixture({ key: '', root: false })
  try {
    assert.deepEqual((await f.call('/health')).body, { ok: true, protocolVersion: 1, configured: false })
    const blocked = await f.call('/submit', { method: 'POST', body: input() })
    assert.equal(blocked.code, 503)
    assert.equal(f.created, 0)
  } finally { f.close() }
})

test('auth and loopback enforced with the plugin-owned token', async () => {
  const f = fixture()
  try {
    assert.equal((await f.call('/submit', { method: 'POST', body: input(), bearer: '' })).code, 401)
    assert.equal((await f.call('/submit', { method: 'POST', body: input(), bearer: 'incorrect' })).code, 401)
    assert.equal((await f.call('/submit', { method: 'POST', body: input(), ip: '192.168.1.5' })).code, 403)
    assert.equal((await f.call('/submit', { method: 'GET' })).code, 405)
    assert.equal(f.created, 0)
  } finally { f.close() }
})

test('submits exactly once and uses Harness native agent with fixed cwd', async () => {
  const f = fixture()
  try {
    const response = await f.call('/submit', { method: 'POST', body: input() })
    assert.equal(response.code, 202)
    const task = response.body
    assert.equal(task.status, 'accepted')
    assert.equal(task.result, null)
    assert.equal(f.created, 1)
    assert.equal(f.agents[0].options.meta.cwd, f.dir)
    assert.deepEqual(f.agents[0].options.agentOptions,
      { provider: 'offline-test', model: 'deterministic-local' })
    assert.equal(f.agents[0].agent.followed.length, 1)
    assert.equal(f.agents[0].agent.followed[0].content[0].text, input().prompt)
    assert.ok(task.task_id && task.session_id)
    const retry = await f.call('/submit', { method: 'POST', body: input() })
    assert.equal(retry.code, 200)
    assert.equal(retry.body.idempotent, true)
    assert.equal(retry.body.task_id, task.task_id)
    assert.equal(f.created, 1)
    assert.equal((await f.call('/submit', { method: 'POST', body: input('turn_00000001', 'different') })).code, 409)
  } finally { f.close() }
})

test('never trusts 202 alone; requires both assistant message and actual idle', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const a = f.agents[0].agent
    await f.runHooks('agent/status', { agent: a, status: 'running' })
    let r = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(r.status, 'running')
    await f.runHooks('session/event', a.session, {
      type: 'assistant/message',
      data: { message: { content: [{ type: 'text', text: '查询执行完毕。' }] } },
    })
    r = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(r.status, 'running')
    assert.equal(r.result, null)
    await f.runHooks('agent/status', { agent: a, status: 'idle' })
    r = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(r.status, 'awaiting_result') // idle is not evidence of turn completion
    await f.runHooks('session/event', a.session, {
      type: 'turn/end', data: { reason: { kind: 'completed' } },
    })
    r = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(r.status, 'answered')
    assert.equal(r.result.text, '查询执行完毕。')
    assert.equal(r.result.execution_verified, false)
    assert.equal(r.result.source, 'harness_assistant')
    const again = await f.call('/submit', { method: 'POST', body: input() })
    assert.equal(again.body.idempotent, true)
    assert.equal(f.created, 1)
  } finally { f.close() }
})

test('official native assistant-stream is observed only by the bound task and never leaks tentative text',async()=>{
  const f=fixture()
  try{
    const task=(await f.call('/submit',{method:'POST',body:input('stream_turn_0001','打个招呼')})).body
    const a=f.agents[0].agent
    // Same id but wrong object must never be treated as the official owner.
    const spoof={id:a.id}
    const start={type:'start',attemptId:'official-attempt-01',revision:1,turn:1,step:0}
    await f.runHooks('agent/assistant-stream',{agent:spoof,frame:start})
    await f.runHooks('agent/assistant-stream',{agent:a,frame:start})
    const delta={type:'chunk',attemptId:start.attemptId,revision:1,index:0,time:1000,
      chunk:{type:'text-delta',index:0,text:'本鱼在呢。'}}
    await f.runHooks('agent/assistant-stream',{agent:a,frame:delta})
    const before=(await f.call('/result',{method:'POST',body:query(task)})).body
    assert.equal(before.result,null,'precommit text must not be public')
    assert.equal(JSON.stringify(before).includes('本鱼在呢'),false)
    await f.runHooks('session/event',a.session,{type:'assistant/message',
      data:{message:{content:[{type:'text',text:'本鱼在呢。'}]}}})
    await f.runHooks('agent/assistant-stream',{agent:a,frame:{
      type:'end',attemptId:start.attemptId,revision:1,index:1,
      outcome:{kind:'committed',eventType:'assistant/message',seq:5}
    }})
    await f.runHooks('session/event',a.session,{type:'turn/end',data:{reason:{kind:'completed'}}})
    await f.runHooks('agent/status',{agent:a,status:'idle'})
    const actual=(await f.call('/result',{method:'POST',body:query(task)})).body
    assert.equal(actual.status,'answered')
    assert.equal(actual.result.text,'本鱼在呢。')
    assert.equal(actual.result.execution_verified,false)
    assert.equal(JSON.stringify(actual).includes('speechPrewarm'),false)
    assert.equal(JSON.stringify(actual).includes('official-attempt-01'),false)
    assert.equal(f.agents[0].agent.followed.length,1,'must not start an extra Agent turn')
  }finally{f.close()}
})

test('native stream cancelled or tool-owned cannot be leaked as confirmed speech',async()=>{
  const f=fixture()
  try{
    const task=(await f.call('/submit',{method:'POST',body:input('stream_turn_0002','查询状态')})).body
    const a=f.agents[0].agent
    const start={type:'start',attemptId:'attempt-tool',revision:1,turn:3,step:0}
    await f.runHooks('agent/assistant-stream',{agent:a,frame:start})
    await f.runHooks('agent/assistant-stream',{agent:a,frame:{type:'chunk',
      attemptId:start.attemptId,revision:1,index:0,time:1000,
      chunk:{type:'text-delta',text:'已经执行成功。',index:0}}})
    await f.runHooks('session/event',a.session,{type:'tool/call',
      data:{callId:'tool-01',name:'fixture_echo',arguments:'{}'}})
    const pending=(await f.call('/result',{method:'POST',body:query(task)})).body
    assert.equal(pending.result,null)
    assert.equal(JSON.stringify(pending).includes('已经执行成功'),false)
    await f.runHooks('agent/assistant-stream',{agent:a,frame:{type:'end',
      attemptId:start.attemptId,revision:1,index:1,
      outcome:{kind:'committed',eventType:'assistant/message',seq:5}}})
    const cancelled=await f.call('/cancel',{method:'POST',body:query(task)})
    assert.equal(cancelled.code,202)
    await f.runHooks('session/event',a.session,{type:'turn/end',data:{reason:{kind:'aborted'}}})
    await f.runHooks('agent/status',{agent:a,status:'idle'})
    const final=(await f.call('/result',{method:'POST',body:query(task)})).body
    assert.equal(final.status,'cancelled')
    assert.equal(final.result,null)
    assert.equal(JSON.stringify(final).includes('已经执行成功'),false)
  }finally{f.close()}
})

test('native reasoning is only a typed presence bit, no raw private content',async()=>{
  const f=fixture()
  try{
    const task=(await f.call('/submit',{method:'POST',body:input()})).body
    const a=f.agents[0].agent
    await f.runHooks('session/event',a.session,{
      type:'assistant/message',
      data:{message:{content:[
        {type:'reasoning',text:'PRIVATE_TRACE_NEVER_EXPOSE_42'},
        {type:'text',text:'对外回答。'}
      ]}}
    })
    await f.runHooks('session/event',a.session,{
      type:'turn/end',data:{reason:{kind:'completed'}}
    })
    await f.runHooks('agent/status',{agent:a,status:'idle'})
    const done=(await f.call('/result',{method:'POST',body:query(task)})).body
    assert.equal(done.status,'answered')
    assert.equal(done.result.text,'对外回答。')
    assert.equal(done.result.reasoning_observed,true)
    assert.equal(JSON.stringify(done).includes('PRIVATE_TRACE_NEVER_EXPOSE_42'),false)
  }finally{f.close()}
  const noReason=fixture()
  try{
    const task=(await noReason.call('/submit',{method:'POST',body:input()})).body
    const a=noReason.agents[0].agent
    await noReason.runHooks('session/event',a.session,{
      type:'assistant/message',
      data:{message:{content:[
        {type:'text',text:'普通回答。'}
      ]}}
    })
    await noReason.runHooks('session/event',a.session,{
      type:'turn/end',data:{reason:{kind:'completed'}}
    })
    await noReason.runHooks('agent/status',{agent:a,status:'idle'})
    const done=(await noReason.call('/result',{method:'POST',body:query(task)})).body
    assert.equal(done.result.reasoning_observed,false)
  }finally{noReason.close()}
})

test('out-of-order idle and assistant message still converge without fabricating result', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const agent = f.agents[0].agent
    await f.runHooks('agent/status', { agent, status: 'idle' })
    assert.equal((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'awaiting_result')
    await f.runHooks('session/event', agent.session, {
      type: 'assistant/message', data: { message: { content: [{ type: 'text', text: '这是回答' }] } },
    })
    assert.equal((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'awaiting_result')
    await f.runHooks('session/event', agent.session, {
      type: 'turn/end', data: { reason: { kind: 'completed' } },
    })
    assert.equal((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'answered')
  } finally { f.close() }
})

test('approvals are observed but not intercepted, decided, or auto-approved', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const a = f.agents[0].agent
    await f.runHooks('agent/status', { agent: a, status: 'running' })
    await f.runHooks('session/event', a.session, { type: 'approval/asked', data: {id:'original-approval',toolName:'fixture-echo'} })
    assert.equal((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'approval_needed')
    await f.runHooks('agent/status', { agent: a, status: 'idle' })
    await f.runHooks('session/event', a.session, {
      type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'pending' }] } },
    })
    assert.notEqual((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'completed')
    await f.runHooks('session/event', a.session, { type: 'approval/decided', data: {id:'original-approval',outcome:'allowed-once'} })
    assert.equal((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'running')
    await f.runHooks('session/event', a.session, {
      type: 'turn/end', data: { reason: { kind: 'completed' } },
    })
    assert.equal((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'answered')
  } finally { f.close() }
})

test('failed agent never reports task success even when assistant text exists', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const a = f.agents[0].agent
    await f.runHooks('session/event', a.session, {
      type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'premature' }] } },
    })
    await f.runHooks('agent/error', { agent: a })
    await f.runHooks('agent/status', { agent: a, status: 'idle' })
    const result = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(result.status, 'failed')
    assert.equal(result.result, null)
  } finally { f.close() }
})

test('invalid input and attempts to override cwd/provider/model are rejected', async () => {
  const f = fixture()
  try {
    for (const bad of [
      { ...input(), cwd: '/tmp' }, { ...input(), provider: 'other' },
      { ...input(), model: 'some-model' }, { ...input(), foo: true },
      { ...input(), turn_id: 'a' }, { ...input(), prompt: '' },
      { ...input(), prompt: 'x'.repeat(4001) }, { ...input(), protocolVersion: 2 },
      [],
    ]) {
      assert.equal((await f.call('/submit', { method: 'POST', body: bad })).code, 400)
    }
    assert.equal((await f.call('/result', { method: 'POST', body: { protocolVersion: 1, task_id: 'nonexistent' } })).code, 404)
    assert.equal((await f.call('/result', { method: 'POST', body: null })).code, 400)
    assert.equal(f.created, 0)
  } finally { f.close() }
})

test('independent tasks do not leak response across sessions', async () => {
  const f = fixture()
  try {
    const one = (await f.call('/submit', { method: 'POST', body: input('turn_11111111') })).body
    const two = (await f.call('/submit', { method: 'POST', body: input('turn_22222222') })).body
    assert.notEqual(one.session_id, two.session_id)
    const agent2 = f.agents[1].agent
    await f.runHooks('agent/status', { agent: agent2, status: 'idle' })
    await f.runHooks('session/event', agent2.session, {
      type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'second only' }] } },
    })
    await f.runHooks('session/event', agent2.session, {
      type: 'turn/end', data: { reason: { kind: 'completed' } },
    })
    const first = (await f.call('/result', { method: 'POST', body: query(one) })).body
    const second = (await f.call('/result', { method: 'POST', body: query(two) })).body
    assert.equal(first.result, null)
    assert.equal(second.result.text, 'second only')
  } finally { f.close() }
})

test('no caller-exposed approval endpoint exists', async () => {
  const f = fixture()
  try {
    await assert.rejects(() => f.call('/approval', { method: 'POST', body: {} }), /not registered/)
  } finally { f.close() }
})

test('late native agent error wins over assistant-text completion', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const a = f.agents[0].agent
    await f.runHooks('session/event', a.session, {
      type: 'assistant/message', data: { message: { content: [{ type: 'text', text: '回答' }] } },
    })
    await f.runHooks('agent/status', { agent: a, status: 'idle' })
    await f.runHooks('agent/error', { agent: a })
    const state = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(state.status, 'failed')
    assert.equal(state.result, null)
  } finally { f.close() }
})

test('failed Harness creation yields fail-closed receipt without exposing exception', async () => {
  const f = fixture({ failCreate: true })
  try {
    const response = await f.call('/submit', { method: 'POST', body: input() })
    assert.equal(response.code, 500)
    assert.equal(response.body.status, 'failed')
    assert.equal(response.body.failure, 'harness_agent_failed')
    assert.doesNotMatch(JSON.stringify(response.body), /private failure diagnostic/)
    assert.equal(f.created, 1)
    const retry = await f.call('/submit', { method: 'POST', body: input() })
    assert.equal(retry.body.idempotent, true)
    assert.equal(f.created, 1)
  } finally { f.close() }
})

test('active task ceiling rejects the seventeenth request without triggering Harness', async () => {
  const f = fixture()
  try {
    for (let i = 0; i < 16; i += 1) {
      const submit = await f.call('/submit', {
        method: 'POST', body: input('task_limit_' + String(i).padStart(3, '0')),
      })
      assert.equal(submit.code, 202)
    }
    const over = await f.call('/submit', {
      method: 'POST', body: input('task_limit_999'),
    })
    assert.equal(over.code, 429)
    assert.equal(f.created, 16)
  } finally { f.close() }
})

test('oversized JSON is rejected before any agent is created', async () => {
  const f = fixture()
  try {
    const response = await f.call('/submit', {
      method: 'POST',
      body: { ...input(), prompt: 'x'.repeat(20 * 1024) },
    })
    assert.equal(response.code, 413)
    assert.equal(response.body.error, 'body_too_large')
    assert.equal(f.created, 0)
  } finally { f.close() }
})

test('native tool/call plus paired successful tool/result and completed turn verifies execution', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const a = f.agents[0].agent
    await f.runHooks('session/event', a.session, {
      type: 'tool/call', data: { callId: 'call-one', name: 'read_file', arguments: '{}' },
    })
    await f.runHooks('session/event', a.session, {
      type: 'assistant/message', data: { message: { content: [{ type: 'text', text: '读取完成' }] } },
    })
    await f.runHooks('session/event', a.session, { type: 'turn/end', data: { reason: { kind: 'completed' } } })
    await f.runHooks('agent/status', { agent: a, status: 'idle' })
    let receipt = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(receipt.status, 'awaiting_result')
    await f.runHooks('session/event', a.session, {
      type: 'tool/result', data: { message: { content: [
        { type: 'tool-result', toolCallId: 'call-one', content: [{ type: 'text', text: 'OK' }], isError: false },
      ] } },
    })
    receipt = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(receipt.status, 'awaiting_result') // prior promise wasn't post-tool summary
    await f.runHooks('session/event', a.session, {
      type: 'assistant/message', data: { message: { content: [{ type: 'text', text: '实际结果已核对' }] } },
    })
    receipt = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(receipt.status, 'completed')
    assert.equal(receipt.result.text, '实际结果已核对')
    assert.equal(receipt.result.execution_verified, true)
    assert.equal(receipt.result.source, 'harness_tool_events')
    assert.deepEqual(receipt.result.tool_receipts, [{ name: 'read_file', receipt: 'success' }])
  } finally { f.close() }
})

test('native failed tool result defeats plausible success prose', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const a = f.agents[0].agent
    await f.runHooks('session/event', a.session, { type: 'tool/call', data: { callId: 'call-two', name: 'shell' } })
    await f.runHooks('session/event', a.session, {
      type: 'tool/result', data: { message: { content: [
        { type: 'tool-result', toolCallId: 'call-two', content: [], isError: true },
      ] }, error: { name: 'ExecError', code: 'EXIT_1' } },
    })
    await f.runHooks('session/event', a.session, {
      type: 'assistant/message', data: { message: { content: [{ type: 'text', text: '已经完成' }] } },
    })
    await f.runHooks('session/event', a.session, { type: 'turn/end', data: { reason: { kind: 'completed' } } })
    await f.runHooks('agent/status', { agent: a, status: 'idle' })
    const r = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(r.status, 'failed')
    assert.equal(r.failure, 'native_tool_failed')
    assert.equal(r.result, null)
  } finally { f.close() }
})

test('unpaired, malformed, and unsupported tool results cannot verify success', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const a = f.agents[0].agent
    await f.runHooks('session/event', a.session, { type: 'tool/call', data: { callId: 'expected', name: 'read_file' } })
    await f.runHooks('session/event', a.session, { type: 'tool/result', data: {
      message: { content: [{ type: 'tool-result', toolCallId: 'wrong', isError: false }] },
    } })
    await f.runHooks('session/event', a.session, { type: 'tool/result', data: {
      message: { content: [{ type: 'tool-result', toolCallId: 'expected', isError: 'false' }] },
    } })
    await f.runHooks('session/event', a.session, {
      type: 'assistant/message', data: { message: { content: [{ type: 'text', text: '成功' }] } },
    })
    await f.runHooks('session/event', a.session, { type: 'turn/end', data: { reason: { kind: 'completed' } } })
    await f.runHooks('agent/status', { agent: a, status: 'idle' })
    const r = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(r.status, 'awaiting_result')
    assert.equal(r.result, null)
    assert.equal((await f.call('/submit', { method: 'POST', body: input() })).body.idempotent, true)
    assert.equal(f.created, 1)
  } finally { f.close() }
})

test('turn abort is cancelled, and blocked/error/max-tokens turn ends are failures', async () => {
  for (const kind of ['aborted', 'blocked', 'error', 'max-tokens']) {
    const f = fixture()
    try {
      const task = (await f.call('/submit', { method: 'POST', body: input() })).body
      const a = f.agents[0].agent
      await f.runHooks('session/event', a.session, {
        type: 'assistant/message', data: { message: { content: [{ type: 'text', text: '部分文字' }] } },
      })
      await f.runHooks('session/event', a.session, { type: 'turn/end', data: {
        reason: { kind, ...(kind === 'aborted' ? { reason: { kind: 'user' } } : {}) },
      } })
      await f.runHooks('agent/status', { agent: a, status: 'idle' })
      const r = (await f.call('/result', { method: 'POST', body: query(task) })).body
      assert.equal(r.status, kind === 'aborted' ? 'cancelled' : 'failed')
      assert.equal(r.result, null)
      if (kind !== 'aborted') assert.equal(r.failure, 'harness_turn_' + kind)
    } finally { f.close() }
  }
})

test('authenticated native cancel waits for aborted turn/end and idle', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const a = f.agents[0].agent
    assert.equal((await f.call('/cancel', { method: 'POST', body: query(task), bearer: '' })).code, 401)
    assert.equal((await f.call('/cancel', { method: 'POST', body: query(task), ip: '10.0.0.4' })).code, 403)
    assert.equal((await f.call('/cancel', { method: 'POST', body: { ...query(task), approval: 'allow' } })).code, 400)
    assert.equal(a.cancels.length, 0)
    const requested = await f.call('/cancel', { method: 'POST', body: query(task) })
    assert.equal(requested.code, 202)
    assert.equal(requested.body.status, 'cancel_requested')
    assert.deepEqual(a.cancels, [{ kind: 'user' }])
    assert.equal((await f.call('/cancel', { method: 'POST', body: query(task) })).body.idempotent, true)
    assert.equal(a.cancels.length, 1)
    await f.runHooks('agent/status', { agent: a, status: 'running' })
    assert.equal((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'cancel_requested')
    await f.runHooks('session/event', a.session, {
      type: 'turn/end', data: { reason: { kind: 'aborted', reason: { kind: 'user' } } },
    })
    assert.equal((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'cancel_requested')
    await f.runHooks('agent/status', { agent: a, status: 'idle' })
    assert.equal((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'cancelled')
  } finally { f.close() }
})

test('missing native cancel fails closed without claiming cancelled', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    f.agents[0].agent.cancel = undefined
    const r = await f.call('/cancel', { method: 'POST', body: query(task) })
    assert.equal(r.code, 501)
    assert.equal(r.body.error, 'native_cancel_unavailable')
    assert.equal((await f.call('/result', { method: 'POST', body: query(task) })).body.status, 'accepted')
  } finally { f.close() }
})

test('official DSH bundle metadata and patch are present for explicit profile install', () => {
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
  const patch = readFileSync(new URL('../cordis.patch.yml', import.meta.url), 'utf8')
  assert.equal(pkg.name, 'dsh-live-bridge')
  assert.equal(pkg.dsh?.bundle?.patch, './cordis.patch.yml')
  assert.match(patch, /id: dsh-live-bridge/)
  assert.match(patch, /name: 'dsh-live-bridge'/)
  assert.doesNotMatch(JSON.stringify(pkg), /dsh-desktop-bridge|dsh-desktop-token/)
})

test('installed DSH 0.2 V4 tool-role receipt confirms only matching producer-owned result', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const a = f.agents[0].agent
    await f.runHooks('session/event', a.session, { type: 'tool/call', data: {
      turn: 1, step: 1, callId: 'v4-call-1', name: 'read_file', arguments: '{}',
    } })
    await f.runHooks('session/event', a.session, { type: 'tool/result', data: {
      message: { role: 'tool', toolCallId: 'v4-call-1',
        source: { kind: 'plugin', callId: 'v4-call-1' }, content: [], isError: false },
    } })
    await f.runHooks('session/event', a.session, { type: 'assistant/message', data: {
      message: { content: [{ type: 'text', text: '文件已检查' }] },
    } })
    await f.runHooks('session/event', a.session, {
      type: 'turn/end', data: { reason: { kind: 'completed' } },
    })
    await f.runHooks('agent/status', { agent: a, status: 'idle' })
    let result = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(result.status, 'awaiting_result')
    await f.runHooks('session/event', a.session, { type: 'tool/result', data: {
      message: { role: 'tool', toolCallId: 'v4-call-1',
        source: { kind: 'tool', callId: 'v4-call-1' }, content: [], isError: false },
    } })
    result = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(result.status, 'awaiting_result') // tool arrived after prior prose
    await f.runHooks('session/event', a.session, { type: 'assistant/message', data: {
      message: { content: [{ type: 'text', text: '确认来自真实工具回执' }] },
    } })
    result = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(result.status, 'completed')
    assert.equal(result.result.execution_verified, true)
    assert.deepEqual(result.result.tool_receipts, [{ name: 'read_file', receipt: 'success' }])
  } finally { f.close() }
})

test('installed DSH 0.2 V4 tool error blocks a success-sounding assistant', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', { method: 'POST', body: input() })).body
    const a = f.agents[0].agent
    await f.runHooks('session/event', a.session, {
      type: 'tool/call', data: { callId: 'v4-failed', name: 'shell' },
    })
    await f.runHooks('session/event', a.session, { type: 'tool/result', data: {
      message: { role: 'tool', toolCallId: 'v4-failed',
        source: { kind: 'tool', callId: 'v4-failed' }, content: [], isError: true },
      error: { name: 'ToolFailure', code: 'FAILED' },
    } })
    await f.runHooks('session/event', a.session, { type: 'assistant/message', data: {
      message: { content: [{ type: 'text', text: '已执行成功' }] },
    } })
    await f.runHooks('session/event', a.session, {
      type: 'turn/end', data: { reason: { kind: 'completed' } },
    })
    await f.runHooks('agent/status', { agent: a, status: 'idle' })
    const result = (await f.call('/result', { method: 'POST', body: query(task) })).body
    assert.equal(result.status, 'failed')
    assert.equal(result.failure, 'native_tool_failed')
    assert.equal(result.result, null)
  } finally { f.close() }
})

test('absent native default provider/model fails closed before creating any Agent', async () => {
  for (const defaultModel of [null, {}, {provider:'offline-test'}, {model:'local'}]) {
    const f=fixture({defaultModel})
    try {
      const r=await f.call('/submit',{method:'POST',body:input()})
      assert.equal(r.code,500)
      assert.equal(r.body.status,'failed')
      assert.equal(r.body.result,null)
      assert.equal(f.created,0)
      assert.equal((await f.call('/submit',{method:'POST',body:input()})).body.idempotent,true)
    } finally {f.close()}
  }
})

test('opt-in Mac volume mode scopes the Agent, caps its model output and never exposes inherited tools', async () => {
  const original = process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
  process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL = '1'
  const f = fixture()
  try {
    const accepted = await f.call('/submit', { method:'POST', body:input() })
    assert.equal(accepted.code, 202)
    const options = f.agents[0].options
    assert.equal(options.agentOptions.maxTokens, 512)
    assert.equal(typeof options.setup, 'function')
    const captures = {}
    options.setup({ on() { return () => {} }, tools: {
      restrict(value) {captures.restrict=value},
      guard(callback) {captures.guard=callback},
      register(value) {captures.tool=value},
    } })
    assert.deepEqual(captures.restrict, {allow: []})
    assert.equal(captures.tool.name, 'dsh_live_read_volume')
    assert.equal(captures.guard({name:'dsh_live_read_volume'}), undefined)
    assert.match(captures.guard({name:'bash'}), /readonly_scope/)
  } finally {
    f.close()
    if (original === undefined) delete process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
    else process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL = original
  }
})

const convoInput = (conversation_id, turn_id, prompt = '继续上一轮') =>
  ({ protocolVersion: 1, conversation_id, turn_id, prompt })
const modelInput = (conversation_id, model) =>
  ({ protocolVersion: 1, conversation_id, model })
async function settle(f, task, agent, text = '测试回复') {
  await f.runHooks('session/event', agent.session, {
    type: 'assistant/message', data: { message: { content: [{type: 'text', text}] } },
  })
  await f.runHooks('session/event', agent.session, {
    type: 'turn/end', data: {reason: {kind: 'completed'}},
  })
  await f.runHooks('agent/status', {agent, status: 'idle'})
  return (await f.call('/result', {method:'POST',body:query(task)})).body
}
test('one conversation keeps the same real Harness Agent/Session across three turns', async () => {
  const f = fixture()
  try {
    const c = 'whale_convo_001'
    let previous = null
    for (let i = 1; i <= 3; i++) {
      const task = (await f.call('/submit', {method:'POST',
        body:convoInput(c,'multi_turn_00'+i,'question '+i)})).body
      assert.equal(task.status, 'accepted')
      assert.equal(task.conversation_id, c)
      if (previous) assert.equal(task.session_id, previous)
      previous = task.session_id
      assert.equal((await settle(f,task,f.agents[0].agent,'answer '+i)).result.text,'answer '+i)
    }
    assert.equal(f.created,1)
    assert.equal(f.agents[0].agent.followed.length,3)
    const session = (await f.call('/session',{method:'POST',body:{protocolVersion:1,conversation_id:c}})).body
    assert.equal(session.session_id,previous)
    assert.deepEqual(session.selected,{provider:'offline-test',model:'deterministic-local'})
  } finally {f.close()}
})
test('two conversations have isolated native Session model selection, receipts and IDs', async () => {
  const f=fixture()
  try {
    const a='convo_isolated_A',b='convo_isolated_B'
    const t1=(await f.call('/submit',{method:'POST',body:convoInput(a,'isolated_turn_1')})).body
    const t2=(await f.call('/submit',{method:'POST',body:convoInput(b,'isolated_turn_2')})).body
    assert.notEqual(t1.session_id,t2.session_id)
    assert.notEqual(t1.task_id,t2.task_id)
    await settle(f,t1,f.agents[0].agent,'response A')
    await settle(f,t2,f.agents[1].agent,'response B')
    const changed=await f.call('/model',{method:'POST',body:modelInput(a,'deepseek-pro')})
    assert.equal(changed.code,200)
    assert.deepEqual(changed.body.selected,{provider:'offline-test',model:'deepseek-pro'})
    const queried=(await f.call('/session',{method:'POST',body:{protocolVersion:1,conversation_id:b}})).body
    assert.equal(queried.selected.model,'deterministic-local')
    assert.deepEqual(f.agents[0].agent.session.events.at(-1),
      {type:'model/selection',data:{provider:'offline-test',model:'deepseek-pro'}})
    assert.equal(f.agents[1].agent.session.events.length,1)
    const next=(await f.call('/submit',{method:'POST',body:convoInput(a,'isolated_turn_3')})).body
    assert.equal(next.session_id,t1.session_id)
    assert.equal(f.created,2)
    assert.equal((await settle(f,next,f.agents[0].agent,'response A2')).result.text,'response A2')
    assert.equal((await f.call('/result',{method:'POST',body:query(t2)})).body.result.text,'response B')
  } finally {f.close()}
})
test('model switch fails closed and does not mutate the bound native Session or default',async()=>{
  const f=fixture()
  try{
    const c='convo_rollback_1'
    const t=(await f.call('/submit',{method:'POST',body:convoInput(c,'rollback_turn_1')})).body
    await settle(f,t,f.agents[0].agent)
    const nativeEvents=f.agents[0].agent.session.events.length
    const r=await f.call('/model',{method:'POST',body:modelInput(c,'invalid-model')})
    assert.equal(r.code,422)
    assert.equal(r.body.error,'harness_model_unavailable')
    assert.equal(r.body.selected.model,'deterministic-local')
    assert.equal(f.agents[0].agent.session.events.length,nativeEvents)
    assert.equal((await f.call('/session',{method:'POST',body:{protocolVersion:1,conversation_id:c}})).body.selected.model,'deterministic-local')
    assert.equal(f.created,1)
    assert.equal((await f.call('/model',{method:'POST',body:{...modelInput(c,'deepseek-pro'), provider:'other'}})).code,400)
  } finally{f.close()}
})
test('per-Session busy switch and second submit fail without crossing cancel/task ownership',async()=>{
 const f=fixture()
 try{
   const a='session_busy_A', b='session_busy_B'
   const t=(await f.call('/submit',{method:'POST',body:convoInput(a,'busy_turn_001')})).body
   assert.equal((await f.call('/model',{method:'POST',body:modelInput(a,'deepseek-pro')})).body.error,'session_busy')
   assert.equal((await f.call('/submit',{method:'POST',body:convoInput(a,'busy_turn_002')})).body.error,'session_busy')
   const independent=(await f.call('/submit',{method:'POST',body:convoInput(b,'busy_turn_003')})).body
   assert.equal(independent.status,'accepted')
   const cancelling=(await f.call('/cancel',{method:'POST',body:query(t)})).body
   assert.equal(cancelling.status,'cancel_requested')
   assert.equal(f.agents[0].agent.cancels.length,1)
   assert.equal(f.agents[1].agent.cancels.length,0)
   await f.runHooks('session/event',f.agents[0].agent.session,{type:'turn/end',data:{reason:{kind:'aborted'}}})
   await f.runHooks('agent/status',{agent:f.agents[0].agent,status:'idle'})
   assert.equal((await f.call('/result',{method:'POST',body:query(t)})).body.status,'cancelled')
   assert.equal((await settle(f,independent,f.agents[1].agent,'independent')).status,'answered')
   assert.equal((await f.call('/model',{method:'POST',body:modelInput(a,'deepseek-pro')})).code,200)
 }finally{f.close()}
})
test('model and conversation endpoints require auth and do not implicitly create sessions',async()=>{
 const f=fixture()
 try{
  const body=modelInput('unknown_convo_1','deepseek-pro')
  assert.equal((await f.call('/model',{method:'POST',body,bearer:''})).code,401)
  assert.equal((await f.call('/model',{method:'POST',body,ip:'192.168.1.4'})).code,403)
  assert.equal((await f.call('/model',{method:'POST',body})).code,404)
  assert.equal((await f.call('/session',{method:'POST',body:{protocolVersion:1,conversation_id:'unknown_convo_1'}})).code,404)
  assert.equal(f.created,0)
 }finally{f.close()}
})

test('memory mode never runs without readonly Agent scope or valid local URL', async () => {
  const before = {
    enabled: process.env.DSH_LIVE_ENABLE_REME_SEARCH,
    url: process.env.DSH_LIVE_REME_URL,
    readonly: process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL,
  }
  process.env.DSH_LIVE_ENABLE_REME_SEARCH='1'
  delete process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
  process.env.DSH_LIVE_REME_URL='http://127.0.0.1:18997'
  const f = fixture()
  try {
    const answer=await f.call('/submit', {method:'POST',body:input('turn_memory_000001','虚构记忆测试')})
    assert.equal(answer.code,500)
    assert.equal(answer.body.status,'failed')
    assert.equal(f.created,0)
  } finally {
    f.close()
    for (const [k, key] of Object.entries({
      enabled:'DSH_LIVE_ENABLE_REME_SEARCH',
      url:'DSH_LIVE_REME_URL',
      readonly:'DSH_LIVE_ENABLE_MAC_READONLY_TOOL',
    })) {
      if (before[k] === undefined) delete process.env[key]
      else process.env[key] = before[k]
    }
  }
})

test('memory-enabled Bridge accepts only scoped volume plus shadowed ReMe tool', async () => {
  const previous = {
    enabled: process.env.DSH_LIVE_ENABLE_REME_SEARCH,
    readonly: process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL,
    url: process.env.DSH_LIVE_REME_URL,
  }
  process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL='1'
  process.env.DSH_LIVE_ENABLE_REME_SEARCH='1'
  process.env.DSH_LIVE_REME_URL='http://127.0.0.1:18997'
  const f=fixture()
  try {
    const response=await f.call('/submit',{method:'POST',body:input('turn_memory_000002','虚构检索')})
    assert.equal(response.code,202)
    assert.equal(f.created,1)
    const tools=[]
    let restrict,guard
    f.agents[0].options.setup({on(){return ()=>{}},tools:{
      restrict(value){restrict=value},
      guard(callback){guard=callback},
      register(tool){tools.push(tool.name)},
    }})
    assert.deepEqual(restrict,{allow:[]})
    assert.deepEqual(tools,['dsh_live_read_volume','reme_search'])
    assert.equal(guard({name:'reme_search'}),undefined)
    assert.match(guard({name:'bash'}),/readonly_scope/)
  } finally {
    f.close()
    for(const [k,key] of [['enabled','DSH_LIVE_ENABLE_REME_SEARCH'],
                          ['readonly','DSH_LIVE_ENABLE_MAC_READONLY_TOOL'],
                          ['url','DSH_LIVE_REME_URL']]) {
      if(previous[k]===undefined)delete process.env[key]
      else process.env[key]=previous[k]
    }
  }
})

test('E1b manual memory endpoint is doubly authenticated, explicit-consent, and disabled by default',async()=>{
 const disabled=fixture()
 try{
   assert.equal((await disabled.call('/memory-manage',{method:'POST',body:{protocolVersion:1,action:'list'}})).code,503)
 }finally{disabled.close()}
 const f=fixture({manualMemory:true})
 const ask=(body,admin=adminToken,bearer=token)=>f.call('/memory-manage',{method:'POST',body:{protocolVersion:1,...body},admin,bearer})
 try{
   assert.equal((await ask({action:'list'},'wrong')).code,403)
   assert.equal((await ask({action:'list'},adminToken,'wrong')).code,401)
   assert.equal((await ask({action:'list',unexpected:'field'})).code,400)
   assert.equal((await ask({action:'put',text:'虚构事实：喜欢香草布丁'})).code,403)
   assert.equal((await ask({action:'consent',allow:true})).code,400)
   assert.equal((await ask({action:'consent',allow:true,confirm:'MANUAL_MEMORY_CONSENT'})).code,200)
   const saved=(await ask({action:'put',text:'虚构事实：喜欢香草布丁'})).body
   assert.ok(saved.id)
   assert.equal(saved.revision,1)
   assert.equal((await ask({action:'read',id:saved.id})).body.fact.text,'虚构事实：喜欢香草布丁\n')
   assert.equal((await ask({action:'put',id:saved.id,text:'new text',expectedRevision:0})).code,409)
   const revise=(await ask({action:'put',id:saved.id,text:'虚构事实：喜欢草莓布丁',expectedRevision:1})).body
   assert.equal(revise.revision,2)
   assert.equal((await ask({action:'export'})).body.facts.length,1)
   assert.equal((await ask({action:'remove',id:saved.id,expectedRevision:2})).code,400)
   assert.equal((await ask({action:'remove',id:saved.id,expectedRevision:2,confirm:'DELETE_THIS_FACT'})).code,200)
   assert.equal((await ask({action:'read',id:saved.id})).code,400)
   assert.equal((await ask({action:'list'})).body.consent.auto_extraction,false)
   assert.equal(f.created,0,'a memory management call must not start an Agent/model')
 }finally{f.close()}
})

test('P1 discovers native DSH provider catalog and session-switches Pro without LLM',async()=>{
  const original=process.env.DSH_LIVE_P1_VISIBLE_MODELS
  // Old operator-scoped allowlist must not hide the real catalog.
  process.env.DSH_LIVE_P1_VISIBLE_MODELS='deterministic-local'
  const f=fixture()
  try{
    const models=await f.call('/models',{method:'POST',body:{protocolVersion:1}})
    assert.equal(models.code,200)
    assert.deepEqual(models.body.models,[
      {id:'deterministic-local',name:'Fixture Flash'},
      {id:'deterministic-pro',name:'Fixture Pro'}])
    assert.equal(models.body.source,'dsh-native-provider-catalog-no-call')
    assert.equal(f.created,0)
    assert.equal((await f.call('/bind',{method:'POST',bearer:'wrong',
      body:{protocolVersion:1,conversation_id:'p1_aabbccddeeff0011'}})).code,401)
    const bind=await f.call('/bind',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_aabbccddeeff0011'}})
    assert.equal(bind.code,200)
    assert.equal(bind.body.selected.model,'deterministic-local')
    assert.equal(f.created,1)
    assert.equal(f.agents[0].agent.followed.length,0)
    const switched=await f.call('/model',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_aabbccddeeff0011',
      model:'deterministic-pro'}})
    assert.equal(switched.code,200)
    assert.equal(switched.body.selected.model,'deterministic-pro')
    const viewed=await f.call('/session',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_aabbccddeeff0011'}})
    assert.equal(viewed.body.selected.model,'deterministic-pro')
    assert.equal(f.agents[0].agent.followed.length,0)
  }finally{
    f.close()
    if(original===undefined)delete process.env.DSH_LIVE_P1_VISIBLE_MODELS
    else process.env.DSH_LIVE_P1_VISIBLE_MODELS=original
  }
})

test('native model catalog fails closed on unavailable or wrong-provider catalogs',async()=>{
  const missing=fixture({modelCatalogFailure:true})
  try{
    const r=await missing.call('/models',{method:'POST',body:{protocolVersion:1}})
    assert.equal(r.code,503)
    assert.equal(r.body.error,'model_catalog_unavailable')
    assert.equal(missing.created,0)
  }finally{missing.close()}
  const alien=fixture({nativeModels:[
    {provider:'another-provider',id:'deterministic-pro',name:'Alien'},
    {provider:'offline-test',id:'deterministic-local',name:'Fixture Flash'},
    {provider:'offline-test',id:'invalid-model',name:'Unavailable'}
  ]})
  try{
    const r=await alien.call('/models',{method:'POST',body:{protocolVersion:1}})
    assert.equal(r.code,200)
    assert.deepEqual(r.body.models.map(x=>x.id),['deterministic-local'])
  }finally{alien.close()}
})

test('explicit end retires an idle in-memory conversation without claiming native file deletion',async()=>{
 const f=fixture()
 try{
   const conv='p1_deadbeefdeadbeef'
   const bind=await f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:conv}})
   assert.equal(bind.code,200)
   const result=await f.call('/end',{method:'POST',body:{protocolVersion:1,conversation_id:conv}})
   assert.equal(result.code,200)
   assert.equal(result.body.session_ended,true)
   assert.equal(result.body.native_artifacts,'pending_cleanup')
   assert.equal((await f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:conv}})).code,410)
   assert.equal((await f.call('/submit',{method:'POST',body:{
     protocolVersion:1,turn_id:'turn_closed_0001',conversation_id:conv,prompt:'repeat'}})).code,410)
 }finally{f.close()}
})

// C2-S4c-D: project already-verified Bridge task facts only; no new Agent or device side effects.
test('companion facts stay disabled and protected without an explicit isolated opt-in', async () => {
  const f = fixture()
  try {
    const task = (await f.call('/submit', {method:'POST', body:input()})).body
    const body = {...query(task), session_id:task.session_id}
    assert.equal((await f.call('/companion-facts', {method:'POST',body})).code, 503)
    assert.equal((await f.call('/companion-facts', {method:'POST',body,bearer:''})).code,401)
    assert.equal((await f.call('/companion-facts', {method:'POST',body,ip:'192.168.1.3'})).code,403)
  } finally { f.close() }
})

test('companion facts bind exact task and session, omit private prompt, text, tool args and keys', async () => {
  const f=fixture({companionFacts:true})
  try {
    const task=(await f.call('/submit',{method:'POST',body:input('turn_scope_0001','PRIVATE_MARKER_PROMPT')})).body
    const body={...query(task),session_id:task.session_id}
    assert.equal((await f.call('/companion-facts',{method:'GET',body})).code,405)
    assert.equal((await f.call('/companion-facts',{method:'POST',body:{...body,secret:'x'}})).code,400)
    assert.equal((await f.call('/companion-facts',{method:'POST',body:{...body,session_id:'other-session'}})).code,409)
    assert.equal((await f.call('/companion-facts',{method:'POST',body:{...body,task_id:'unknown'}})).code,404)
    const r=await f.call('/companion-facts',{method:'POST',body})
    assert.equal(r.code,200)
    assert.deepEqual(r.body,{ok:true,protocolVersion:1,revision:0,turn_id:task.turn_id,session_id:task.session_id,
      task_phase:'thinking',tool_active_count:0,tool_failed:false,approval_pending:false,
      outcome:null,assistant_ready_for_tts:false})
    assert.doesNotMatch(JSON.stringify(r.body),/PRIVATE_MARKER_PROMPT|DEEPSEEK_API_KEY|token|arguments|toolName|text/i)
  } finally { f.close() }
})

test('companion facts keep independent two tool calls and scope same callId to each session', async () => {
  const f=fixture({companionFacts:true})
  try {
    const first=(await f.call('/submit',{method:'POST',body:input('turn_scope_0002')})).body
    const second=(await f.call('/submit',{method:'POST',body:input('turn_scope_0003')})).body
    const a=f.agents[0].agent,b=f.agents[1].agent
    const queryFact=async t=>(await f.call('/companion-facts',{method:'POST',body:{...query(t),session_id:t.session_id}})).body
    for(const agent of [a,b]){
      await f.runHooks('session/event',agent.session,{type:'tool/call',data:{callId:'same-id',name:'read',arguments:'PRIVATE_ARGS'}})
    }
    await f.runHooks('session/event',a.session,{type:'tool/call',data:{callId:'second-id',name:'write'}})
    assert.equal((await queryFact(first)).tool_active_count,2)
    assert.equal((await queryFact(second)).tool_active_count,1)
    await f.runHooks('session/event',a.session,{type:'tool/result',data:{message:{role:'tool',source:{kind:'tool',callId:'same-id'},toolCallId:'same-id',isError:false}}})
    assert.equal((await queryFact(first)).task_phase,'working')
    assert.equal((await queryFact(first)).tool_active_count,1)
    assert.equal((await queryFact(second)).tool_active_count,1)
    await f.runHooks('session/event',a.session,{type:'tool/result',data:{message:{role:'tool',source:{kind:'tool',callId:'second-id'},toolCallId:'second-id',isError:false}}})
    assert.equal((await queryFact(first)).tool_active_count,0)
    assert.equal((await queryFact(first)).task_phase,'thinking')
  } finally {f.close()}
})

test('companion facts follow approval and validated V4 tool error; text never means audio is playing',async()=>{
  const f=fixture({companionFacts:true})
  try{
    const task=(await f.call('/submit',{method:'POST',body:input('turn_scope_0004')})).body
    const a=f.agents[0].agent
    const q=async()=> (await f.call('/companion-facts',{method:'POST',body:{...query(task),session_id:task.session_id}})).body
    await f.runHooks('session/event',a.session,{type:'tool/call',data:{callId:'call-fail',name:'shell'}})
    await f.runHooks('session/event',a.session,{type:'tool/result',data:{message:{role:'tool',source:{kind:'plugin',callId:'call-fail'},toolCallId:'call-fail',isError:true}}})
    assert.equal((await q()).tool_active_count,1)
    assert.equal((await q()).tool_failed,false)
    await f.runHooks('session/event',a.session,{type:'approval/asked',data:{id:'approve-one',toolName:'shell'}})
    assert.equal((await q()).task_phase,'approval_pending')
    await f.runHooks('session/event',a.session,{type:'approval/decided',data:{id:'approve-one',outcome:'allowed-once'}})
    assert.equal((await q()).approval_pending,false)
    await f.runHooks('session/event',a.session,{type:'tool/result',data:{message:{role:'tool',source:{kind:'tool',callId:'call-fail'},toolCallId:'call-fail',isError:true}}})
    assert.equal((await q()).tool_failed,true)
    await f.runHooks('session/event',a.session,{type:'assistant/message',data:{message:{content:[{type:'text',text:'已经完成 PRIVATE_RESULT_TEXT'}]}}})
    assert.equal((await q()).assistant_ready_for_tts,false)
    await f.runHooks('session/event',a.session,{type:'turn/end',data:{reason:{kind:'completed'}}})
    await f.runHooks('agent/status',{agent:a,status:'idle'})
    assert.equal((await q()).outcome,'failed')
    assert.equal((await q()).assistant_ready_for_tts,false)
  } finally { f.close() }
})

test('only final answered/completed text exposes ready-for-TTS; abort and blocked never do',async()=>{
  for(const reason of ['completed','aborted','blocked']){
    const f=fixture({companionFacts:true})
    try{
      const task=(await f.call('/submit',{method:'POST',body:input()})).body
      const a=f.agents[0].agent
      const q=async()=> (await f.call('/companion-facts',{method:'POST',body:{...query(task),session_id:task.session_id}})).body
      await f.runHooks('session/event',a.session,{type:'assistant/message',data:{message:{content:[{type:'text',text:'private result'}]}}})
      assert.equal((await q()).assistant_ready_for_tts,false)
      await f.runHooks('session/event',a.session,{type:'turn/end',data:{reason:{kind:reason}}})
      await f.runHooks('agent/status',{agent:a,status:'idle'})
      const fact=await q()
      assert.equal(fact.assistant_ready_for_tts,reason==='completed')
      assert.equal(fact.outcome,reason==='completed'?'answered':reason==='aborted'?'cancelled':'failed')
      assert.doesNotMatch(JSON.stringify(fact),/private result|speaking|playback_started/)
    }finally { f.close() }
  }
})

test('companion facts do not revive ended conversation snapshots or the persisted ledger', async()=>{
  const f=fixture({companionFacts:true})
  try{
    const conversation_id='c2_visual_owner_01'
    const submit=await f.call('/submit',{method:'POST',body:{...input('c2_visual_turn_01'),conversation_id}})
    assert.equal(submit.code,202)
    const task=submit.body
    const a=f.agents[0].agent
    await f.runHooks('session/event',a.session,{type:'assistant/message',data:{message:{content:[{type:'text',text:'finished'}]}}})
    await f.runHooks('session/event',a.session,{type:'turn/end',data:{reason:{kind:'completed'}}})
    await f.runHooks('agent/status',{agent:a,status:'idle'})
    const before=await f.call('/companion-facts',{method:'POST',body:{...query(task),session_id:task.session_id}})
    assert.equal(before.code,200)
    assert.equal(before.body.assistant_ready_for_tts,true)
    const ended=await f.call('/end',{method:'POST',body:{protocolVersion:1,conversation_id}})
    assert.equal(ended.code,200)
    const after=await f.call('/companion-facts',{method:'POST',body:{...query(task),session_id:task.session_id}})
    assert.equal(after.code,404)
    assert.equal(after.body.error,'unknown_task')
  }finally{f.close()}
})

test('companion facts distinguish native cancellation request from confirmed aborted turn',async()=>{
  const f=fixture({companionFacts:true})
  try{
    const task=(await f.call('/submit',{method:'POST',body:input('c2_cancel_turn_01')})).body
    const a=f.agents[0].agent
    const body={...query(task),session_id:task.session_id}
    const fact=async()=> (await f.call('/companion-facts',{method:'POST',body})).body
    const cancel=await f.call('/cancel',{method:'POST',body:query(task)})
    assert.equal(cancel.code,202)
    assert.equal((await fact()).task_phase,'cancel_requested')
    assert.equal((await fact()).outcome,null)
    assert.equal((await fact()).assistant_ready_for_tts,false)
    await f.runHooks('session/event',a.session,{type:'turn/end',data:{reason:{kind:'aborted'}}})
    await f.runHooks('agent/status',{agent:a,status:'idle'})
    assert.equal((await fact()).outcome,'cancelled')
    assert.equal((await fact()).assistant_ready_for_tts,false)
  }finally { f.close() }
})

test('companion facts revision rejects stale ordered snapshots at the Mac adapter boundary',async()=>{
  const f=fixture({companionFacts:true})
  try {
    const task=(await f.call('/submit',{method:'POST',body:input('turn_version_01')})).body
    const a=f.agents[0].agent
    const queryFacts=async()=> (await f.call('/companion-facts',{method:'POST',
      body:{...query(task),session_id:task.session_id}})).body
    const versions=[]
    versions.push((await queryFacts()).revision)
    for(const event of [
      {type:'tool/call',data:{callId:'A',name:'read'}},
      {type:'approval/asked',data:{id:'rev-check',toolName:'read'}},
      {type:'approval/decided',data:{id:'rev-check',outcome:'allowed-once'}},
      {type:'tool/result',data:{message:{role:'tool',source:{kind:'tool',callId:'A'},toolCallId:'A',isError:false}}},
      {type:'assistant/message',data:{message:{content:[{type:'text',text:'done'}]}}},
      {type:'turn/end',data:{reason:{kind:'completed'}}},
    ]) {
      await f.runHooks('session/event',a.session,event)
      versions.push((await queryFacts()).revision)
    }
    await f.runHooks('agent/status',{agent:a,status:'idle'})
    versions.push((await queryFacts()).revision)
    assert.deepEqual(versions,[0,1,2,3,4,5,6,7])
  }finally {f.close()}
})

test('aborting during approval produces settled cancelled facts, never pending approval',async()=>{
  const f=fixture({companionFacts:true})
  try{
    const task=(await f.call('/submit',{method:'POST',body:input('turn_approval_abort_01')})).body
    const agent=f.agents[0].agent
    await f.runHooks('session/event',agent.session,{type:'approval/asked',data:{id:'abort-during-approval',toolName:'test'}})
    await f.runHooks('session/event',agent.session,{type:'turn/end',data:{reason:{kind:'aborted'}}})
    await f.runHooks('agent/status',{agent,status:'idle'})
    const facts=(await f.call('/companion-facts',{method:'POST',
      body:{...query(task),session_id:task.session_id}})).body
    assert.equal(facts.task_phase,'settled')
    assert.equal(facts.outcome,'cancelled')
    assert.equal(facts.approval_pending,false)
    assert.equal(facts.assistant_ready_for_tts,false)
  }finally{f.close()}
})

test('E3 short native tool and approval transitions replay even after final status',async()=>{
  const f=fixture({companionFacts:true})
  try{
    const task=(await f.call('/submit',{method:'POST',body:input('e3_fast_turn_01','PRIVATE_FAST_PROMPT')})).body
    const agent=f.agents[0].agent
    const read=async revision=>await f.call('/companion-facts',{method:'POST',body:{
      ...query(task),session_id:task.session_id,after_revision:revision}})
    const first=await read(-1)
    assert.equal(first.code,200)
    assert.deepEqual(first.body.changes.map(x=>x.revision),[0])
    await f.runHooks('session/event',agent.session,{type:'tool/call',data:{callId:'fast',name:'echo',arguments:'SECRET_TOOL_ARGUMENT'}})
    await f.runHooks('session/event',agent.session,{type:'approval/asked',data:{id:'SECRET_APPROVAL_ID',toolName:'echo'}})
    await f.runHooks('session/event',agent.session,{type:'approval/decided',data:{id:'SECRET_APPROVAL_ID',outcome:'allowed-once'}})
    await f.runHooks('session/event',agent.session,{type:'tool/result',data:{message:{
      role:'tool',source:{kind:'tool',callId:'fast'},toolCallId:'fast',isError:false}}})
    await f.runHooks('session/event',agent.session,{type:'assistant/message',data:{message:{
      content:[{type:'text',text:'PRIVATE_ASSISTANT_TEXT'}]}}})
    await f.runHooks('session/event',agent.session,{type:'turn/end',data:{reason:{kind:'completed'}}})
    await f.runHooks('agent/status',{agent,status:'idle'})
    const final=await read(0)
    assert.equal(final.code,200)
    assert.deepEqual(final.body.changes.map(x=>x.revision),[1,2,3,4,5,6,7])
    assert.deepEqual(final.body.changes.map(x=>x.task_phase),
      ['working','approval_pending','working','thinking','thinking','thinking','settled'])
    assert.equal(final.body.changes.at(-1).outcome,'tool_verified')
    assert.equal((await read(7)).body.changes.length,0)
    assert.doesNotMatch(JSON.stringify(final.body),
      /PRIVATE_FAST_PROMPT|SECRET_TOOL_ARGUMENT|SECRET_APPROVAL_ID|PRIVATE_ASSISTANT_TEXT|token|speaking/i)
    assert.equal((await read(8)).code,409)
  } finally{f.close()}
})

test('E3 bounded fact history fails closed after overflow, disabled and cross-session still blocked',async()=>{
  const f=fixture({companionFacts:true})
  try{
    const task=(await f.call('/submit',{method:'POST',body:input('e3_history_gap_01')})).body
    const a=f.agents[0].agent
    const get=async revision=>f.call('/companion-facts',{method:'POST',
      body:{...query(task),session_id:task.session_id,after_revision:revision}})
    for(let i=0;i<70;i++){
      await f.runHooks('session/event',a.session,{type:'tool/call',
        data:{callId:'job-'+i,name:'test'}})
    }
    const stale=await get(-1)
    assert.equal(stale.code,409)
    assert.equal(stale.body.error,'visual_history_gap')
    const latest=await get(6)
    assert.equal(latest.code,200)
    assert.equal(latest.body.changes.length,64)
    assert.equal(latest.body.changes[0].revision,7)
    assert.equal(latest.body.changes.at(-1).revision,70)
    assert.equal((await f.call('/companion-facts',{method:'POST',
      body:{...query(task),session_id:'foreign-session',after_revision:70}})).code,409)
    assert.equal((await f.call('/companion-facts',{method:'POST',
      body:{...query(task),session_id:task.session_id,after_revision:1.5}})).code,400)
  }finally{f.close()}
})

test('E3 native concurrent approvals remain pending by id; rejection cannot verify tool execution',async()=>{
  const f=fixture({companionFacts:true})
  try{
    const task=(await f.call('/submit',{method:'POST',body:input('e3_two_approvals_01')})).body
    const a=f.agents[0].agent
    const snapshot=async()=> (await f.call('/companion-facts',{method:'POST',
      body:{...query(task),session_id:task.session_id}})).body
    await f.runHooks('session/event',a.session,{type:'tool/call',
      data:{callId:'safe-tool',name:'echo'}})
    for(const id of ['approval-A','approval-B'])
      await f.runHooks('session/event',a.session,{type:'approval/asked',data:{id,toolName:'echo'}})
    await f.runHooks('session/event',a.session,{type:'approval/decided',
      data:{id:'approval-A',outcome:'allowed-once'}})
    assert.equal((await snapshot()).approval_pending,true)
    await f.runHooks('session/event',a.session,{type:'approval/decided',
      data:{id:'approval-B',outcome:'rejected'}})
    assert.equal((await snapshot()).approval_pending,false)
    await f.runHooks('session/event',a.session,{type:'tool/result',data:{message:{
      role:'tool',source:{kind:'tool',callId:'safe-tool'},toolCallId:'safe-tool',isError:false}}})
    await f.runHooks('session/event',a.session,{type:'assistant/message',
      data:{message:{content:[{type:'text',text:'private fake completion'}]}}})
    await f.runHooks('session/event',a.session,{type:'turn/end',data:{reason:{kind:'completed'}}})
    await f.runHooks('agent/status',{agent:a,status:'idle'})
    const result=(await f.call('/result',{method:'POST',body:query(task)})).body
    assert.equal(result.status,'failed')
    assert.equal(result.failure,'native_approval_rejected')
    assert.equal(result.result,null)
    assert.equal((await snapshot()).assistant_ready_for_tts,false)
  }finally{f.close()}
})

test('native approval rejection and cancellation remain non-executed but distinguishable',async()=>{
  for (const outcome of ['rejected','cancelled','unavailable']) {
    const f=fixture({companionFacts:true})
    try {
      const task=(await f.call('/submit',{method:'POST',
        body:input('e3_native_choice_'+outcome)})).body
      const a=f.agents[0].agent
      await f.runHooks('session/event',a.session,{type:'tool/call',
        data:{callId:'probe',name:'dsh_live_approval_probe'}})
      await f.runHooks('session/event',a.session,{type:'approval/asked',
        data:{id:'native-asked',toolName:'dsh_live_approval_probe'}})
      await f.runHooks('session/event',a.session,{type:'approval/decided',
        data:{id:'native-asked',outcome}})
      await f.runHooks('session/event',a.session,{type:'tool/result',data:{
        message:{role:'tool',toolCallId:'probe',isError:true,
          source:{kind:'tool',callId:'probe'}}}})
      await f.runHooks('session/event',a.session,{type:'turn/end',
        data:{reason:{kind:'completed'}}})
      await f.runHooks('agent/status',{agent:a,status:'idle'})
      const result=(await f.call('/result',{method:'POST',body:query(task)})).body
      assert.equal(result.status,'failed')
      assert.equal(result.result,null)
      assert.equal(result.failure,outcome==='unavailable'
        ? 'native_approval_not_granted' : 'native_approval_'+outcome)
      const facts=(await f.call('/companion-facts',{method:'POST',
        body:{...query(task),session_id:task.session_id}})).body
      assert.equal(facts.assistant_ready_for_tts,false)
      assert.equal(facts.tool_failed,true)
    }finally{f.close()}
  }
})

test('E3 unmatched approval decision fails closed instead of clearing another request',async()=>{
  const f=fixture({companionFacts:true})
  try{
    const task=(await f.call('/submit',{method:'POST',body:input('e3_unmatched_approval')})).body
    const a=f.agents[0].agent
    await f.runHooks('session/event',a.session,{type:'approval/asked',
      data:{id:'real-pending',toolName:'echo'}})
    await f.runHooks('session/event',a.session,{type:'approval/decided',
      data:{id:'foreign-approval',outcome:'allowed-once'}})
    const result=(await f.call('/result',{method:'POST',body:query(task)})).body
    assert.equal(result.status,'failed')
    assert.equal(result.failure,'invalid_native_approval')
  }finally{f.close()}
})


test('native official web_search opt-in admits only search and caps attempts',async()=>{
  const original = process.env.DSH_LIVE_ENABLE_WEB_SEARCH
  const readonlyOriginal = process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
  process.env.DSH_LIVE_ENABLE_WEB_SEARCH='1'
  process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL='1'
  const f=fixture()
  try {
    const task=(await f.call('/submit',{method:'POST',
      body:input('native_web_opt_in_0001')})).body
    assert.equal(task.status,'accepted')
    const captures={}
    f.agents[0].options.setup({on(){return ()=>{}},tools:{
      restrict(value){captures.restrict=value},
      guard(fn){captures.guard=fn},
      register(tool){(captures.local??=[]).push(tool.name)},
    }})
    assert.deepEqual(captures.restrict,{allow:['web_search']})
    assert.deepEqual(captures.local,['dsh_live_read_volume'])
    assert.equal(captures.guard({name:'web_search',callId:'a'}),undefined)
    assert.equal(captures.guard({name:'web_search',callId:'a'}),undefined)
    assert.equal(captures.guard({name:'web_search',callId:'b'}),undefined)
    assert.match(captures.guard({name:'web_search',callId:'c'}),/budget_exhausted/)
    assert.match(captures.guard({name:'web_search'}),/missing_receipt/)
    assert.match(captures.guard({name:'web_fetch',callId:'d'}),/readonly_scope/)
    assert.match(captures.guard({name:'bash',callId:'e'}),/readonly_scope/)
    assert.equal(captures.guard({name:'dsh_live_read_volume'}),undefined)
  } finally {
    f.close()
    if(original===undefined)delete process.env.DSH_LIVE_ENABLE_WEB_SEARCH
    else process.env.DSH_LIVE_ENABLE_WEB_SEARCH=original
    if(readonlyOriginal===undefined)delete process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
    else process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL=readonlyOriginal
  }
})

test('native official search cannot bypass required read-only scope',async()=>{
  const original=process.env.DSH_LIVE_ENABLE_WEB_SEARCH
  const readonlyOriginal=process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
  process.env.DSH_LIVE_ENABLE_WEB_SEARCH='1'
  delete process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
  const f=fixture()
  try {
    const result=(await f.call('/submit',{method:'POST',
      body:input('native_web_requires_policy_01')})).body
    assert.equal(result.status,'failed')
  }finally{
    f.close()
    if(original===undefined)delete process.env.DSH_LIVE_ENABLE_WEB_SEARCH
    else process.env.DSH_LIVE_ENABLE_WEB_SEARCH=original
    if(readonlyOriginal===undefined)delete process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
    else process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL=readonlyOriginal
  }
})

test('E3b companion approval stays disabled by default and never grants',async()=>{
  const f=fixture()
  try{
    const pending=await f.call('/approval/pending',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_'+'a'.repeat(32)}})
    assert.equal(pending.code,503)
    const native=await f.askApproval({agent:{id:'nobody'},toolName:'dsh_live_approval_probe'})
    assert.equal(native,'unavailable')
  }finally{f.close()}
})

test('E3b scoped no-I/O approval only via same session task and single-use receipt',async()=>{
  const f=fixture({companionApproval:true})
  try{
    const conversation='p1_'+'b'.repeat(32)
    const submitted=await f.call('/submit',{method:'POST',body:{
      ...input('e3b_ui_safe_0001','OFFLINE_APPROVAL_PROBE'),conversation_id:conversation}})
    assert.equal(submitted.code,202)
    const task=submitted.body
    const agent=f.agents[0].agent
    await f.runHooks('session/event',agent.session,{
      type:'approval/asked',data:{id:'official-id',toolName:'dsh_live_approval_probe'}})
    const pendingPromise=f.askApproval({agent,toolName:'dsh_live_approval_probe'})
    const found=await f.call('/approval/pending',{method:'POST',
      body:{protocolVersion:1,conversation_id:conversation}})
    assert.equal(found.code,200)
    assert.equal(found.body.pending.tool,'dsh_live_approval_probe')
    assert.match(found.body.pending.description,/内存/)
    assert(!JSON.stringify(found.body).includes('OFFLINE_APPROVAL_PROBE'))
    const {task_id,request_id}=found.body.pending
    const wrong=await f.call('/approval/decide',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_'+'c'.repeat(32),
      task_id,request_id,decision:'allowed-once'}})
    assert.equal(wrong.code,409)
    const changed=await f.call('/approval/decide',{method:'POST',body:{
      protocolVersion:1,conversation_id:conversation,task_id,
      request_id:'00000000-0000-0000-0000-000000000001',decision:'allowed-once'}})
    assert.equal(changed.code,409)
    const declined=await f.call('/approval/decide',{method:'POST',body:{
      protocolVersion:1,conversation_id:conversation,task_id,request_id,decision:'rejected'}})
    assert.equal(declined.code,202)
    assert.equal(declined.body.submitted,true)
    assert.equal(await pendingPromise,'rejected')
    const repeat=await f.call('/approval/decide',{method:'POST',body:{
      protocolVersion:1,conversation_id:conversation,task_id,request_id,decision:'allowed-once'}})
    assert.equal(repeat.code,409)
    const after=await f.call('/approval/pending',{method:'POST',
      body:{protocolVersion:1,conversation_id:conversation}})
    assert.equal(after.body.pending,null)
  }finally{f.close()}
})

test('E3b cancelled approval is not allowed and unsupported tools never reach companion',async()=>{
  const f=fixture({companionApproval:true})
  try{
    const unknown=await f.askApproval({agent:{id:'abc'},toolName:'dsh_live_read_volume'})
    assert.equal(unknown,'unavailable')
    const conversation='p1_'+'d'.repeat(32)
    await f.call('/submit',{method:'POST',
      body:{...input('e3b_ui_cancel_01','OFFLINE_APPROVAL_PROBE'),conversation_id:conversation}})
    const agent=f.agents[0].agent
    await f.runHooks('session/event',agent.session,{type:'approval/asked',
      data:{id:'official-cancel',toolName:'dsh_live_approval_probe'}})
    const answer=f.askApproval({agent,toolName:'dsh_live_approval_probe'})
    const pending=(await f.call('/approval/pending',{method:'POST',
      body:{protocolVersion:1,conversation_id:conversation}})).body.pending
    const rejected=await f.call('/approval/decide',{method:'POST',body:{
      protocolVersion:1,conversation_id:conversation,task_id:pending.task_id,
      request_id:pending.request_id,decision:'cancelled'}})
    assert.equal(rejected.code,202)
    assert.equal(await answer,'cancelled')
    const noForeign=await f.call('/approval/decide',{method:'POST',
      bearer:'incorrect',body:{protocolVersion:1,conversation_id:conversation,
      task_id:pending.task_id,request_id:pending.request_id,decision:'allowed-once'}})
    assert.equal(noForeign.code,401)
  }finally{f.close()}
})

test('E3b Agent-scoped safe answerer precedes the built-in Web forwarder',async()=>{
  const f=fixture({companionApproval:true,priorApprovalForwarder:true})
  try{
    const conversation='p1_'+'e'.repeat(32)
    const admitted=await f.call('/submit',{method:'POST',body:{
      ...input('e3b_precedence_probe_001','OFFLINE_APPROVAL_PROBE'),
      conversation_id:conversation,
    }})
    assert.equal(admitted.code,202)
    const agent=f.agents[0].agent
    await f.runHooks('session/event',agent.session,{
      type:'approval/asked',
      data:{id:'official-precedence',toolName:'dsh_live_approval_probe'},
    })
    const decision=f.askApproval({agent,toolName:'dsh_live_approval_probe'})
    const reply=await f.call('/approval/pending',{method:'POST',body:{
      protocolVersion:1,conversation_id:conversation,
    }})
    assert.equal(reply.code,200)
    assert.equal(reply.body.pending?.tool,'dsh_live_approval_probe')
    const pending=reply.body.pending
    const submitted=await f.call('/approval/decide',{method:'POST',body:{
      protocolVersion:1,conversation_id:conversation,
      task_id:pending.task_id,request_id:pending.request_id,
      decision:'cancelled',
    }})
    assert.equal(submitted.code,202)
    assert.equal(await decision,'cancelled')
  }finally{f.close()}
})

test('H5 mounts the official Web-only preset before querying Agent tools, keeping search opt-in',async()=>{
  const previous=process.env.DSH_LIVE_TOOL_MODE
  process.env.DSH_LIVE_TOOL_MODE='native'
  const f=fixture({webPresetFixture:true,webPresetConfigured:true,nativeToolCatalog:[]})
  try{
    const id='p1_'+'1'.repeat(32)
    const call=async(body)=>f.call('/bind',{method:'POST',body:{
      protocolVersion:1,conversation_id:id,...body}})
    const bind=await call()
    assert.equal(bind.code,200)
    assert.equal(bind.body.search_supported,true)
    assert.equal(bind.body.search_enabled,false)
    assert.equal(f.presetMounts.length,1)
    assert.equal(f.presetMounts[0].id,'deepseek-live-web')
    assert.deepEqual(f.agents[0].scopedMasks[0].filter,{deny:['web_search','web_fetch']})
    assert.equal((await f.call('/search',{method:'POST',body:{
      protocolVersion:1,conversation_id:id,enabled:true}})).body.enabled,true)
    assert.equal(f.agents[0].scopedMasks[0].active,false)
    assert.equal(f.created,1)
    assert.equal(f.agents[0].agent.followed.length,0)
  }finally {
    f.close()
    if(previous===undefined) delete process.env.DSH_LIVE_TOOL_MODE
    else process.env.DSH_LIVE_TOOL_MODE=previous
  }
})

test('H5 rejected Web-only preset mount denies the binding before any model turn',async()=>{
  const previous=process.env.DSH_LIVE_TOOL_MODE
  process.env.DSH_LIVE_TOOL_MODE='native'
  const f=fixture({webPresetFixture:true,webPresetConfigured:true,webPresetFailure:true})
  try{
    const response=await f.call('/bind',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_'+'4'.repeat(32)}})
    assert.equal(response.code,503)
    assert.equal(response.body.error,'session_bind_failed')
    assert.equal(f.presetMounts.length,1)
    assert.equal(f.agents.length,0)
  }finally {
    f.close()
    if(previous===undefined) delete process.env.DSH_LIVE_TOOL_MODE
    else process.env.DSH_LIVE_TOOL_MODE=previous
  }
})

test('C2-S4d native mode inherits all installed Harness tools and toggles only web tools per Agent',async()=>{
  const original=process.env.DSH_LIVE_TOOL_MODE
  const oldReadonly=process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
  const oldWeb=process.env.DSH_LIVE_ENABLE_WEB_SEARCH
  process.env.DSH_LIVE_TOOL_MODE='native'
  delete process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
  delete process.env.DSH_LIVE_ENABLE_WEB_SEARCH
  const f=fixture({nativeToolCatalog:['web_search','web_fetch','bash','another-plugin']})
  try{
    const a='p1_'+'a'.repeat(32),b='p1_'+'b'.repeat(32)
    const bind=x=>f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:x}})
    const query=x=>f.call('/search',{method:'POST',body:{protocolVersion:1,conversation_id:x}})
    const set=(x,value)=>f.call('/search',{method:'POST',
      body:{protocolVersion:1,conversation_id:x,enabled:value}})
    const first=(await bind(a)).body
    assert.equal(first.search_supported,true)
    assert.equal(first.search_enabled,false)
    assert.deepEqual(f.agents[0].scopedMasks[0].filter,{deny:['web_search','web_fetch']})
    assert.equal((await set(a,true)).body.enabled,true)
    assert.equal(f.agents[0].scopedMasks[0].active,false)
    assert.equal((await query(a)).body.enabled,true)
    assert.equal((await bind(b)).body.search_enabled,false)
    assert.equal(f.agents[1].scopedMasks[0].active,true)
    assert.equal((await set(a,false)).body.enabled,false)
    assert.equal(f.agents[0].scopedMasks.at(-1).active,true)
    assert.equal((await set(a,false)).code,200)
    assert.equal((await set(a,'yes')).code,400)
    assert.equal((await query('p1_'+'c'.repeat(32))).code,404)
    assert.equal((await query(a)).body.enabled,false)
    assert.equal((await set(a,true)).body.enabled,true)
    const task=(await f.call('/submit',{method:'POST',
      body:{...input('native_search_busy_01'),conversation_id:a}})).body
    assert.equal(task.status,'accepted')
    assert.equal((await set(a,false)).code,409)
  }finally{
    f.close()
    if(original===undefined)delete process.env.DSH_LIVE_TOOL_MODE
    else process.env.DSH_LIVE_TOOL_MODE=original
    if(oldReadonly===undefined)delete process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
    else process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL=oldReadonly
    if(oldWeb===undefined)delete process.env.DSH_LIVE_ENABLE_WEB_SEARCH
    else process.env.DSH_LIVE_ENABLE_WEB_SEARCH=oldWeb
  }
})

test('C2-S4d native mode cannot quietly bypass an isolated read-only profile',async()=>{
  const oldMode=process.env.DSH_LIVE_TOOL_MODE
  const oldReadonly=process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
  process.env.DSH_LIVE_TOOL_MODE='native'
  process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL='1'
  const f=fixture({nativeToolCatalog:['web_search','bash']})
  try{
    const got=await f.call('/bind',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_'+'a'.repeat(32)}})
    assert.equal(got.code,503)
    assert.equal((await f.call('/search',{method:'POST',body:{
      protocolVersion:1,conversation_id:'p1_'+'a'.repeat(32),enabled:true}})).code,404)
  }finally{
    f.close()
    if(oldMode===undefined)delete process.env.DSH_LIVE_TOOL_MODE
    else process.env.DSH_LIVE_TOOL_MODE=oldMode
    if(oldReadonly===undefined)delete process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL
    else process.env.DSH_LIVE_ENABLE_MAC_READONLY_TOOL=oldReadonly
  }
})

test('R218 Flash speech binding is a distinct, no-tools, fixed-model scope',async()=>{
  const f=fixture({defaultModel:{provider:'offline-test',model:'deterministic-pro'},
    nativeToolCatalog:['shell','web_search']})
  const id='speech_aabbccdd11223344556677889900aabb'
  try{
    const absent=await f.call('/speech-bind',{method:'POST',body:{protocolVersion:1,conversation_id:id},bearer:''})
    assert.equal(absent.code,401)
    const cap=await f.call('/speech-capabilities',{method:'POST',body:{protocolVersion:1}})
    assert.equal(cap.body.tools_denied,true)
    assert.equal(f.created,0)
    const bind=await f.call('/speech-bind',{method:'POST',body:{protocolVersion:1,conversation_id:id}})
    assert.equal(bind.code,200)
    assert.equal(bind.body.selected.model,'deepseek-flash')
    assert.equal(bind.body.speech_only,true)
    assert.equal(bind.body.tools_denied,true)
    assert.equal(f.agents[0].options.agentOptions.model,'deepseek-flash')
    assert.equal(f.agents[0].options.agentOptions.maxTokens,320)
    assert.deepEqual(f.agents[0].scopedMasks[0].filter,{allow:[]})
    assert.equal(f.agents[0].scopedGuards.length,1)
    for(const name of ['shell','web_search','late_added_scoped_tool']) {
      assert.equal(f.agents[0].scopedGuards[0]({name}),
                   'speech_only_tool_forbidden','monotonic hard denial: '+name)
    }
    assert.equal((await f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:id}})).code,403)
    assert.equal((await f.call('/model',{method:'POST',body:{protocolVersion:1,conversation_id:id,model:'deterministic-pro'}})).code,403)
    const prompt='仅生成供Qwen朗读的短文本'
    const started=await f.call('/submit',{method:'POST',body:{protocolVersion:1,conversation_id:id,turn_id:'test_r218_speechonly',prompt}})
    assert.equal(started.code,202)
    assert.equal(f.agents[0].agent.followed.length,1)
    // A normal conversation still gets the default model, not the speech
    // model -- no Host-wide model selection or callback took place.
    const normal=await f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:'normal_conversation_test_999'}})
    assert.equal(normal.code,200)
    assert.equal(normal.body.selected.model,'deterministic-pro')
    assert.equal(f.agents[1].scopedMasks.length,0)
  } finally {f.close()}
})

test('R218 refuses a speech session with visible scope-local tools or missing guard',async()=>{
  const f=fixture({nativeToolCatalog:['normal'],scopedExtraTools:['extra_owned_plugin']})
  const id='speech_ddbbcc11223344556677889900aacc'
  try {
    // The fixture's native tool catalog represents preset-visible tools;
    // our scoped mask blocks inherited globals regardless of registration.
    const r=await f.call('/speech-bind',{method:'POST',body:{protocolVersion:1,conversation_id:id}})
    assert.equal(r.code,503)
    assert.equal(f.created,1)
    assert.equal(f.agents.length,0,'failed creation must not expose a live Agent')
    const bad=await f.call('/submit',{method:'POST',body:{
      protocolVersion:1,conversation_id:'speech_unknown_1234567890',turn_id:'no_premature_turn_1',prompt:'不能降级到普通Agent'}})
    assert.equal(bad.code,403)
    assert.equal(f.agents.length,0)
  }finally{f.close()}
})

test('R519: scoped Pinky capability check proves actual voice Agent tools without model/phone call',async()=>{
  const phones=['mcp__pinky_dafeiyu__phone_connect',
    'mcp__pinky_dafeiyu__phone_release','mcp__other__phone_connect','web_search']
  const f=fixture({webPresetConfigured:true,webPresetFixture:true,
    nativeToolCatalog:phones})
  try{
    const id='r519_phone_agent_scope_01'
    assert.equal((await f.call('/phone-capabilities',{method:'POST',body:{protocolVersion:1,conversation_id:id}})).code,404)
    assert.equal((await f.call('/phone-capabilities',{method:'POST',bearer:'bad',body:{protocolVersion:1,conversation_id:id}})).code,401)
    assert.equal((await f.call('/phone-capabilities',{method:'POST',body:{protocolVersion:1,conversation_id:id,extra:true}})).code,400)
    assert.equal((await f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:id}})).code,200)
    const result=await f.call('/phone-capabilities',{method:'POST',body:{protocolVersion:1,conversation_id:id}})
    assert.equal(result.code,200)
    assert.deepEqual(result.body,{ok:true,scoped_checked:true,agent_tools_native:true,
      pinky_dafeiyu_visible:true,pinky_tool_count:2})
    assert.equal(f.agents.length,1)
    phones.splice(0,2) // server disconnects; no stale green report
    const disconnected=await f.call('/phone-capabilities',{method:'POST',body:{protocolVersion:1,conversation_id:id}})
    assert.equal(disconnected.body.pinky_dafeiyu_visible,false)
    assert.equal(disconnected.body.pinky_tool_count,0)
  }finally{f.close()}
})

test('R519: absent Pinky tool and legacy Agent must report unavailable, not success',async()=>{
  const f=fixture({nativeToolCatalog:['web_search','mcp__other__phone_launch']})
  try{
    const id='r519_phone_agent_absent_01'
    assert.equal((await f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:id}})).code,200)
    const result=await f.call('/phone-capabilities',{method:'POST',body:{protocolVersion:1,conversation_id:id}})
    assert.equal(result.code,200)
    assert.deepEqual(result.body,{ok:true,scoped_checked:false,agent_tools_native:false,
      pinky_dafeiyu_visible:false,pinky_tool_count:0})
  }finally{f.close()}
})

// R538: native ToolRegistry enforces one-turn Pinky read-only scope, not
// merely a prompt. The fixture has all 26-like tools and an unsafe shell.
test('R538: only phone read tools are available while the bound voice task runs',async()=>{
  const {PINKY_READONLY_TOOLS}=await import('../lib/pinky-readonly-policy.js')
  const catalog=[...PINKY_READONLY_TOOLS,'mcp__pinky_dafeiyu__phone_tap',
    'mcp__pinky_dafeiyu__phone_type','mcp__pinky_dafeiyu__phone_task_run','shell']
  const f=fixture({nativeToolCatalog:catalog,webPresetConfigured:true,webPresetFixture:true})
  try {
    const conversation_id='p1_r538_pinky_readonly_01'
    const bind=await f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id}})
    assert.equal(bind.code,200)
    const capabilities=await f.call('/phone-capabilities',{method:'POST',
      body:{protocolVersion:1,conversation_id}})
    assert.equal(capabilities.body.pinky_dafeiyu_visible,true)
    assert.equal(capabilities.body.pinky_tool_count,PINKY_READONLY_TOOLS.length+3)
    // R540 does NOT impose a default Pinky whitelist; only the original
    // independent native Web preset policy is present for ordinary turns.
    assert.deepEqual(f.agents[0].scopedMasks[0].filter,
      {deny:['web_search','web_fetch']})
    const preflight=await f.call('/phone-readonly-preflight',{method:'POST',
      body:{protocolVersion:1,conversation_id}})
    assert.equal(preflight.code,200)
    assert.equal(preflight.body.readonly_mask_verified,true)
    assert.equal(preflight.body.actual_phone_tools_executed,0)
    assert.equal(preflight.body.model_turns_created,0)
    assert.equal(f.agents[0].agent.followed.length,0)
    const response=await f.call('/submit',{method:'POST',body:{
      ...input('r538_phone_read_001','只读查询手机应用列表'),
      conversation_id,phone_read_only:true,
    }})
    assert.equal(response.code,202,response.body.error)
    const owned=f.agents[0]
    assert.equal(owned.agent.followed.length,1)
    const guard=owned.scopedGuards.at(-1)
    assert.equal(guard({name:'mcp__pinky_dafeiyu__phone_apps'}),undefined,
      'in-flight explicitly verified phone query allowed')
    const invalidRepeat=await f.call('/submit',{method:'POST',body:{
      ...input('r538_phone_read_001','只读查询手机应用列表'),
      conversation_id,
    }})
    assert.equal(invalidRepeat.code,409,
      'a cached read-only task cannot be reused with normal tool permissions')
    assert.equal(owned.scopedMasks.length,3)
    assert.equal(owned.scopedMasks[1].active,false,
      'free preflight mask must be removed before the real phone task')
    assert.equal(owned.scopedMasks.at(-1).active,true)
    assert.deepEqual(owned.scopedMasks.at(-1).filter,{allow:PINKY_READONLY_TOOLS})
    await f.runHooks('session/event',owned.agent.session,{
      type:'tool/call',data:{callId:'phone-read-1',name:'mcp__pinky_dafeiyu__phone_apps'}})
    await f.runHooks('session/event',owned.agent.session,{
      type:'tool/result',data:{message:{
        role:'tool',source:{kind:'tool',callId:'phone-read-1'},
        toolCallId:'phone-read-1',isError:false}}})
    await f.runHooks('session/event',owned.agent.session,{type:'assistant/message',
      data:{message:{content:[{type:'text',text:'已收到手机应用列表回应。'}]}}})
    await f.runHooks('session/event',owned.agent.session,{type:'turn/end',
      data:{reason:{kind:'completed'}}})
    await f.runHooks('agent/status',{agent:owned.agent,status:'idle'})
    const result=(await f.call('/result',{method:'POST',body:query(response.body)})).body
    assert.equal(result.status,'completed')
    assert.equal(result.result.phone_read_only_scoped,true)
    assert.equal(owned.scopedMasks.at(-1).active,false,
      'official terminal releases mask so future normal DSH turns work')
    assert.equal(guard({name:'mcp__pinky_dafeiyu__phone_apps'}),
      'r542_phone_turn_owner_required',
      'ambient conversations cannot read the users phone after task')
    assert.equal(guard({name:'mcp__pinky_dafeiyu__phone_tap'}),
      'r542_phone_turn_owner_required')
  } finally {f.close()}
})

test('R538: unscopeable or absent Agent blocks phone before native followup',async()=>{
  const normal=fixture({webPresetConfigured:true,webPresetFixture:true,nativeToolCatalog:[
    'mcp__pinky_dafeiyu__phone_apps','mcp__pinky_dafeiyu__phone_connect',
    'mcp__pinky_dafeiyu__phone_task_list','shell']})
  try {
    const id='p1_r538_mask_missing_001'
    const unbound=await normal.call('/submit',{method:'POST',body:{
      ...input('r538_bad_unbound_01'),conversation_id:id,phone_read_only:true}})
    assert.equal(unbound.code,409)
    assert.equal(normal.created,0)
    const bind=await normal.call('/bind',{method:'POST',
      body:{protocolVersion:1,conversation_id:id}})
    assert.equal(bind.code,200)
    const okay=await normal.call('/submit',{method:'POST',body:{
      ...input('r538_with_mask_001'),conversation_id:id,phone_read_only:true}})
    assert.equal(okay.code,202)
    assert.equal(normal.agents[0].agent.followed.length,1)
    // A SECOND read-only query in same busy Agent must never launch.
    const busy=await normal.call('/submit',{method:'POST',body:{
      ...input('r538_repeat_00001'),conversation_id:id,phone_read_only:true}})
    assert.equal(busy.code,409)
  }finally{normal.close()}

  const unsafe=fixture({webPresetConfigured:true,webPresetFixture:true,nativeToolCatalog:[
    'mcp__pinky_dafeiyu__phone_connect','mcp__pinky_dafeiyu__phone_task_list'],
    scopedExtraTools:['shell']})
  try {
    const id='p1_r538_mask_ignored_001'
    await unsafe.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:id}})
    const response=await unsafe.call('/submit',{method:'POST',body:{
      ...input('r538_scope_ignored1'),conversation_id:id,phone_read_only:true}})
    assert.equal(response.code,500)
    assert.equal(unsafe.agents[0].agent.followed.length,0,
      'mask that cannot hide a globally exposed shell must fail closed')
    assert.equal(unsafe.agents[0].scopedMasks.at(-1).active,false)
  }finally{unsafe.close()}
})

test('R538: invalid read-only intent flag and generic turns do not widen scope',async()=>{
  const catalog=['shell','mcp__pinky_dafeiyu__phone_connect',
    'mcp__pinky_dafeiyu__phone_task_list']
  const f=fixture({nativeToolCatalog:catalog,webPresetConfigured:true,webPresetFixture:true})
  try {
    const id='p1_r538_regular_session_001'
    await f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:id}})
    for(const bad of [false,'true',null]) {
      const response=await f.call('/submit',{method:'POST',
        body:{...input('r538_bad_flag_0001'),conversation_id:id,phone_read_only:bad}})
      assert.equal(response.code,400)
    }
    assert.equal(f.agents[0].agent.followed.length,0)
    const normal=await f.call('/submit',{method:'POST',
      body:{...input('r538_standard_0001'),conversation_id:id}})
    assert.equal(normal.code,202)
    assert.equal(f.agents[0].scopedMasks.length,1,
      'normal turns keep their existing native web policy; this fixture has no risky Pinky tool')
    assert.equal(f.agents[0].scopedGuards.at(-1)({name:'mcp__pinky_dafeiyu__phone_apps'}),
      'r542_phone_turn_owner_required',
      'an ordinary question may not inspect a private phone')
    assert.deepEqual(f.agents[0].scopedMasks[0].filter,{deny:['web_search','web_fetch']})

  }finally{f.close()}
})

// R540: all 26 native Pinky tools follow the person's existing Pinky policy.
const R540_PHONE_NAMES=[
  'phone_app','phone_apps','phone_batch','phone_connect','phone_device',
  'phone_drag','phone_files','phone_handoff','phone_key','phone_launch',
  'phone_logs','phone_observe','phone_pinch','phone_read_list',
  'phone_release','phone_request_approval','phone_swipe','phone_tap',
  'phone_task_cancel','phone_task_list','phone_task_run','phone_task_status',
  'phone_task_steer','phone_task_wait','phone_type','phone_wait_for',
].map(name=>'mcp__pinky_dafeiyu__'+name)

test('R540: full native Agent Pinky tools, user intent gate, exact official receipt',async()=>{
  const f=fixture({webPresetConfigured:true,webPresetFixture:true,
    nativeToolCatalog:[...R540_PHONE_NAMES,'shell','web_search','web_fetch']})
  try {
    const id='p1_r540_full_phone_scope_01'
    const bind=await f.call('/bind',{method:'POST',
      body:{protocolVersion:1,conversation_id:id}})
    assert.equal(bind.code,200)
    const scope=await f.call('/phone-policy-capabilities',{method:'POST',
      body:{protocolVersion:1,conversation_id:id}})
    assert.equal(scope.code,200)
    assert.equal(scope.body.pinky_policy_available,true)
    assert.equal(scope.body.pinky_tool_count,26)
    assert.equal(scope.body.foreground_screen_read_available,true)
    assert.equal(scope.body.app_launch_available,true)
    assert.equal(scope.body.approval_decisions_bypassed,false)
    assert.equal(scope.body.phone_tools_executed,0)
    assert.equal(scope.body.model_turns_created,0)
    const bound=f.agents[0]
    assert.equal(bound.agent.followed.length,0)
    assert.deepEqual(bound.scopedMasks.map(x=>x.filter),
      [{deny:['web_search','web_fetch']}],
      'No R538 global phone deny mask or other new scope installed')
    const phoneGuard=bound.scopedGuards.at(-1)
    assert.equal(phoneGuard({name:'mcp__pinky_dafeiyu__phone_tap'}),
      'r542_phone_turn_owner_required')
    assert.equal(phoneGuard({name:'mcp__pinky_dafeiyu__phone_observe'}),
      'r542_phone_turn_owner_required')
    assert.equal(phoneGuard({name:'shell'}),undefined)
    const submitted=await f.call('/submit',{method:'POST',body:{
      ...input('r540_official_phone_01','帮我通过Pinky看看iPhone当前前台软件'),
      conversation_id:id,phone_policy:'pinky',
    }})
    assert.equal(submitted.code,202,submitted.body.error)
    assert.equal(bound.agent.followed.length,1)
    assert.equal(bound.scopedMasks.length,1,
      'Full Pinky operation requires no lossy allowlist')
    for(const name of R540_PHONE_NAMES)
      assert.equal(phoneGuard({name}),undefined,'Pinky tool allowed: '+name)
    const changed=await f.call('/submit',{method:'POST',body:{
      ...input('r540_official_phone_01','帮我通过Pinky看看iPhone当前前台软件'),
      conversation_id:id,
    }})
    assert.equal(changed.code,409)
    const tool='mcp__pinky_dafeiyu__phone_observe'
    await f.runHooks('session/event',bound.agent.session,{
      type:'tool/call',data:{callId:'read-foreground',name:tool}})
    await f.runHooks('session/event',bound.agent.session,{
      type:'tool/result',data:{message:{
        role:'tool',source:{kind:'tool',callId:'read-foreground'},
        toolCallId:'read-foreground',isError:false}}})
    await f.runHooks('session/event',bound.agent.session,{type:'assistant/message',
      data:{message:{content:[{type:'text',text:'手机当前前台是浏览器（测试占位）。'}]}}})
    await f.runHooks('session/event',bound.agent.session,{type:'turn/end',
      data:{reason:{kind:'completed'}}})
    await f.runHooks('agent/status',{agent:bound.agent,status:'idle'})
    const result=(await f.call('/result',{method:'POST',body:query(submitted.body)})).body
    assert.equal(result.status,'completed')
    assert.equal(result.result.phone_pinky_policy_scoped,true)
    assert.equal(result.result.phone_read_only_scoped,false)
    assert.deepEqual(result.result.tool_receipts,[{name:tool,receipt:'success'}])
    assert.equal(phoneGuard({name:tool}),'r542_phone_turn_owner_required')
    assert.equal(phoneGuard({name:'mcp__pinky_dafeiyu__phone_launch'}),
      'r542_phone_turn_owner_required')
    assert.equal(bound.scopedMasks.length,1)
  } finally {f.close()}
})

test('R540: incomplete catalog, ambiguous flags and bad bearer fail closed',async()=>{
  const limited=fixture({webPresetConfigured:true,webPresetFixture:true,
    nativeToolCatalog:R540_PHONE_NAMES.slice(0,6)})
  try {
    const id='p1_r540_incomplete_agent_01'
    const unbound=await limited.call('/submit',{method:'POST',body:{
      ...input('r540_invalid_unbound'),conversation_id:id,phone_policy:'pinky'}})
    assert.equal(unbound.code,409)
    assert.equal(limited.created,0)
    await limited.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:id}})
    const cap=await limited.call('/phone-policy-capabilities',{method:'POST',
      body:{protocolVersion:1,conversation_id:id}})
    assert.equal(cap.body.pinky_policy_available,false)
    assert.equal(cap.body.pinky_tool_count,6)
    for(const mode of [null,'all','true',false]) {
      const bad=await limited.call('/submit',{method:'POST',body:{
        ...input('r540_invalid_mode_01'),conversation_id:id,phone_policy:mode}})
      assert.equal(bad.code,400)
    }
    const conflict=await limited.call('/submit',{method:'POST',body:{
      ...input('r540_double_mode_01'),conversation_id:id,
      phone_policy:'pinky',phone_read_only:true}})
    assert.equal(conflict.code,400)
    const auth=await limited.call('/phone-policy-capabilities',{method:'POST',
      bearer:'wrong',body:{protocolVersion:1,conversation_id:id}})
    assert.equal(auth.code,401)
    const attempted=await limited.call('/submit',{method:'POST',body:{
      ...input('r540_blocked_phone_01'),conversation_id:id,phone_policy:'pinky'}})
    assert.equal(attempted.code,500)
    assert.equal(limited.agents[0].agent.followed.length,0)
    const result=(await limited.call('/result',{method:'POST',
      body:query(attempted.body)})).body
    assert.equal(result.status,'failed')
    assert.equal(result.failure,'r540_full_pinky_catalog_unavailable')
    assert.equal(limited.agents[0].scopedGuards.at(-1)(
      {name:'mcp__pinky_dafeiyu__phone_connect'}),
      'r542_phone_turn_owner_required')
  }finally{limited.close()}
})

test('R541: native phone step is sourced only from pending tool/call, never prompt',async()=>{
  const {companionFacts}=await import('../lib/companion-facts.js')
  const task={turn:'r541',session:'agent541',status:'running',factRevision:4,
    tools:new Map([['a',{name:'mcp__pinky_dafeiyu__phone_connect',outcome:'success'}],
                   ['b',{name:'mcp__pinky_dafeiyu__phone_launch',outcome:'pending'}]])}
  const got=companionFacts(task)
  assert.equal(got.task_phase,'working')
  assert.equal(got.phone_tool_step,'opening_app')
  assert.equal(got.tool_active_count,1)
  task.tools.get('b').outcome='success'
  assert.equal(companionFacts(task).phone_tool_step,undefined)
  task.tools.set('c',{name:'mcp__pinky_dafeiyu__phone_type',outcome:'pending'})
  assert.equal(companionFacts(task).phone_tool_step,'entering_text')
  task.tools.set('d',{name:'mcp__pinky_dafeiyu__phone_observe',outcome:'pending'})
  assert.equal(companionFacts(task).phone_tool_step,'reading_screen')
  task.tools.set('e',{name:'mcp__pinky_dafeiyu__phone_tap',outcome:'pending'})
  assert.equal(companionFacts(task).phone_tool_step,'navigating_screen')
  task.tools.set('f',{name:'shell',outcome:'pending'})
  assert.equal(companionFacts(task).phone_tool_step,'navigating_screen',
    'shell must not be rendered as a claimed phone action')
  task.tools.set('g',{name:'mcp__pinky_dafeiyu__phone_release',outcome:'pending'})
  assert.equal(companionFacts(task).phone_tool_step,'releasing_phone')
  assert.equal(JSON.stringify(companionFacts(task)).includes('content'),false)
})


test('R672: Mac CUA reports only live native step and bounded success count',async()=>{
  const {companionFacts}=await import('../lib/companion-facts.js')
  const task={turn:'r672',session:'agent672',status:'running',factRevision:3,
    approvalOutstanding:false,
    tools:new Map([['a',{name:'cua',outcome:'success',args:'private'}],
                   ['b',{name:'cua',outcome:'success'}],
                   ['c',{name:'cua',outcome:'pending',screen:'secret'}]])}
  const live=companionFacts(task)
  assert.equal(live.computer_tool_step,'cua_running')
  assert.equal(live.computer_tool_succeeded_count,2)
  assert.equal(live.tool_active_count,1)
  assert.equal(JSON.stringify(live).includes('private'),false)
  assert.equal(JSON.stringify(live).includes('secret'),false)
  task.tools.get('c').outcome='success'
  const settled=companionFacts(task)
  assert.equal(settled.computer_tool_step,undefined)
  assert.equal(settled.computer_tool_succeeded_count,3)
  task.tools.clear()
  assert.equal(companionFacts(task).computer_tool_succeeded_count,undefined)
})

test('R542: expired guard state never defeats the bound live official phone turn',async()=>{
  const tools=[
    'phone_connect','phone_observe','phone_launch','phone_tap','phone_task_run',
    'phone_request_approval',...Array.from({length:17},(_,i)=>'phone_extra_'+i),
  ].map(s=>'mcp__pinky_dafeiyu__'+s)
  const f=fixture({webPresetConfigured:true,webPresetFixture:true,
    nativeToolCatalog:[...tools,'web_search','web_fetch']})
  const id='p1_r542_native_guard_owner_001'
  const name='mcp__pinky_dafeiyu__phone_connect'
  let g
  try{
    const bind=await f.call('/bind',{method:'POST',body:{protocolVersion:1,conversation_id:id}})
    assert.equal(bind.code,200)
    const b=f.agents[0]
    assert.equal(b.scopedGuards.length,1)
    g=b.scopedGuards[0]
    assert.equal(g({name}),'r542_phone_turn_owner_required')
    // Same official conversation and Agent: no duplicate native guard.
    assert.equal((await f.call('/bind',{method:'POST',body:{
      protocolVersion:1,conversation_id:id}})).code,200)
    assert.equal(b.scopedGuards.length,1)
    const normal=await f.call('/submit',{method:'POST',body:{
      ...input('r542_normal_nonphone','今天日期'),
      conversation_id:id,
    }})
    assert.equal(normal.code,202)
    assert.equal(g({name}),'r542_phone_turn_owner_required')
    await f.runHooks('session/event',b.agent.session,{type:'assistant/message',
      data:{message:{content:[{type:'text',text:'今天星期一（离线测试）。'}]}}})
    await f.runHooks('session/event',b.agent.session,{type:'turn/end',
      data:{reason:{kind:'completed'}}})
    await f.runHooks('agent/status',{agent:b.agent,status:'idle'})
    const accepted=await f.call('/submit',{method:'POST',body:{
      ...input('r542_real_phone_turn','帮我通过Pinky查看手机屏幕'),
      conversation_id:id,phone_policy:'pinky',
    }})
    assert.equal(accepted.code,202,accepted.body.error)
    assert.equal(g({name}),undefined,
      'phone enabled by current OWNED official task, not transient boolean')
    assert.equal(g({name:'mcp__pinky_dafeiyu__phone_launch'}),undefined)
    await f.runHooks('session/event',b.agent.session,{type:'tool/call',
      data:{name,callId:'r542_connect_result'}})
    await f.runHooks('session/event',b.agent.session,{type:'tool/result',
      data:{message:{role:'tool',isError:true,toolCallId:'r542_connect_result',
        source:{kind:'tool',callId:'r542_connect_result'},
        content:[{type:'text',text:'offline tool refused'}]}}})
    await f.runHooks('session/event',b.agent.session,{type:'turn/end',
      data:{reason:{kind:'completed'}}})
    await f.runHooks('agent/status',{agent:b.agent,status:'idle'})
    const r=(await f.call('/result',{method:'POST',body:query(accepted.body)})).body
    assert.equal(r.status,'failed')
    assert.equal(r.failure,'native_tool_failed')
    assert.deepEqual(r.tools,[{name,outcome:'failed'}])
    assert.equal(g({name}),'r542_phone_turn_owner_required',
      'permission released after terminal result')
  }finally {
    f.close()
    assert.equal(f.agents[0]?.scopedGuards.length,0,
      'real DSH tool guard disposer must run on plugin cleanup')
  }
})

test('R592: native failed tap retried in same Pinky turn yields narrow recovered status, not success',async()=>{
  const f=fixture({webPresetConfigured:true,webPresetFixture:true,
    nativeToolCatalog:[...R540_PHONE_NAMES,'web_search','web_fetch']})
  try {
    const id='r592_phone_one_failed_tap_recovered'
    const bound=await f.call('/bind',{method:'POST',
      body:{protocolVersion:1,conversation_id:id}})
    assert.equal(bound.code,200)
    const submitted=await f.call('/submit',{method:'POST',body:{
      ...input('r592_scope_phone_recovery_01','帮我用手机执行这一步'),
      conversation_id:id,phone_policy:'pinky',
    }})
    assert.equal(submitted.code,202)
    const agent=f.agents.at(-1).agent
    const native=[
      ['phone_connect',false],['phone_launch',false],
      ['phone_tap',true],['phone_tap',false],
      ['phone_type',false],['phone_tap',false],
      ['phone_observe',false],['phone_tap',false],
      ['phone_release',false],
    ]
    for(let i=0;i<native.length;i++){
      const [tool,err]=native[i]
      const name='mcp__pinky_dafeiyu__'+tool
      const callId='r592-native-tool-'+i
      await f.runHooks('session/event',agent.session,{
        type:'tool/call',data:{name,callId}})
      await f.runHooks('session/event',agent.session,{
        type:'tool/result',data:{message:{
          role:'tool',source:{kind:'tool',callId},toolCallId:callId,
          isError:err,
        }}})
    }
    await f.runHooks('session/event',agent.session,{
      type:'assistant/message',data:{message:{content:[{
        type:'text',text:'手机后续步骤已经继续执行，最终结果请用户核对。'
      }]}}})
    await f.runHooks('session/event',agent.session,{
      type:'turn/end',data:{reason:{kind:'completed'}}})
    await f.runHooks('agent/status',{agent,status:'idle'})
    const final=(await f.call('/result',{method:'POST',body:query(submitted.body)})).body
    assert.equal(final.status,'failed')
    assert.equal(final.failure,'native_tool_failed')
    assert.equal(final.phone_recovery_state,
      'navigation_retried_final_unconfirmed')
    assert.equal(final.result,null)
    assert.equal(final.tools.filter(t=>t.outcome==='failed').length,1)
    assert.equal(final.tools.at(-1).outcome,'success')
  } finally {f.close()}
})


test('R675 native CUA user-question requires real Mac choice and exact task identity',async()=>{
  const f=fixture({webPresetConfigured:true,webPresetFixture:true,companionFacts:true,nativeToolCatalog:['cua']})
  try{
    const conv='p1_r675_native_cua_user_conversation'
    const task=(await f.call('/submit',{method:'POST',body:{
      ...input('r675_cua_task_001','查看Mac窗口'),conversation_id:conv}})).body
    const agent=f.agents[0].agent
    await f.runHooks('session/event',agent.session,{type:'tool/call',data:{
      callId:'r675_cua_native_001',name:'cua',arguments:{screen:'PRIVATE'}}})
    const payload={questions:[{id:'app-consent-1',
      question:'允许查看 Finder 窗口吗？',detail:'仅本次查看',
      header:'Mac App 访问授权',options:[
        {label:'允许本次'}, {label:'拒绝'}]}],agent}
    const result=f.askComputer(payload)
    const q=await f.call('/computer-question/pending',{method:'POST',body:{
      protocolVersion:1,conversation_id:conv}})
    assert.equal(q.code,200)
    assert.equal(q.body.pending.question,'允许查看 Finder 窗口吗？')
    assert.deepEqual(q.body.pending.options,['允许本次','拒绝'])
    assert.equal(JSON.stringify(q.body).includes('PRIVATE'),false)
    const facts=(await f.call('/companion-facts',{method:'POST',body:{
      ...query(task),session_id:task.session_id,after_revision:-1}})).body
    assert.ok((facts.changes??[]).some(x=>x.computer_tool_step==='cua_waiting_permission'))
    const wrong=await f.call('/computer-question/decide',{method:'POST',body:{
      protocolVersion:1,conversation_id:conv,task_id:task.task_id,
      request_id:q.body.pending.request_id,question_id:'app-consent-1',
      choice:'自动允许全部'}})
    assert.equal(wrong.code,409)
    const approved=await f.call('/computer-question/decide',{method:'POST',body:{
      protocolVersion:1,conversation_id:conv,task_id:task.task_id,
      request_id:q.body.pending.request_id,question_id:'app-consent-1',
      choice:'允许本次'}})
    assert.equal(approved.code,202)
    assert.deepEqual(await result,{answers:[{id:'app-consent-1',selected:['允许本次']}]})
    assert.equal((await f.call('/computer-question/pending',{method:'POST',body:{
      protocolVersion:1,conversation_id:conv}})).body.pending,null)
  }finally{f.close()}
})

test('R675 bounded CUA questions never convert prompts into blanket approval',()=>{
  const valid={questions:[{id:'approval.1',question:'Allow app?',options:[
    {label:'Allow once'},{label:'Deny'}]}]}
  assert.deepEqual(boundedComputerQuestion(valid).options,['Allow once','Deny'])
  assert.equal(boundedComputerQuestion({...valid,questions:[...valid.questions,...valid.questions]}),null)
  assert.equal(boundedComputerQuestion({questions:[{...valid.questions[0],
    multiSelect:true}]}),null)
  assert.equal(boundedComputerQuestion({questions:[{...valid.questions[0],
    options:[{label:'yes'},{label:'yes'}]}]}),null)
})

test('R676 single global preference authorizes only authentic native CUA app-access',async()=>{
  const { preapprovedNativeCuaChoice }=await import('../lib/computer-preconsent.js')
  const genuine={questions:[{id:'cua-app-access',
    question:'Allow Computer Use to launch if needed, read, capture, and control Some Application?',
    detail:'Application: /Applications/Some Application.app/Contents/MacOS/Binary\nTask access applies to the selected application instance',
    options:[{label:'Allow for this task'},{label:'Deny'},{label:'Always allow'}]}]}
  assert.equal(preapprovedNativeCuaChoice(genuine,false),null)
  assert.deepEqual(preapprovedNativeCuaChoice(genuine,true),{
    answers:[{id:'cua-app-access',selected:['Allow for this task']}]})
  assert.equal(preapprovedNativeCuaChoice({...genuine,questions:[{...genuine.questions[0],id:'some-other-approval'}]},true),null)
  assert.equal(preapprovedNativeCuaChoice({...genuine,questions:[{...genuine.questions[0],question:'Approve any tools?'}]},true),null)
  assert.equal(preapprovedNativeCuaChoice({...genuine,questions:[{...genuine.questions[0],options:[{label:'Always allow'},{label:'Deny'}]}]},true),null)
  assert.equal(preapprovedNativeCuaChoice({...genuine,questions:[{...genuine.questions[0],detail:'Application: /Applications/Other.app/Other\nNot the native CUA text'}]},true),null)
  assert.equal(preapprovedNativeCuaChoice(genuine,false),null)
})

test('R678 pre-getApp CUA state failure recovers only after verified read-only window proof',async()=>{
  const make=(method)=>JSON.stringify({method,params:{}})
  const accessError='Error: APP_ACCESS_REQUIRED: Select the application with getApp before reading or controlling it'
  async function scenario({failedText=accessError,lastHandle='trusted-native-handle',mutating=false,skipWindows=false}={}){
    const f=fixture()
    try{
      const user=mutating?'把Chrome页面的内容修改一下':'帮我查看我的电脑Chrome当前标签页'
      const admitted=(await f.call('/submit',{method:'POST',body:input(
        'r678_cua_readonly_'+Math.random().toString(16).slice(2,14),user)})).body
      const agent=f.agents[0].agent
      const send=async(e)=>f.runHooks('session/event',agent.session,e)
      const call=async(id,method)=>send({type:'tool/call',data:{callId:id,name:'cua',arguments:make(method)}})
      const result=async(id,isError,text)=>send({type:'tool/result',data:{message:{
        role:'tool',source:{kind:'tool',callId:id},toolCallId:id,isError,
        content:[{type:'text',text}]
      }}})
      await call('one','getState');await result('one',true,failedText)
      await call('two','getApp');await result('two',false,
        JSON.stringify({appHandle:'trusted-native-handle',pid:412,name:'Chrome',bundleId:'com.google.Chrome'}))
      await call('three','getState');await result('three',false,
        JSON.stringify({appHandle:lastHandle,pid:412,windows:skipWindows?[]:[{id:4}],
                        tree:'trusted provider tree',snapshotId:'abc'}))
      await send({type:'assistant/message',data:{message:{content:[
        {type:'text',text:'Chrome 当前标签页已在原生窗口中读取到'}]}}})
      await send({type:'turn/end',data:{reason:{kind:'completed'}}})
      await f.runHooks('agent/status',{agent,status:'idle'})
      return (await f.call('/result',{method:'POST',body:query(admitted)})).body
    }finally{f.close()}
  }
  const success=await scenario()
  assert.equal(success.status,'completed')
  assert.equal(success.result.execution_verified,true)
  assert.deepEqual(success.result.tool_receipts.map(x=>x.receipt),['failed','success','success'])
  for(const arg of [{failedText:'Error: APP_ACCESS_DENIED'},
                    {lastHandle:'DIFFERENT-NATIVE-HANDLE'},
                    {mutating:true},{skipWindows:true}]){
    const failed=await scenario(arg)
    assert.equal(failed.status,'failed')
    assert.equal(failed.failure,'native_tool_failed')
    assert.equal(failed.result,null)
  }
})
