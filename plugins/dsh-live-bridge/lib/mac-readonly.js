/** Project-owned, per-Agent, closed-scope Mac volume reader.
 * No shell, external service, arbitrary path, file contents or private metadata.
 * This tool exists only in Deepseek-live and is NOT registered globally.
 */
import { statfsSync } from 'node:fs'
import { createScopedMemorySearchTool, MEMORY_SEARCH_TOOL } from './memory-readonly.js'

export const READ_VOLUME_TOOL = 'dsh_live_read_volume'
export const WEB_SEARCH_TOOL = 'web_search'
const MAX_NATIVE_SEARCHES_PER_AGENT = 2

export function createReadVolumeTool(root) {
  return {
    name: READ_VOLUME_TOOL,
    description: 'Read only the free and total GB of the fixed Deepseek-live project volume. No arguments, no file content.',
    parameters: { type: 'object', properties: {}, required: [], additionalProperties: false },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(_args, exec) {
      if (exec?.signal?.aborted) throw new Error('operation_cancelled')
      const v = statfsSync(root)
      const total = Math.round(v.blocks * v.bsize / 1073741824 * 10) / 10
      const free = Math.round(v.bavail * v.bsize / 1073741824 * 10) / 10
      if (!Number.isFinite(total) || !Number.isFinite(free) ||
          total < 0 || free < 0 || free > total) {
        throw new Error('volume_stats_unavailable')
      }
      return JSON.stringify({
        scope: 'deepseek_live_project_volume',
        total_gb: total, free_gb: free,
        contents_read: false, readonly: true,
      })
    },
  }
}

export function installReadonlyScope(agentCtx, root, memoryEndpoint = null, nativeSearch = false) {
  // Mandatory scoped defense in depth: hide ALL inherited tools from the model.
  // The scoped register below is the only visible business tool.
  // Guard is monotonic: late approval/pre-execute changes cannot admit Bash.
  const tools = agentCtx?.tools
  if (!tools || typeof tools.restrict !== 'function' ||
      typeof tools.guard !== 'function' || typeof tools.register !== 'function') {
    throw new Error('native_scoped_tool_policy_unavailable')
  }
  // Global tools stay hidden. Scoped memory reader (if opted in) shadows ReMe's
  // global tool without allowing arbitrary other Harness tools.
  const memoryTool = memoryEndpoint ? createScopedMemorySearchTool(memoryEndpoint) : null
  // Native DSH web_search is an inherited official tool, never an extra
  // homemade HTTP capability. Off by default: upstream auxiliary search can
  // generate additional billable model requests independently of chat turns.
  // Unknown/unregistered official names fail during restrict(), not open wider.
  const searchCalls = new Set()
  tools.restrict({ allow: nativeSearch ? [WEB_SEARCH_TOOL] : [] })
  tools.guard((exec) => {
    if (nativeSearch && exec?.name === WEB_SEARCH_TOOL) {
      if (typeof exec.callId !== 'string' || !exec.callId)
        return 'deepseek_live_web_search_missing_receipt'
      if (searchCalls.has(exec.callId)) return undefined
      if (searchCalls.size >= MAX_NATIVE_SEARCHES_PER_AGENT)
        return 'deepseek_live_web_search_budget_exhausted'
      // Conservatively reserve at guarded attempt even if upstream search fails.
      searchCalls.add(exec.callId)
      return undefined
    }
    return exec?.name === READ_VOLUME_TOOL ||
      (memoryTool && exec?.name === MEMORY_SEARCH_TOOL)
        ? undefined : 'deepseek_live_readonly_scope'
  })
  tools.register(createReadVolumeTool(root))
  if (memoryTool) tools.register(memoryTool)
}
