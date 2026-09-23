/**
 * Drop-in OpenTelemetry setup that emits the MEGA Loop trace contract.
 *
 * Set up tracing **before anything else** loads — instrumentations patch modules as they load,
 * so a client created earlier is never traced. `register.ts` does that when preloaded; Next.js
 * calls `setupTracing()` from `instrumentation.ts` instead — see the README.
 *
 * Configures an OTLP exporter (Langfuse / Phoenix / any collector, chosen by env), the W3C
 * `traceparent` propagator so one request stays one trace across services, and the Node
 * auto-instrumentations (HTTP, fetch, Express, NestJS, …) so that propagation happens without
 * hand-written code.
 */

import {
  context,
  diag,
  SpanKind,
  trace,
  type Attributes,
  type Context,
  type Link,
  type Tracer,
} from '@opentelemetry/api'
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node'
import { W3CTraceContextPropagator, type ExportResult } from '@opentelemetry/core'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { registerInstrumentations, type Instrumentation } from '@opentelemetry/instrumentation'
import { resourceFromAttributes } from '@opentelemetry/resources'
import {
  AlwaysOnSampler,
  BatchSpanProcessor,
  NodeTracerProvider,
  ParentBasedSampler,
  SamplingDecision,
  type ReadableSpan,
  type Sampler,
  type SamplingResult,
  type Span,
  type SpanExporter,
  type SpanProcessor,
} from '@opentelemetry/sdk-trace-node'
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from '@opentelemetry/semantic-conventions'

export interface TracingOptions {
  serviceName?: string
  /** A commit sha or release tag. Optional, but it is how a consumer tells builds apart. */
  serviceVersion?: string
  resourceAttributes?: Record<string, string>
  /**
   * Replaces the default, `defaultInstrumentations()`. To add an LLM SDK's instrumentation
   * (OpenInference's), pass `[...defaultInstrumentations(), new OpenAIInstrumentation()]`.
   */
  instrumentations?: Instrumentation[]
}

function langfuseHeaders(): Record<string, string> {
  const publicKey = process.env.LANGFUSE_PUBLIC_KEY?.trim()
  const secretKey = process.env.LANGFUSE_SECRET_KEY?.trim()
  if (!publicKey || !secretKey) return {}
  const token = Buffer.from(`${publicKey}:${secretKey}`).toString('base64')
  return { Authorization: `Basic ${token}` }
}

/** Explicit OTLP settings win; otherwise infer the endpoint from the platform's env vars. */
function endpointAndHeaders(): { url: string; headers: Record<string, string> } {
  const explicit = process.env.OTEL_EXPORTER_OTLP_ENDPOINT?.trim()
  if (explicit) return { url: `${explicit.replace(/\/$/, '')}/v1/traces`, headers: {} }

  const langfuseHost = process.env.LANGFUSE_HOST?.trim()
  if (langfuseHost) {
    return {
      url: `${langfuseHost.replace(/\/$/, '')}/api/public/otel/v1/traces`,
      headers: langfuseHeaders(),
    }
  }

  const phoenixHost = (process.env.PHOENIX_HOST ?? 'http://localhost:6006').trim()
  return { url: `${phoenixHost.replace(/\/$/, '')}/v1/traces`, headers: {} }
}

/** A processor that only keeps books: nothing to flush, nothing to shut down but its own maps. */
abstract class Bookkeeper implements SpanProcessor {
  abstract onStart(span: Span, parentContext: Context): void

  onEnd(_span: ReadableSpan): void {}

  forceFlush(): Promise<void> {
    return Promise.resolve()
  }

  shutdown(): Promise<void> {
    return Promise.resolve()
  }
}

/**
 * Spans a processor remembers until they end. A span that never ends — an abandoned stream, a
 * forgotten `end()` — would otherwise be held for the life of the process, so the oldest go first.
 */
const MAX_TRACKED = 10_000

function remember<K, V>(map: Map<K, V>, key: K, value: V, onEvict?: (key: K, value: V) => void): void {
  if (!map.has(key) && map.size >= MAX_TRACKED) {
    const [oldestKey, oldest] = map.entries().next().value as [K, V]
    map.delete(oldestKey)
    onEvict?.(oldestKey, oldest)
  }
  map.set(key, value)
}

