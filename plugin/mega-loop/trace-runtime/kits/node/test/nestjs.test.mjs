/**
 * The kit in a NestJS app, set up the way the README tells a user to: the kit's files copied in,
 * `register` imported on the first line of main.ts, and an interceptor seating the request.
 */

import assert from 'node:assert/strict'
import { cpSync, existsSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { after, before, test } from 'node:test'

import { startCollector } from './collector.mjs'
import { startFakeOpenAI } from './fake-openai.mjs'
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

const APP = join(KIT_DIR, 'test/fixtures/nestjs')

let collector
let openai
let app
let base

before(async () => {
  mkdirSync(join(APP, 'src/tracing'), { recursive: true })
  for (const file of ['instrument.ts', 'register.ts']) {
    cpSync(join(KIT_DIR, 'src', file), join(APP, 'src/tracing', file))
  }
  prepareFixture(APP, ['run', 'build'])
  assert.ok(existsSync(join(APP, 'dist/main.js')))

  collector = await startCollector()
  openai = await startFakeOpenAI()
  const port = await freePort()
  base = `http://127.0.0.1:${port}`
  app = startApp('node', ['dist/main.js'], {
    cwd: APP,
    env: {
      OTEL_EXPORTER_OTLP_ENDPOINT: collector.endpoint,
      OTEL_SERVICE_NAME: 'orders-api',
      PORT: String(port),
      FAKE_OPENAI_URL: openai.baseURL,
    },
  })
  await app.ready(`${base}/health`)
})

after(async () => {
  await app?.stop()
  await openai?.close()
  await collector?.close()
})

async function ask(path) {
  collector.spans.length = 0
  const { answer } = await postJson(`${base}${path}`, { question: 'How many orders shipped late?' })
  assert.equal(answer, '14 orders shipped late.')
  const spans = await collector.until((s) =>
    s.some((x) => !x.parent_id && x.name.startsWith('POST')) &&
    s.some((x) => x.name === 'lookup_orders'),
  )
  return requestTrace(spans)
}

test('a Nest request is one trace, with the question on the HTTP root span', async () => {
  const spans = await ask('/chat')

  assert.ok(spans.some((s) => s.name === 'lookup_orders'), 'the tool span left the trace')
  const root = rootOf(spans)
  assert.match(root.name, /^POST/)
  assert.equal(root.attributes['input.value'], 'How many orders shipped late?')
  assert.equal(root.attributes['output.value'], '14 orders shipped late.')
  // Nest's own spans prove the NestJS instrumentation was registered, not just HTTP.
  assert.ok(spans.some((s) => s.attributes['nestjs.type']), 'no NestJS spans')

  const { exitCode, report } = grade(spans)
  assert.equal(report.verdict, 'entry_seatable', JSON.stringify(report, null, 2))
  assert.equal(exitCode, 0)
})

test('the same app without the interceptor is not seatable', async () => {
  const spans = await ask('/chat-naive')

  assert.equal(rootOf(spans).attributes['input.value'], undefined)
  const { exitCode, report } = grade(spans)
  assert.notEqual(report.verdict, 'entry_seatable')
  assert.equal(exitCode, 1)
})


test('a model call is an LLM span with its messages, with no tracing code in the handler', async () => {
  collector.spans.length = 0
  const { answer } = await postJson(`${base}/chat-llm`, { question: 'How many orders shipped late?' })
  assert.equal(answer, 'Fourteen orders shipped late.')

  const spans = requestTrace(
    await collector.until((s) => s.some((x) => x.span_kind === 'LLM')),
  )
  const llm = spans.find((s) => s.span_kind === 'LLM')
  assert.ok(llm, 'no LLM span — the OpenInference instrumentation was not installed')

  // The four things MEGA Loop reads off a model call. Asserted by name, because a span that has a
  // kind but no messages is the shape the old opt-in default produced: visible, and unreadable.
  assert.equal(llm.attributes['llm.input_messages.0.message.role'], 'user')
  assert.equal(
    llm.attributes['llm.input_messages.0.message.content'],
    'How many orders shipped late?',
  )
  assert.equal(
    llm.attributes['llm.output_messages.0.message.content'],
    'Fourteen orders shipped late.',
  )
  assert.equal(llm.attributes['llm.model_name'], 'gpt-4o-mini')

  if (process.env.SHOW_LLM_SPAN) {
    console.log(JSON.stringify({ name: llm.name, span_kind: llm.span_kind, attributes: llm.attributes }, null, 2))
  }

  const { exitCode, report } = grade(spans)
  assert.equal(report.verdict, 'entry_seatable', JSON.stringify(report, null, 2))
  assert.equal(exitCode, 0)
})
