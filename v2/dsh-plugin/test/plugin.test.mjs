import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { test } from 'node:test'
import { apply } from '../src/index.mjs'

test('native tools preserve memory mode and scoped update HTTP contract', async t => {
  const requests = []
  const http = createServer(async (req, res) => {
    let body = ''
    for await (const chunk of req) body += chunk
    requests.push({ method: req.method, url: req.url, body: body ? JSON.parse(body) : undefined })
    res.setHeader('content-type', 'application/json')
    res.end('{"ok":true}')
  })
  await new Promise(resolve => http.listen(0, '127.0.0.1', resolve))
  t.after(() => new Promise(resolve => { http.closeAllConnections(); http.close(resolve) }))
  const tools = new Map()
  const sections = []
  apply({ tools: { register: tool => tools.set(tool.name, tool) }, systemPrompt: { section: section => sections.push(section) } }, {
    baseUrl: `http://127.0.0.1:${http.address().port}`, scopeId: 'test-study', timeoutMs: 10000,
  })
  const exec = { signal: new AbortController().signal }
  assert.equal(tools.size, 13)
  assert.equal(sections.length, 1)
  await assert.rejects(tools.get('trader_recall_memory').execute({ query: '现金流风险' }, exec), /mode/)
  await tools.get('trader_recall_memory').execute({ query: '现金流风险', mode: 'imported' }, exec)
  assert.equal(requests[0].body.mode, 'imported')
  assert.equal(requests[0].body.scope_id, 'test-study')
  await tools.get('trader_update_memory').execute({
    memory_id: '00000000-0000-0000-0000-000000000001', expected_revision: 1,
    kind: 'preference', content: '关注现金流风险', source_type: 'user_statement', source_reference: '请记住：关注现金流风险',
  }, exec)
  assert.equal(requests[1].method, 'PUT')
  assert.equal(new URL(requests[1].url, 'http://localhost').searchParams.get('scope_id'), 'test-study')
  assert.equal(requests[1].body.expected_revision, 1)
  assert.equal('scope_id' in requests[1].body, false)
  assert.equal('memory_id' in requests[1].body, false)
})