/**
 * Maps every open span to the entry span of its request in this process.
 *
 * A framework (NestJS's HTTP server span, Next.js's `BaseServer.handleRequest`) opens the root
 * before your handler runs, so a span the handler opens is a child — and MEGA Loop reads the
 * request from the root. `onStart` is the one place the SDK hands out the root while it is still
 * writable. Entries are per span, not per trace: one process can serve two requests of the same
 * trace at once (a route calling its own server, a gateway fanning out), each with its own entry.
 */
class EntrySpanRegistry extends Bookkeeper {
  private readonly entryOfSpan = new Map<string, Span>()
  private readonly waiters = new Map<string, Array<() => void>>()

  onStart(span: Span, parentContext: Context): void {
    const parent = trace.getSpanContext(parentContext)
    // A remote parent means the true root lives upstream; this service's first span is still
    // where its own request arrived, and seating it there is harmless.
    const inherited = parent && !parent.isRemote ? this.entryOfSpan.get(parent.spanId) : undefined
    remember(this.entryOfSpan, span.spanContext().spanId, inherited ?? span, (spanId, entry) => {
      if (entry.spanContext().spanId === spanId) this.release(spanId)
    })
  }

  override onEnd(span: ReadableSpan): void {
    const { spanId } = span.spanContext()
    const entry = this.entryOfSpan.get(spanId)
    this.entryOfSpan.delete(spanId)
    // Every processor's onEnd runs in this same tick, so by the time a waiter resumes, the batch
    // processor after this one has queued the span and a flush will send it.
    if (entry?.spanContext().spanId === spanId) this.release(spanId)
  }

  /** The entry span of the request `spanId` belongs to, while that span is open. */
  entryOf(spanId: string): Span | undefined {
    return this.entryOfSpan.get(spanId)
  }

  /**
   * Resolves when every entry of `traceId` open in this process has ended — at once if none is.
   * By trace, not by span: Next.js runs `after()` in a context whose active span has already
   * ended, so the span no longer leads to its entry, while the trace id still does.
   */
  ended(traceId: string): Promise<void> {
    // A descendant can outlive its entry and still point at it; only an entry still mapped to
    // itself is open.
    const open = new Set(
      [...this.entryOfSpan.values()].filter((entry) => {
        const { traceId: t, spanId } = entry.spanContext()
        return t === traceId && this.entryOfSpan.get(spanId) === entry
      }),
    )
    return Promise.all(
      [...open].map(
        (entry) =>
          new Promise<void>((resolve) => {
            const { spanId } = entry.spanContext()
            const list = this.waiters.get(spanId) ?? []
            list.push(resolve)
            this.waiters.set(spanId, list)
          }),
      ),
    ).then(() => undefined)
  }

  private release(spanId: string): void {
    this.waiters.get(spanId)?.forEach((resolve) => resolve())
    this.waiters.delete(spanId)
  }

  override shutdown(): Promise<void> {
    this.entryOfSpan.clear()
    this.waiters.forEach((list) => list.forEach((resolve) => resolve()))
    this.waiters.clear()
    return Promise.resolve()
  }
}

/**
 * The attributes MEGA Loop reads a kind from — OpenInference's, and the foreign families it maps
 * at ingest. Pinned against the validator's contract by `tests/test_node_kit_contract.py`.
 */
const KIND_KEYS = [
  'openinference.span.kind',
  'gen_ai.operation.name',
  'llm.request.type',
  'traceloop.span.kind',
  'langfuse.observation.type',
]

/**
 * Labels a span that reaches export without any kind `CHAIN` — the HTTP server, Nest's handler, a
 * database client — since a kindless span is skipped by every kind-filtering detector. Deciding at
 * export, not at start, is what leaves alone a kind an SDK or your code sets after the span opens:
 * MEGA Loop maps a foreign kind only when no OpenInference kind is present.
 */
class KindDefaultExporter implements SpanExporter {
  constructor(private readonly inner: SpanExporter) {}

  export(spans: ReadableSpan[], done: (result: ExportResult) => void): void {
    this.inner.export(spans.map(withDefaultKind), done)
  }

  shutdown(): Promise<void> {
    return this.inner.shutdown()
  }

  forceFlush(): Promise<void> {
    return this.inner.forceFlush?.() ?? Promise.resolve()
  }
}

function withDefaultKind(span: ReadableSpan): ReadableSpan {
  if (KIND_KEYS.some((key) => span.attributes[key] !== undefined)) return span
  // An ended span is read-only; a view over it with one more attribute is what gets exported.
  const attributes = { ...span.attributes, 'openinference.span.kind': 'CHAIN' }
  return Object.create(span, { attributes: { value: attributes } }) as ReadableSpan
}

