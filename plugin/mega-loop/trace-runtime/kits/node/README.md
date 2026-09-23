# Node kit

Two files to copy into your project:

- `src/instrument.ts` — the setup: exporter, `traceparent` propagator, the Node
  auto-instrumentations, and `setRequestInput` / `setRequestOutput`.
- `src/register.ts` — turns tracing on when it is loaded. This is the file you preload.

Plain Node, Express, Koa and NestJS all use both. Next.js uses `instrument.ts` only, and calls
it from `instrumentation.ts` ([Next.js](#nextjs) below).

## 1. Install

```bash
npm install @opentelemetry/api @opentelemetry/sdk-trace-node \
            @opentelemetry/exporter-trace-otlp-http @opentelemetry/core \
            @opentelemetry/resources @opentelemetry/semantic-conventions \
            @opentelemetry/instrumentation @opentelemetry/auto-instrumentations-node
```

`auto-instrumentations-node` covers HTTP, `fetch`, Express, Koa, Hapi, NestJS, database clients
and more. It is what makes `traceparent` travel between services without hand-written code.
`setupTracing()` registers it as `defaultInstrumentations()`, which drops the spans nothing can use:
Express/router middleware layers and `net`/`dns`. Every span that arrives without a kind is
labelled `CHAIN`; a kind set by an instrumentor or by your code is never overwritten.

The kit also installs its own sampler. It records every span except the HTTP/gRPC request an LLM
SDK makes inside its own model-call span, which only duplicates that span. Because the kit sets the
sampler, `OTEL_TRACES_SAMPLER` is not read; to sample, change `SkipModelCallTransport`'s fallback.
The skipped request still carries a `traceparent`, marked not sampled: if your model endpoint is a
traced service of your own (an LLM gateway), exempt it in the sampler or its spans are dropped.

If you call the OpenAI SDK directly, add the OpenInference instrumentation so LLM spans carry
`llm.*` attributes automatically:

```bash
npm install @arizeai/openinference-instrumentation-openai
```

Pass it in `register.ts`:
`setupTracing({ instrumentations: [...defaultInstrumentations(), new OpenAIInstrumentation()] })`.
If no LLM spans appear in an ES-module app, also call
`openAIInstrumentation.manuallyInstrument(OpenAI)` after importing the SDK.

## 2. Point it at your platform

```bash
# Langfuse
export LANGFUSE_HOST=https://cloud.langfuse.com
export LANGFUSE_PUBLIC_KEY=pk-lf-…
export LANGFUSE_SECRET_KEY=sk-lf-…

# or Phoenix
export PHOENIX_HOST=http://localhost:6006

# or any OTel collector (wins over both of the above)
export OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318

export OTEL_SERVICE_NAME=orders-api   # one name per service
```

## 3. Load it before anything else

Instrumentations patch modules as they load, so a client created earlier is never traced. Preload
`register`:

```bash
node --import ./dist/register.js dist/server.js     # ES modules
node --require ./dist/register.js dist/main.js      # CommonJS
```

or make it the first import of your entrypoint. Preload `register.js`, not `instrument.js`:
`instrument.js` only exports functions, so preloading it sets nothing up.

## 4. Put the request on the root span

MEGA Loop reads the user's request from the trace's **root span**. When a framework handles HTTP,
the root is the server span it opened *before* your code ran, so a span you open in the handler is
a child and does not count. `setRequestInput` finds the real root from anywhere inside the
request:

```ts
import { setRequestInput, setRequestOutput } from './tracing/instrument'

setRequestInput(question)   // ← the one line you cannot skip
const answer = await runAgent(question)
setRequestOutput(answer)
```

It returns `false` when no trace is active, which almost always means tracing loaded after the
framework did.

If your code *is* the entry point (a CLI, a queue consumer, a script), open the root yourself with
`tracer.startActiveSpan`. `src/example-agent.ts` is a full request done that way: nested steps, a
sub-agent, a tool that reports failure properly, and a service hop. Read its four numbered comments
before adapting your own code.

```bash
npm run example
```

## NestJS

1. Copy both files to `src/tracing/`. Nest compiles to CommonJS by default, and the files build
   there unchanged.
2. Make `import './tracing/register'` the **first line** of `src/main.ts`, before `@nestjs/core`,
   or start the app with `node --require ./dist/tracing/register.js dist/main.js`.
3. Seat the request in an interceptor. Apply it to your chat routes, or globally with
   `app.useGlobalInterceptors(...)`:

```ts
@Injectable()
export class RequestTraceInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const body = context.switchToHttp().getRequest<{ body?: { question?: unknown } }>().body
    if (typeof body?.question === 'string') setRequestInput(body.question)
    return next.handle().pipe(
      tap((result) => {
        const answer = (result as { answer?: unknown } | undefined)?.answer
        if (typeof answer === 'string') setRequestOutput(answer)
      }),
    )
  }
}
```

Change `question` and `answer` to your API's field names. The request the trace needs is the one
the user sent, not the prompt your code built from it.

## Next.js

Next.js has its own loading hook and opens its own root span (`POST /api/chat`). App Router on
the Node runtime:

1. Copy `instrument.ts` to `tracing/instrument.ts`. Next does not use `register.ts`.
2. Add `instrumentation.ts` at the project root, next to `app/` (or inside `src/` if you use
   one):

   ```ts
   export async function register(): Promise<void> {
     // The edge runtime has no Node SDK. Routes that run on edge are not traced by this kit.
     if (process.env.NEXT_RUNTIME !== 'nodejs') return
     const { setupTracing } = await import('./tracing/instrument')
     setupTracing({ serviceName: process.env.OTEL_SERVICE_NAME ?? 'next-app' })
   }
   ```

3. Call `setRequestInput` / `setRequestOutput` in the route handler or server action. It reaches
   Next's root span:

   ```ts
   export async function POST(request: Request): Promise<Response> {
     const { question } = await request.json()
     setRequestInput(question)
     const answer = await runAgent(question)
     setRequestOutput(answer)
     return Response.json({ answer })
   }
   ```

`fetch` calls from a route carry `traceparent`, so a downstream service continues the same trace.

**Serverless (Vercel, Lambda).** The function can be frozen as soon as it responds, before the
batch is sent. Flush after the response instead:

```ts
import { after } from 'next/server'
import { flushTracing } from '../../tracing/instrument'

after(() => flushTracing({ waitForRequest: true }))
```

Next runs `after()` callbacks before it ends its own root span, which is the span carrying the
request. `waitForRequest` makes the flush wait for that root to end, for up to 5 s
(`timeoutMs`), before it sends the batch. Pass it only from `after()`: code that runs before the
response would wait out the whole timeout, since the root ends after the handler returns. A
handler that flushes itself before returning calls `flushTracing()` with no options.

## 5. Check it

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/trace-runtime/scripts/validate_traces.py" --platform langfuse --last 50
```

`${CLAUDE_PLUGIN_ROOT}` is the installed mega-loop plugin; the skills fill it in.

Fix whatever it prints, and re-run until you see **✓ entry_seatable**.

Validate traces that crossed a real service or queue boundary. A single-process smoke test passes
whether or not propagation works, which is exactly the bug you are trying to rule out.

## Gotchas

- **Nothing exported.** The process exited before the batch processor flushed. `register.ts`
  flushes on SIGTERM/SIGINT. A script that exits by itself must `await shutdownTracing()` first.
- **Every service is its own trace (ES modules).** An ES module binds `http`'s exports when it
  imports them, so a patch applied later never reaches it. `register.ts` installs OTel's loader
  hook for this. If you preload your own setup instead, keep that hook.
- **Every span is a root.** Context was lost. `provider.register()` enables async-aware context
  propagation. If you replaced the context manager, keep an async-aware one.
- **`startSpan` instead of `startActiveSpan`.** `startSpan` does not make the span current, so
  the next span parents to whatever was current before. Use `startActiveSpan` unless you are
  deliberately building a detached span.

## Maintaining the kit

```bash
npm install && npm test
```

The tests run each setup this README describes against a real app: plain Node across two
services, NestJS and Next.js. Each app exports spans over OTLP to an in-process collector, and
`scripts/validate_traces.py`, the grader the skills use, grades them. Each setup also has a
negative control, the same app without `setRequestInput`, which must fail. That proves the test
can fail. The fixtures have no lockfile and install the newest release in their major range
(`test/fixtures/*/package.json`), so a framework release that breaks the kit fails here first. The
test needs `uv` on `PATH`.
