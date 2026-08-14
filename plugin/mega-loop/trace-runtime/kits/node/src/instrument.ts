/**
 * Drop-in OpenTelemetry setup that emits the MEGA Loop trace contract.
 *
 * Import this file **before anything else** — instrumentations patch modules as they load, so
 * a client created earlier is never traced:
 *
 *     node --import ./dist/instrument.js dist/server.js
 *
 * or, in ESM source, keep it the first import of your entrypoint.
 *
 * Configures an OTLP exporter (Langfuse / Phoenix / any collector, chosen by env), the W3C
 * `traceparent` propagator so one request stays one trace across services, and OpenInference
 * auto-instrumentation for whichever LLM SDKs are installed.
 */

import { diag, trace, type Tracer } from '@opentelemetry/api'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { W3CTraceContextPropagator } from '@opentelemetry/core'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { BatchSpanProcessor, NodeTracerProvider } from '@opentelemetry/sdk-trace-node'
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from '@opentelemetry/semantic-conventions'

export interface TracingOptions {
  serviceName?: string
  /** A commit sha or release tag. Optional, but it is how a consumer tells builds apart. */
  serviceVersion?: string
  resourceAttributes?: Record<string, string>
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

/**
 * The provider `setupTracing()` built, kept so `shutdownTracing()` can flush it.
 *
 * `provider.register()` installs the provider as the *delegate* of the API's internal
 * `ProxyTracerProvider`, and `trace.getTracerProvider()` hands back that proxy — which has no
 * `shutdown`. Going through the API to flush is therefore a silent no-op; hold the real one.
 */
let activeProvider: NodeTracerProvider | undefined

export function setupTracing(options: TracingOptions = {}): Tracer {
  const serviceName = options.serviceName ?? 'agent'
  const attributes: Record<string, string> = {
    [ATTR_SERVICE_NAME]: serviceName,
    ...(options.serviceVersion ? { [ATTR_SERVICE_VERSION]: options.serviceVersion } : {}),
    ...options.resourceAttributes,
  }

  const { url, headers } = endpointAndHeaders()
  const provider = new NodeTracerProvider({
    resource: resourceFromAttributes(attributes),
    spanProcessors: [new BatchSpanProcessor(new OTLPTraceExporter({ url, headers }))],
  })

  // Without an explicit propagator, cross-service calls start new traces instead of continuing
  // this one — the fragmentation MEGA Loop cannot use.
  provider.register({ propagator: new W3CTraceContextPropagator() })
  activeProvider = provider

  diag.info(`tracing configured: service=${serviceName} endpoint=${url}`)
  return trace.getTracer(serviceName)
}

/** Flush before a short-lived process exits, or nothing is ever exported. Safe to call twice. */
export async function shutdownTracing(): Promise<void> {
  const provider = activeProvider
  activeProvider = undefined
  await provider?.shutdown()
}