/** The `gen_ai.operation.name` values MEGA Loop reads as a model call (LLM or EMBEDDING). */
const MODEL_CALL_OPERATIONS = ['chat', 'text_completion', 'generate_content', 'embeddings']

/**
 * The model calls in flight, by span id, so the sampler can ask whether a new span's parent is
 * one. The active span cannot answer that itself: OpenInference puts a wrapper in the context that
 * hides the attributes, and sets the LLM kind only after the span starts. So OpenInference's spans
 * are kept from the start, and the kind is read when a child is about to be created.
 */
class ModelCallSpans extends Bookkeeper {
  private readonly open = new Map<string, Span>()

  onStart(span: Span): void {
    if (span.instrumentationScope.name.startsWith('@arizeai/openinference') || isModelCall(span)) {
      remember(this.open, span.spanContext().spanId, span)
    }
  }

  override onEnd(span: ReadableSpan): void {
    this.open.delete(span.spanContext().spanId)
  }

  has(spanId: string): boolean {
    const span = this.open.get(spanId)
    return span !== undefined && isModelCall(span)
  }

  override shutdown(): Promise<void> {
    this.open.clear()
    return Promise.resolve()
  }
}

function isModelCall(span: Span): boolean {
  const kind = span.attributes['openinference.span.kind']
  const operation = String(span.attributes['gen_ai.operation.name'] ?? '')
  return kind === 'LLM' || kind === 'EMBEDDING' || MODEL_CALL_OPERATIONS.includes(operation)
}

/**
 * Records every span except the transport of a model call: the HTTP/gRPC client span an LLM SDK
 * opens inside its own model-call span is an empty duplicate of it. One decision here covers every
 * transport instrumentation. Calls between your own services keep their client span — it is what
 * carries `traceparent`.
 */
class SkipModelCallTransport implements Sampler {
  private readonly fallback = new ParentBasedSampler({ root: new AlwaysOnSampler() })

  shouldSample(
    parentContext: Context,
    traceId: string,
    name: string,
    kind: SpanKind,
    attributes: Attributes,
    links: Link[],
  ): SamplingResult {
    const parent = trace.getSpanContext(parentContext)
    if (kind === SpanKind.CLIENT && parent && modelCalls.has(parent.spanId)) {
      return { decision: SamplingDecision.NOT_RECORD }
    }
    return this.fallback.shouldSample(parentContext, traceId, name, kind, attributes, links)
  }

  toString(): string {
    return 'SkipModelCallTransport'
  }
}

/**
 * The Node auto-instrumentations, minus the spans nothing can use.
 *
 * - Express middleware and route layers: one empty span per `jsonParser`, guard and handler. They
 *   outnumber the useful spans and trip the signal-density check (`S2`) on any Nest or Express
 *   app. Express 5 (Nest 11) routes through the `router` package, which emits them again.
 * - OpenTelemetry's own OpenAI instrumentation: it records `gen_ai.*` without the messages, and
 *   next to OpenInference's (which writes the `llm.*` messages MEGA Loop reads) it would add a
 *   second span per model call.
 * - `net` and `dns`: empty spans under every request.
 */
export function defaultInstrumentations(): Instrumentation[] {
  return getNodeAutoInstrumentations({
    '@opentelemetry/instrumentation-express': {
      // ExpressLayerType's values; the enum's package is not one the kit asks you to install.
      ignoreLayersType: ['middleware', 'request_handler', 'router'] as never,
    },
    '@opentelemetry/instrumentation-router': { enabled: false },
    '@opentelemetry/instrumentation-openai': { enabled: false },
    '@opentelemetry/instrumentation-net': { enabled: false },
    '@opentelemetry/instrumentation-dns': { enabled: false },
  })
}

// On the global object, not in module variables: a bundler (Next.js builds `instrumentation.ts`
// and each route separately) can load this file twice. A route's copy would otherwise hold an
// empty registry while the provider fills the other one, and no provider at all to flush.
const shared = globalThis as Record<symbol, unknown>

const REGISTRY_KEY = Symbol.for('mega-loop.trace-kit.entry-spans')
const entrySpans = (shared[REGISTRY_KEY] ??= new EntrySpanRegistry()) as EntrySpanRegistry
const MODEL_CALLS_KEY = Symbol.for('mega-loop.trace-kit.model-calls')
const modelCalls = (shared[MODEL_CALLS_KEY] ??= new ModelCallSpans()) as ModelCallSpans

