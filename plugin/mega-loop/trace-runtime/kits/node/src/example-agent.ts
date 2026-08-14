/**
 * A correctly-traced request: one root, nested steps, a sub-agent, and a service hop.
 *
 * Running it should produce **one** trace:
 *
 *     POST /chat              CHAIN   ← root, carries input.value
 *     ├─ plan                 LLM
 *     ├─ query_orders         TOOL
 *     ├─ research_agent       AGENT   ← a sub-agent, not a new trace
 *     │  └─ search_docs       RETRIEVER
 *     └─ answer               LLM
 *
 * The fake model calls are not the point. The four numbered comments are: they mark the places
 * a request normally fragments or goes silent.
 */

import { context, propagation, SpanStatusCode, trace } from '@opentelemetry/api'

import { setupTracing, shutdownTracing } from './instrument.js'

const tracer = setupTracing({ serviceName: 'orders-agent', serviceVersion: '1.4.2' })

export async function handleRequest(question: string): Promise<string> {
  return tracer.startActiveSpan('POST /chat', async (root) => {
    root.setAttribute('openinference.span.kind', 'CHAIN')
    // (1) The root carries the user's question. Without it the trace cannot be replayed, and
    //     everything else you do right stops mattering.
    root.setAttribute('input.value', question)

    const plan = await planStep(question)
    const rows = await queryOrders(plan.window)
    const research = await researchAgent(question)
    const answer = await answerStep(question, rows, research)

    root.setAttribute('output.value', answer)
    root.end()
    return answer
  })
}

async function planStep(question: string): Promise<{ window: string }> {
  return tracer.startActiveSpan('plan', async (span) => {
    span.setAttribute('openinference.span.kind', 'LLM')
    span.setAttribute('llm.model_name', 'claude-sonnet-5')
    span.setAttribute('input.value', question)

    // (2) Messages are indexed from 0, contiguously, with standard roles.
    span.setAttribute('llm.input_messages.0.message.role', 'system')
    span.setAttribute('llm.input_messages.0.message.content', 'You answer order questions.')
    span.setAttribute('llm.input_messages.1.message.role', 'user')
    span.setAttribute('llm.input_messages.1.message.content', question)

    const plan = { window: 'last_week' }
    span.setAttribute('llm.output_messages.0.message.role', 'assistant')
    span.setAttribute('llm.output_messages.0.message.content', 'I will query the orders.')
    span.setAttribute(
      'llm.output_messages.0.message.tool_calls.0.tool_call.function.name',
      'query_orders',
    )
    span.setAttribute(
      'llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments',
      JSON.stringify(plan), // must parse as a JSON object
    )
    span.setAttribute('llm.token_count.prompt', 412)
    span.setAttribute('llm.token_count.completion', 38)
    span.setAttribute('llm.token_count.total', 450)
    span.setAttribute('output.value', 'I will query the orders.')
    span.end()
    return plan
  })
}

async function queryOrders(window: string): Promise<Array<{ id: number; late: boolean }>> {
  return tracer.startActiveSpan('query_orders', async (span) => {
    span.setAttribute('openinference.span.kind', 'TOOL')
    span.setAttribute('input.value', JSON.stringify({ window }))
    try {
      const rows = [
        { id: 1, late: true },
        { id: 2, late: true },
      ]
      span.setAttribute('output.value', JSON.stringify(rows))
      span.end()
      return rows
    } catch (error) {
      // (3) A failure is reported as a failure. Returning {"error": …} with an OK status is the
      //     most common way a real bug becomes invisible to detection.
      span.setStatus({ code: SpanStatusCode.ERROR, message: String(error) })
      span.end()
      throw error
    }
  })
}

/** A sub-agent is a span inside this trace, never a trace of its own. */
async function researchAgent(question: string): Promise<string> {
  return tracer.startActiveSpan('research_agent', async (span) => {
    span.setAttribute('openinference.span.kind', 'AGENT')
    span.setAttribute('input.value', question)
    const docs = await searchDocs(question)
    span.setAttribute('output.value', docs)
    span.end()
    return docs
  })
}

async function searchDocs(query: string): Promise<string> {
  return tracer.startActiveSpan('search_docs', async (span) => {
    span.setAttribute('openinference.span.kind', 'RETRIEVER')
    span.setAttribute('input.value', query)
    span.setAttribute('retrieval.documents.0.document.content', 'Shipping SLA is 3 days.')
    span.setAttribute('retrieval.documents.0.document.score', 0.91)
    span.end()
    return 'Shipping SLA is 3 days.'
  })
}

async function answerStep(
  question: string,
  rows: Array<{ id: number }>,
  research: string,
): Promise<string> {
  return tracer.startActiveSpan('answer', async (span) => {
    span.setAttribute('openinference.span.kind', 'LLM')
    span.setAttribute('llm.model_name', 'claude-sonnet-5')
    span.setAttribute('input.value', JSON.stringify({ rows, research }))
    span.setAttribute('llm.input_messages.0.message.role', 'user')
    span.setAttribute('llm.input_messages.0.message.content', question)
    const answer = `${rows.length} orders shipped late.`
    span.setAttribute('llm.output_messages.0.message.role', 'assistant')
    span.setAttribute('llm.output_messages.0.message.content', answer)
    span.setAttribute('llm.token_count.prompt', 486)
    span.setAttribute('llm.token_count.completion', 21)
    span.setAttribute('llm.token_count.total', 507)
    span.setAttribute('output.value', answer)
    span.end()
    return answer
  })
}

/**
 * (4) The service hop — where traces fragment if you forget one line.
 *
 * `propagation.inject` writes the W3C `traceparent` header from the active context. The
 * receiving service calls `propagation.extract` on its incoming headers and opens its spans
 * inside `context.with(...)`. Most HTTP client instrumentation does this for you; do it by hand
 * only for clients that are not instrumented.
 */
export async function callDownstream(url: string, payload: unknown): Promise<Record<string, string>> {
  const headers: Record<string, string> = {}
  propagation.inject(context.active(), headers)
  // await fetch(url, { method: 'POST', headers, body: JSON.stringify(payload) })
  return headers
}

if (process.argv[1]?.endsWith('example-agent.js')) {
  handleRequest('How many orders shipped late last week?')
    .then(async (answer) => {
      console.log(answer)
      await shutdownTracing() // flush before exit, or you export nothing
    })
    .catch((error) => {
      trace.getActiveSpan()?.recordException(error)
      process.exitCode = 1
    })
}
