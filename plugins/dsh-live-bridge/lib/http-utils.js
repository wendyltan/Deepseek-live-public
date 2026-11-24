/**
 * HTTP parsing, loopback/token authentication, and local file permission checks
 * for dsh-live-bridge.
 */
import { timingSafeEqual } from 'node:crypto'
import { lstatSync, readFileSync, statSync } from 'node:fs'
import { isAbsolute } from 'node:path'

export const LIMIT_BYTES = 16 * 1024

export function readProfileBridgeToken(path) {
  if (!path) return ''
  if (!isAbsolute(path)) throw new Error('bridge_token_path_not_absolute')
  const file = statSync(path)
  if (!file.isFile() || (file.mode & 0o077) !== 0 ||
      (typeof process.getuid === 'function' && file.uid !== process.getuid())) {
    throw new Error('bridge_token_file_not_private')
  }
  return readFileSync(path, 'utf8').trim()
}

export function readProfileAdminToken(path) {
  if (!isAbsolute(path)) throw new Error('memory_admin_path_not_absolute')
  const file = lstatSync(path)
  if (file.isSymbolicLink() || !file.isFile() || file.nlink !== 1 ||
      (file.mode & 0o077) !== 0 ||
      (typeof process.getuid === 'function' && file.uid !== process.getuid())) {
    throw new Error('memory_admin_file_not_private')
  }
  return readFileSync(path, 'utf8').trim()
}

export function send(res, code, payload) {
  const body = JSON.stringify(payload)
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
  })
  res.end(body)
}

export function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0
    const parts = []
    req.on('data', (part) => {
      size += part.length
      if (size > LIMIT_BYTES) {
        reject(new Error('body_too_large'))
        return
      }
      parts.push(part)
    })
    req.on('end', () => {
      if (size > LIMIT_BYTES) return
      try {
        const obj = JSON.parse(Buffer.concat(parts).toString('utf8'))
        resolve(obj && typeof obj === 'object' && !Array.isArray(obj) ? obj : null)
      } catch {
        resolve(null)
      }
    })
    req.on('error', reject)
  })
}

export function isLoopback(req) {
  const ip = req.socket?.remoteAddress ?? ''
  return ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1'
}

export function goodToken(req, expected) {
  if (expected.length < 32 || expected.length > 256) return false
  const header = req.headers?.authorization
  if (typeof header !== 'string' || !header.startsWith('Bearer ')) return false
  const actual = Buffer.from(header.slice(7))
  const wanted = Buffer.from(expected)
  return actual.length === wanted.length && timingSafeEqual(actual, wanted)
}

export function validWorkspace(text) {
  if (typeof text !== 'string' || !isAbsolute(text)) return false
  try {
    return statSync(text).isDirectory()
  } catch {
    return false
  }
}