/**
 * The provider `setupTracing()` built, kept so `flushTracing()` and `shutdownTracing()` can
 * reach it.
 *
 * `provider.register()` installs the provider as the *delegate* of the API's internal
 * `ProxyTracerProvider`, and `trace.getTracerProvider()` hands back that proxy — which has no
 * `shutdown`. Going through the API to flush is therefore a silent no-op; hold the real one.
 */
const PROVIDER_KEY = Symbol.for('mega-loop.trace-kit.provider')

function activeProvider(): NodeTracerProvider | undefined {
  return shared[PROVIDER_KEY] as NodeTracerProvider | undefined
}

export function setupTracing(options: TracingOptions = {}): Tracer {
  const serviceName = options.serviceName ?? 'agent'
  if (activeProvider()) return trace.getTracer(serviceName)

  const attributes: Record<string, string> = {
    [ATTR_SERVICE_NAME]: serviceName,
    ...(options.serviceVersion ? { [ATTR_SERVICE_VERSION]: options.serviceVersion } : {}),
    ...options.resourceAttributes,
  }

  const { url, headers } = endpointAndHeaders()
  const provider = new NodeTracerProvider({
    resource: resourceFromAttributes(attributes),
    // Replaces the default sampler, so OTEL_TRACES_SAMPLER is not read; it records everything else.
    sampler: new SkipModelCallTransport(),
    // The bookkeepers run before the batch processor, so a span is indexed before it is queued.
    spanProcessors: [
      entrySpans,
      modelCalls,
      new BatchSpanProcessor(new KindDefaultExporter(new OTLPTraceExporter({ url, headers }))),
    ],
  })

  // Without an explicit propagator, cross-service calls start new traces instead of continuing
  // this one — the fragmentation MEGA Loop cannot use.
  provider.register({ propagator: new W3CTraceContextPropagator() })
  shared[PROVIDER_KEY] = provider

  // Installing the instrumentation packages does nothing until they are registered here — and
  // without the HTTP/fetch ones, no `traceparent` is sent or read, so every service is a root.
  registerInstrumentations({
    tracerProvider: provider,
    instrumentations: options.instrumentations ?? defaultInstrumentations(),
  })

  diag.info(`tracing configured: service=${serviceName} endpoint=${url}`)
  return trace.getTracer(serviceName)
}

/**
 * Put the user's request on the root span of the current trace — the one field MEGA Loop cannot
 * work without. Call it from inside the request (a handler, an interceptor, a route); it finds
 * the root even when a framework opened it. Returns false when no trace is active here, which
 * almost always means tracing was set up after the framework loaded.
 */
export function setRequestInput(input: string, kind: 'CHAIN' | 'AGENT' = 'CHAIN'): boolean {
  const entry = currentEntry()
  if (!entry) return false
  entry.setAttribute('openinference.span.kind', kind)
  entry.setAttribute('input.value', input)
  return true
}

/** The answer the user got, on the same root span. Call it before the response is sent. */
export function setRequestOutput(output: string): boolean {
  const entry = currentEntry()
  if (!entry) return false
  entry.setAttribute('output.value', output)
  return true
}

function currentEntry(): Span | undefined {
  const active = trace.getSpanContext(context.active())
  return active ? entrySpans.entryOf(active.spanId) : undefined
}

/**
 * Send what the batch still holds — for a serverless handler, which can be frozen as soon as it
 * responds.
 *
 * `waitForRequest` is for Next.js `after()`: Next runs those callbacks before it ends its own root
 * span, the one carrying the request, so the flush first waits for that span (up to `timeoutMs`,
 * for a stream the client abandoned). Never pass it from code that runs before the response: the
 * root ends only after the handler returns, so the wait would always run out.
 */
export async function flushTracing({
  waitForRequest = false,
  timeoutMs = 5_000,
}: { waitForRequest?: boolean; timeoutMs?: number } = {}): Promise<void> {
  const active = waitForRequest ? trace.getSpanContext(context.active()) : undefined
  if (active) {
    let timer: NodeJS.Timeout | undefined
    await Promise.race([
      entrySpans.ended(active.traceId),
      new Promise<void>((resolve) => (timer = setTimeout(resolve, timeoutMs))),
    ])
    clearTimeout(timer)
  }
  await activeProvider()?.forceFlush()
}

/** Flush before a short-lived process exits, or nothing is ever exported. Safe to call twice. */
export async function shutdownTracing(): Promise<void> {
  const provider = activeProvider()
  delete shared[PROVIDER_KEY]
  await provider?.shutdown()
}
