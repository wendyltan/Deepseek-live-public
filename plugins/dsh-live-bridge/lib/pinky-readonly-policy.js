/** R538 single-turn Agent-scoped Pinky read-only boundary.
 *
 * This is an actual native ToolRegistry mask, not an instruction to a model.
 * Never allow phone_device: without args it can read, but the same tool can
 * change screen orientation, location and appearance.
 * Never allow phone_task_run: read_only:true still invokes Pinky's own model.
 * Never allow tap/type/launch/swipe/batch or generic shell/web tools.
 */
export const PINKY_READONLY_TOOLS = Object.freeze([
  'mcp__pinky_dafeiyu__phone_connect',
  'mcp__pinky_dafeiyu__phone_release',
  'mcp__pinky_dafeiyu__phone_apps',
  'mcp__pinky_dafeiyu__phone_task_list',
  'mcp__pinky_dafeiyu__phone_task_status',
  'mcp__pinky_dafeiyu__phone_task_wait',
])
export const PINKY_READONLY_EVIDENCE = Object.freeze([
  'mcp__pinky_dafeiyu__phone_apps',
  'mcp__pinky_dafeiyu__phone_task_list',
  'mcp__pinky_dafeiyu__phone_task_status',
  'mcp__pinky_dafeiyu__phone_task_wait',
])

// R538: default-deny every Pinky tool capable of writing, creating an
// external task, or reading the screen. This guard is attached to the ONLY
// Deepseek-live Agent, not any other DSH profile. It also covers phone
// requests that the lightweight transcript classifier fails to recognize.
export function restrictPinkyWritesForVoiceAgent(agentCtx, agent) {
  const tools=agentCtx?.tools
  if(typeof tools?.schemas!=='function' || typeof tools?.restrict!=='function')
    throw new Error('r538_pinky_guard_api_missing')
  const names=tools.schemas(agent).map(x=>x?.name)
  const phoneNames=names.filter(x=>typeof x==='string' &&
                                      x.startsWith('mcp__pinky_dafeiyu__'))
  const unsafe=phoneNames.filter(x=>!PINKY_READONLY_TOOLS.includes(x))
  if(!unsafe.length)return 0
  const undo=tools.restrict({deny:unsafe})
  if(typeof undo!=='function')
    throw new Error('r538_pinky_write_guard_not_owned')
  const after=tools.schemas(agent).map(x=>x?.name)
  if(unsafe.some(name=>after.includes(name))) {
    undo()
    throw new Error('r538_pinky_write_guard_not_enforced')
  }
  return unsafe.length
}

export function scopedReadOnlyPhoneTools(binding) {
  const phone=binding?.phone
  if(binding?.nativeTools!==true || phone?.scoped_checked!==true ||
     phone.visible!==true || typeof phone.tools?.restrict!=='function' ||
     typeof phone.tools?.schemas!=='function')
    throw new Error('r538_pinky_native_scope_missing')
  const known=phone.tools.schemas(binding.agent).map(x=>x?.name)
  if(!known.includes('mcp__pinky_dafeiyu__phone_connect') ||
     !known.includes('mcp__pinky_dafeiyu__phone_task_list'))
    throw new Error('r538_readonly_tools_missing')
  const allow=PINKY_READONLY_TOOLS.filter(name=>known.includes(name))
  const undo=phone.tools.restrict({allow})
  if(typeof undo!=='function')
    throw new Error('r538_readonly_mask_cannot_be_removed')
  // Re-read effective Agent scope AFTER restriction. A registry that silently
  // ignores the mask must not be used for a real read-only phone operation.
  try {
    const effective=phone.tools.schemas(binding.agent).map(x=>x?.name)
    if(!effective.length || effective.some(name=>!allow.includes(name)))
      throw new Error('r538_readonly_mask_not_enforced')
  } catch (err) {
    undo()
    throw err
  }
  return undo
}
