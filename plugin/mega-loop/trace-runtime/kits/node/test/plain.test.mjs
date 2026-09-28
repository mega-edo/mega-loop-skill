/**
 * The kit in a plain Node process: the example agent, and a two-service request that must stay
 * one trace without any hand-written propagation.
 */

import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { join } from 'node:path'

import { startCollector } from './collector.mjs'
import {
  KIT_DIR,
  freePort,
  grade,
  postJson,
  requestTrace,
  rootOf,
  startApp,
  traceIds,
} from './harness.mjs'

const REGISTER = join(KIT_DIR, 'dist/register.js')
const SERVICES = join(KIT_DIR, 'test/fixtures/plain/services.mjs')

let collector
before(async () => {
  collector = await startCollector()
})
after(() => collector.close())

test('the example agent emits one seatable trace', async () => {
  collector.spans.length = 0
  const app = startApp('node', [join(KIT_DIR, 'dist/example-agent.js')], {
    cwd: KIT_DIR,
    env: { OTEL_EXPORTER_OTLP_ENDPOINT: collector.endpoint },
  })
  await new Promise((r) => app.child.once('exit', r))
  assert.equal(app.child.exitCode, 0, app.output())

  const spans = await collector.until((s) => s.some((x) => x.name === 'POST /chat'))
  assert.equal(traceIds(spans).length, 1)
  assert.equal(rootOf(spans).attributes['input.value'], 'How many orders shipped late last week?')

  const { exitCode, report } = grade(spans)
  assert.equal(report.verdict, 'entry_seatable', JSON.stringify(report, null, 2))
  assert.equal(exitCode, 0)
})

async function runTwoServices({ seatInput }) {
  collector.spans.length = 0
  const [gatewayPort, retrieverPort] = [await freePort(), await freePort()]
  const env = { OTEL_EXPORTER_OTLP_ENDPOINT: collector.endpoint, SEAT_INPUT: seatInput ? '1' : '0' }
  const retriever = startApp('node', ['--import', REGISTER, SERVICES], {
    cwd: KIT_DIR,
    env: { ...env, ROLE: 'retriever', OTEL_SERVICE_NAME: 'retriever', PORT: String(retrieverPort) },
  })
  const gateway = startApp('node', ['--import', REGISTER, SERVICES], {
    cwd: KIT_DIR,
    env: {
      ...env,
      ROLE: 'gateway',
      OTEL_SERVICE_NAME: 'gateway',
      PORT: String(gatewayPort),
      RETRIEVER_URL: `http://127.0.0.1:${retrieverPort}`,
    },
  })
  try {
    await retriever.ready(`http://127.0.0.1:${retrieverPort}/`)
    await gateway.ready(`http://127.0.0.1:${gatewayPort}/`)
    const { answer } = await postJson(`http://127.0.0.1:${gatewayPort}/chat`, {
      question: 'What is the shipping SLA?',
    })
    assert.equal(answer, 'Found 1 document(s).')
  } finally {
    await Promise.all([gateway.stop(), retriever.stop()])
  }
  const spans = await collector.until(
    (s) => s.some((x) => x.service === 'gateway' && !x.parent_id && x.name.startsWith('POST')) &&
      s.some((x) => x.name === 'search_docs'),
  )
  return requestTrace(spans)
}

test('a request across two services stays one trace, seated on the gateway root', async () => {
  const spans = await runTwoServices({ seatInput: true })

  assert.deepEqual(new Set(spans.map((s) => s.service)), new Set(['gateway', 'retriever']))
  assert.ok(spans.some((s) => s.name === 'search_docs'), 'the retriever span left the trace')
  const root = rootOf(spans)
  assert.equal(root.service, 'gateway')
  assert.equal(root.attributes['input.value'], 'What is the shipping SLA?')
  assert.equal(root.attributes['output.value'], 'Found 1 document(s).')

  const { exitCode, report } = grade(spans)
  assert.equal(report.verdict, 'entry_seatable', JSON.stringify(report, null, 2))
  assert.equal(exitCode, 0)
})

test('without setRequestInput the root carries no request and the trace is not seatable', async () => {
  const spans = await runTwoServices({ seatInput: false })

  assert.equal(rootOf(spans).attributes['input.value'], undefined)
  const { exitCode, report } = grade(spans)
  // The retriever's own input seats the entry as a fallback, so this is `degraded`, not
  // `entry_missing` — but the root check fails, which is the point of setRequestInput.
  assert.notEqual(report.verdict, 'entry_seatable')
  assert.equal(report.checks.find((c) => c.id === 'R1b_clean_root').verdict, 'fail')
  assert.equal(exitCode, 1)
})
