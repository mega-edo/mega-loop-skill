/**
 * The kit in a Next.js app: `setupTracing()` from `instrumentation.ts`, `setRequestInput` in a
 * route handler, and a `fetch` to a second service that must continue the same trace.
 */

import assert from 'node:assert/strict'
import { cpSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { after, before, test } from 'node:test'

import { startCollector } from './collector.mjs'
import {
  KIT_DIR,
  freePort,
  grade,
  postJson,
  prepareFixture,
  requestTrace,
  rootOf,
  startApp,
} from './harness.mjs'

const APP = join(KIT_DIR, 'test/fixtures/nextjs')

let collector
let retriever
let app
let base

before(async () => {
  mkdirSync(join(APP, 'tracing'), { recursive: true })
  cpSync(join(KIT_DIR, 'src/instrument.ts'), join(APP, 'tracing/instrument.ts'))
  prepareFixture(APP, ['run', 'build'])

  collector = await startCollector()
  const retrieverPort = await freePort()
  retriever = startApp(
    'node',
    ['--import', join(KIT_DIR, 'dist/register.js'), join(KIT_DIR, 'test/fixtures/plain/services.mjs')],
    {
      cwd: KIT_DIR,
      env: {
        OTEL_EXPORTER_OTLP_ENDPOINT: collector.endpoint,
        OTEL_SERVICE_NAME: 'retriever',
        ROLE: 'retriever',
        PORT: String(retrieverPort),
      },
    },
  )
  const port = await freePort()
  base = `http://127.0.0.1:${port}`
  app = startApp('node_modules/.bin/next', ['start', '-p', String(port), '-H', '127.0.0.1'], {
    cwd: APP,
    env: {
      NEXT_TELEMETRY_DISABLED: '1',
      OTEL_EXPORTER_OTLP_ENDPOINT: collector.endpoint,
      OTEL_SERVICE_NAME: 'next-app',
      RETRIEVER_URL: `http://127.0.0.1:${retrieverPort}`,
    },
  })
  await retriever.ready(`http://127.0.0.1:${retrieverPort}/`)
  await app.ready(`${base}/api/health`)
})

after(async () => {
  await Promise.all([app?.stop(), retriever?.stop()])
  await collector?.close()
})

async function ask(path) {
  collector.spans.length = 0
  const { answer } = await postJson(`${base}${path}`, { question: 'What is the shipping SLA?' })
  assert.equal(answer, 'Found 1 document(s).')
  const spans = await collector.until((s) =>
    s.some((x) => x.service === 'next-app' && !x.parent_id && x.name.startsWith('POST')) &&
    s.some((x) => x.name === 'search_docs'),
  )
  return requestTrace(spans)
}

test('a Next.js route is one trace across services, seated on the Next root span', async () => {
  const spans = await ask('/api/chat')

  assert.ok(spans.some((s) => s.name === 'search_docs'), 'the retriever span left the trace')
  const root = rootOf(spans)
  assert.equal(root.service, 'next-app')
  assert.equal(root.attributes['input.value'], 'What is the shipping SLA?')
  assert.equal(root.attributes['output.value'], 'Found 1 document(s).')

  const { exitCode, report } = grade(spans)
  assert.equal(report.verdict, 'entry_seatable', JSON.stringify(report, null, 2))
  assert.equal(exitCode, 0)
})

test('the same route without setRequestInput is not seatable', async () => {
  const spans = await ask('/api/chat-naive')

  assert.equal(rootOf(spans).attributes['input.value'], undefined)
  const { exitCode, report } = grade(spans)
  assert.notEqual(report.verdict, 'entry_seatable')
  assert.equal(exitCode, 1)
})
