// Read-only local clock fact, prepared for the per-turn systemPrompt assembly.
//
// Why: a real wireless turn asked "今天是星期几" and the answer was "我没有能读
// 系统时钟的工具", although the host and the board both knew the time. The gap
// is context, not model ability. This helper turns the host clock into one
// bounded, read-only fact line; it is NOT a tool call, NOT a memory write and
// NOT a guess about the user's timezone.
//
// Pure on purpose: no I/O, no timers, no ambient time inside tests. Wiring it
// into a prompt section is a separate, deployable decision (see
// research/R367_FIRST_SOUND_AND_CLOCK_OFFLINE_2026-11-05.md); this module alone
// changes no running behaviour.

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
export const MAX_CLOCK_LINE_BYTES = 240

function pad(value) {
  return String(value).padStart(2, '0')
}

function zoneLabel(date, timeZone) {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone, timeZoneName: 'longOffset',
    }).formatToParts(date)
    const name = parts.find((part) => part.type === 'timeZoneName')?.value || ''
    // "GMT+08:00" -> "+08:00"; plain "GMT"/"UTC" stays as the host's label.
    return name === 'GMT' || name === 'UTC' ? 'UTC' : name.replace(/^GMT/, '') || 'UTC'
  } catch {
    return 'UTC'
  }
}

function wallClock(date, timeZone) {
  // Derive the wall clock in the requested zone without trusting the process TZ.
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(date)
  const get = (type) => parts.find((part) => part.type === type)?.value || ''
  return {
    year: get('year'), month: get('month'), day: get('day'),
    hour: get('hour') === '24' ? '00' : get('hour'), minute: get('minute'),
  }
}

/**
 * One bounded line describing the host's current local time.
 * @param {Date} [now] injected clock; defaults to the real one.
 * @param {{timeZone?: string}} [options] explicit zone for tests or hosts whose
 *   zone must not be inferred.
 * @returns {string}
 */
export function clockLine(now = new Date(), { timeZone = undefined } = {}) {
  if (!(now instanceof Date) || Number.isNaN(now.getTime())) {
    throw new TypeError('clockLine_requires_valid_date')
  }
  const zone = timeZone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const local = wallClock(now, zone)
  const stamp = `${local.year}-${local.month}-${local.day} ${local.hour}:${local.minute}`
  const weekday = WEEKDAYS[new Date(
    Number(local.year), Number(local.month) - 1, Number(local.day)).getDay()]
  const line = `本机当前时间 ${stamp}（${weekday}，时区 ${zoneLabel(now, zone)}）。`
    + '这是只读的环境事实，不是工具调用结果；被问到日期或时间时直接使用，'
    + '不要回答无法读取时钟。'
  if (Buffer.byteLength(line, 'utf8') > MAX_CLOCK_LINE_BYTES) {
    throw new RangeError('clockLine_too_long')
  }
  return line
}

/** Prompt section body: a function so the value is re-read on every assembly. */
export function clockSectionText({ now = () => new Date(), timeZone } = {}) {
  return () => clockLine(now(), { timeZone })
}

export default clockLine
