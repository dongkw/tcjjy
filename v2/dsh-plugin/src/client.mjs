/** Small HTTP boundary. Business state lives in PostgreSQL, never in this process. */
export class TraderClient {
  constructor({ baseUrl = 'http://127.0.0.1:8012', scopeId = 'local', timeoutMs = 60000 } = {}) {
    const url = new URL(baseUrl)
    if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
        || url.username || url.password || url.search || url.hash || !['', '/'].includes(url.pathname)) {
      throw new Error('V2 backend must be a local HTTP origin, for example http://127.0.0.1:8012')
    }
    if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(scopeId)) throw new Error('Invalid V2 scopeId')
    if (!Number.isInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 300000) throw new Error('Invalid V2 timeoutMs')
    this.baseUrl = url.origin
    this.scopeId = scopeId
    this.timeoutMs = timeoutMs
  }

  async request(path, { method = 'GET', body, query, signal, scoped = true, scopeInBody = method === 'POST' } = {}) {
    if (!path.startsWith('/api/') || path.includes('..') || path.includes('\\')) throw new Error('Invalid API path')
    const url = new URL(path, this.baseUrl)
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value))
    }
    if (scoped) url.searchParams.set('scope_id', this.scopeId)
    const payload = body === undefined ? undefined : { ...body, ...(scoped && scopeInBody ? { scope_id: this.scopeId } : {}) }
    const timeout = AbortSignal.timeout(this.timeoutMs)
    const combined = signal ? AbortSignal.any([signal, timeout]) : timeout
    let response
    try {
      response = await fetch(url, {
        method, redirect: 'error', signal: combined,
        headers: payload === undefined ? {} : { 'content-type': 'application/json' },
        body: payload === undefined ? undefined : JSON.stringify(payload),
      })
    } catch (error) {
      if (combined.aborted) throw new Error('V2 request cancelled or timed out. A write may already have committed; read saved records before retrying.')
      throw new Error('Cannot reach the local V2 backend. Start scripts/start.ps1 and check /health.', { cause: error })
    }
    const value = await response.json().catch(() => null)
    if (!response.ok) {
      const detail = typeof value?.detail === 'string' ? value.detail : `request rejected (${response.status})`
      throw new Error(`V2 ${response.status}: ${detail}`)
    }
    if (value === null) throw new Error('V2 returned an invalid JSON response')
    return value
  }
}

export function uuid(value) {
  if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) {
    throw new Error('Expected a UUID returned by a V2 tool')
  }
  return value
}
