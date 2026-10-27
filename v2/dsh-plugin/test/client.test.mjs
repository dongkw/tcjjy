import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { test } from 'node:test'
import { TraderClient, uuid } from '../src/client.mjs'

async function server(t, handler) {
  const http = createServer(handler)
  await new Promise(resolve => http.listen(0, '127.0.0.1', resolve))
  t.after(() => new Promise(resolve => { http.closeAllConnections(); http.close(resolve) }))
  return `http://127.0.0.1:${http.address().port}`
}

test('scope is pinned by deployment and writes are performed only once', async t => {
  let calls = 0
  const baseUrl = await server(t, async (req, res) => {
    calls++
    let text = ''
    for await (const chunk of req) text += chunk
    assert.equal(new URL(req.url, 'http://localhost').searchParams.get('scope_id'), 'study')
    assert.equal(JSON.parse(text).scope_id, 'study')
    res.setHeader('content-type', 'application/json'); res.end('{"saved":true}')
  })
  const client = new TraderClient({ baseUrl, scopeId: 'study' })
  assert.deepEqual(await client.request('/api/memory', { method: 'POST', body: { scope_id: 'other', content: 'test' } }), { saved: true })
  assert.equal(calls, 1)
})

test('cancellation reaches active fetch and no retry occurs', async t => {
  let calls = 0
  let started
  const ready = new Promise(resolve => { started = resolve })
  const baseUrl = await server(t, (_req, _res) => { calls++; started() })
  const controller = new AbortController()
  const pending = new TraderClient({ baseUrl }).request('/api/research/sessions', { signal: controller.signal })
  await ready; controller.abort()
  await assert.rejects(pending, /cancelled or timed out/)
  assert.equal(calls, 1)
})

test('backend validation error is surfaced without a fake successful result', async t => {
  const baseUrl = await server(t, (_req, res) => { res.writeHead(422, { 'content-type': 'application/json' }); res.end('{"detail":"引用尚未读取"}') })
  await assert.rejects(new TraderClient({ baseUrl }).request('/api/research/reports'), /422: 引用尚未读取/)
})

test('only a local origin and safe generated IDs are accepted', () => {
  for (const baseUrl of ['https://example.com', 'http://user:pass@localhost', 'http://localhost/api', 'http://localhost?key=secret']) {
    assert.throws(() => new TraderClient({ baseUrl }))
  }
  assert.throws(() => new TraderClient({ scopeId: '../other' }))
  assert.throws(() => uuid('../other'))
  assert.equal(uuid('00000000-0000-0000-0000-000000000000'), '00000000-0000-0000-0000-000000000000')
})
