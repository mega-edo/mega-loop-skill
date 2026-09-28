/**
 * A stand-in for Langfuse / Phoenix: an OTLP/HTTP receiver that keeps every span in memory.
 *
 * The kit's exporter is the real one, sending the same JSON it sends to a platform, so a test
 * that reads spans from here exercises everything except the platform's own storage. Spans come
 * out in the flat shape `validate_traces.py --file` reads (see assets/good-trace.json).
 */

import { createServer } from 'node:http'

function attributeValue(value) {
  if (value == null) return null
  if ('stringValue' in value) return value.stringValue
  if ('boolValue' in value) return value.boolValue
  if ('intValue' in value) return Number(value.intValue)
  if ('doubleValue' in value) return value.doubleValue
  if ('arrayValue' in value) return (value.arrayValue.values ?? []).map(attributeValue)
  return null
}

function nanosToIso(nanos) {
  return new Date(Number(BigInt(nanos) / 1_000_000n)).toISOString()
}

/** OTLP's SpanKind/StatusCode enums, reduced to what the validator reads. */
const STATUS = { 0: 'UNSET', 1: 'OK', 2: 'ERROR' }

function flatten(payload) {
  const spans = []
  for (const resourceSpans of payload.resourceSpans ?? []) {
    const service = (resourceSpans.resource?.attributes ?? []).find(
      (a) => a.key === 'service.name',
    )
    for (const scopeSpans of resourceSpans.scopeSpans ?? []) {
      for (const span of scopeSpans.spans ?? []) {
        const attributes = Object.fromEntries(
          (span.attributes ?? []).map((a) => [a.key, attributeValue(a.value)]),
        )
        spans.push({
          span_id: span.spanId,
          trace_id: span.traceId,
          parent_id: span.parentSpanId ?? '',
          name: span.name,
          span_kind: attributes['openinference.span.kind'] ?? '',
          status_code: STATUS[span.status?.code ?? 0],
          status_message: span.status?.message ?? '',
          start_time: nanosToIso(span.startTimeUnixNano),
          end_time: nanosToIso(span.endTimeUnixNano),
          service: attributeValue(service?.value),
          attributes,
        })
      }
    }
  }
  return spans
}

export async function startCollector() {
  const spans = []
  const server = createServer((req, res) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      if (req.url !== '/v1/traces' || !req.headers['content-type']?.includes('json')) {
        res.writeHead(415).end()
        return
      }
      spans.push(...flatten(JSON.parse(Buffer.concat(chunks).toString('utf8'))))
      res.writeHead(200, { 'content-type': 'application/json' }).end('{}')
    })
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address()
  return {
    endpoint: `http://127.0.0.1:${port}`,
    spans,
    /** Wait until `predicate(spans)` holds — spans arrive in batches, in no promised order. */
    async until(predicate, { timeoutMs = 15_000 } = {}) {
      const deadline = Date.now() + timeoutMs
      while (!predicate(spans)) {
        if (Date.now() > deadline) {
          throw new Error(`collector timed out with ${spans.length} spans: ` +
            JSON.stringify(spans.map((s) => `${s.service}:${s.name}`)))
        }
        await new Promise((r) => setTimeout(r, 100))
      }
      return spans
    },
    close: () => new Promise((resolve) => server.close(resolve)),
  }
}
