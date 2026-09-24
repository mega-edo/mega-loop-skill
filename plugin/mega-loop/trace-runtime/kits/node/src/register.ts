/**
 * Turns tracing on as a side effect of being loaded — the file to preload:
 *
 *     node --import ./dist/register.js dist/server.js       # ESM
 *     node --require ./dist/register.js dist/main.js       # CommonJS (NestJS default)
 *
 * or make `import './register.js'` the first line of the entrypoint. `instrument.js` only exports
 * functions, so preloading it instead configures nothing. The service name comes from
 * `OTEL_SERVICE_NAME`, the standard variable, so one build can run as several services.
 */

import { register } from 'node:module'
import { pathToFileURL } from 'node:url'

import { setupTracing, shutdownTracing } from './instrument.js'

// An ES module binds another module's exports when it imports it, so patching `http` afterwards
// never reaches `import { createServer } from 'node:http'` — no server span, no `traceparent`
// read, one trace per service. This hook lets the instrumentations wrap ES imports as they load.
// It resolves from the entrypoint's directory, where the app's node_modules are.
register(
  '@opentelemetry/instrumentation/hook.mjs',
  pathToFileURL(process.argv[1] ?? `${process.cwd()}/`),
)

setupTracing({
  serviceName: process.env.OTEL_SERVICE_NAME,
  serviceVersion: process.env.OTEL_SERVICE_VERSION,
})

// A server stopped by its orchestrator gets SIGTERM, and the spans still in the batch are lost
// unless they are flushed first. The app's own handlers, if it has any, decide when it exits;
// with none, the process ends the way the signal would have ended it.
for (const signal of ['SIGTERM', 'SIGINT'] as const) {
  process.once(signal, () => {
    void shutdownTracing().finally(() => {
      if (process.listenerCount(signal) === 0) process.kill(process.pid, signal)
    })
  })
}
