import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clockLine, clockSectionText, MAX_CLOCK_LINE_BYTES,
} from '../lib/session-clock.js'

// 2026-11-05T12:58:11Z is 2026-11-05 20:58 in Shanghai and still 11-05 in UTC.
const FIXED = new Date('2026-11-05T12:58:11Z')

test('renders the exact local wall clock and weekday for an explicit zone', () => {
  assert.equal(
    clockLine(FIXED, { timeZone: 'Asia/Shanghai' }),
    '本机当前时间 2026-11-05 20:58（周四，时区 +08:00）。'
      + '这是只读的环境事实，不是工具调用结果；被问到日期或时间时直接使用，'
      + '不要回答无法读取时钟。',
  )
})

test('the same instant renders differently in another zone, without guessing', () => {
  const utc = clockLine(FIXED, { timeZone: 'UTC' })
  assert.match(utc, /2026-11-05 12:58（周四，时区 (?:\+00:00|UTC)）/)
  const shanghai = clockLine(FIXED, { timeZone: 'Asia/Shanghai' })
  assert.notEqual(utc, shanghai)
})

test('weekday follows the zone-local calendar date, not the process zone', () => {
  // 2026-11-05T20:30Z is already Friday 04:30 in Shanghai.
  const late = new Date('2026-11-05T20:30:00Z')
  assert.match(clockLine(late, { timeZone: 'Asia/Shanghai' }), /2026-11-06 04:30（周五/)
  assert.match(clockLine(late, { timeZone: 'UTC' }), /2026-11-05 20:30（周四/)
})

test('line stays bounded and never claims a tool call', () => {
  const line = clockLine(FIXED, { timeZone: 'Asia/Shanghai' })
  assert.ok(Buffer.byteLength(line, 'utf8') <= MAX_CLOCK_LINE_BYTES)
  assert.doesNotMatch(line, /tool_|调用成功|已执行/)
  assert.match(line, /不是工具调用/)
})

test('invalid dates are refused instead of printing NaN', () => {
  assert.throws(() => clockLine(new Date('not-a-date'), { timeZone: 'UTC' }),
    /clockLine_requires_valid_date/)
  assert.throws(() => clockLine('2026-11-05', { timeZone: 'UTC' }),
    /clockLine_requires_valid_date/)
})

test('section text is a function so every assembly re-reads the clock', () => {
  const text = clockSectionText({ now: () => FIXED, timeZone: 'Asia/Shanghai' })
  assert.equal(typeof text, 'function')
  assert.match(text(), /2026-11-05 20:58/)
  // A later assembly with a later clock must not return the old minute.
  const later = clockSectionText({ now: () => new Date('2026-11-05T13:05:00Z'),
    timeZone: 'Asia/Shanghai' })
  assert.match(later(), /2026-11-05 21:05/)
})
