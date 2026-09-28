/**
 * Next.js calls `register()` once per server process, before any route runs — its equivalent of
 * preloading `register.js`. The edge runtime has no Node SDK, so it is skipped there.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== 'nodejs') return
  const { setupTracing } = await import('./tracing/instrument')
  setupTracing({ serviceName: process.env.OTEL_SERVICE_NAME ?? 'next-app' })
}
