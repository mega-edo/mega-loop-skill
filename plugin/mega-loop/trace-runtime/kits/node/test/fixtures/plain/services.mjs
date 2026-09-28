/**
 * Two services and one request: `gateway` takes the user's question and asks `retriever` over
 * HTTP. Neither touches `traceparent` by hand — if the kit's instrumentations are registered,
 * both services land in one trace; if they are not, each is its own root.
 *
 * Run once per service, preloading the kit: `node --import <kit>/dist/register.js services.mjs`.
 */

import { createServer } from 'node:http'

import { trace } from '@opentelemetry/api'

import { setRequestInput, setRequestOutput } from '../../../dist/instrument.js'

const role = process.env.ROLE
const port = Number(process.env.PORT)
const tracer = trace.getTracer(role)

async function readJson(req) {
  const chunks = []
  for await (const chunk of req) chunks.push(chunk)
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')
}

async function gateway(body) {
  if (process.env.SEAT_INPUT !== '0') setRequestInput(body.question)
  const response = await fetch(`${process.env.RETRIEVER_URL}/search`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query: body.question }),
  })
  const { documents } = await response.json()
  const answer = `Found ${documents.length} document(s).`
  setRequestOutput(answer)
  return { answer }
}

async function retriever(body) {
  return tracer.startActiveSpan('search_docs', async (span) => {
    span.setAttribute('openinference.span.kind', 'RETRIEVER')
    span.setAttribute('input.value', body.query)
    const documents = ['Shipping SLA is 3 days.']
    documents.forEach((doc, i) => {
      span.setAttribute(`retrieval.documents.${i}.document.content`, doc)
    })
    span.end()
    return { documents }
  })
}

const handlers = { gateway, retriever }

createServer(async (req, res) => {
  if (req.method === 'GET') return res.writeHead(200).end('ok')
  const result = await handlers[role](await readJson(req))
  res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(result))
}).listen(port, '127.0.0.1')
