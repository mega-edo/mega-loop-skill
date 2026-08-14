# Node kit

## 1. Install

```bash
npm install @opentelemetry/api @opentelemetry/sdk-trace-node \
            @opentelemetry/exporter-trace-otlp-http @opentelemetry/core \
            @opentelemetry/resources @opentelemetry/semantic-conventions
```

Add the auto-instrumentation for your framework and HTTP client — it is what makes `traceparent`
propagate without hand-written code:

```bash
npm install @opentelemetry/auto-instrumentations-node
```

If you use OpenAI or Anthropic SDKs directly, add the OpenInference instrumentation so LLM spans
carry `llm.*` attributes automatically:

```bash
npm install @arizeai/openinference-instrumentation-openai
```

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
```

## 3. Wire it up

Copy `src/instrument.ts` into your project and load it **before anything else** — instrumentation
patches modules as they load, so a client created earlier is never traced:

```bash
node --import ./dist/instrument.js dist/server.js
```

Then wrap each user request in a root span that carries the question:

```ts
await tracer.startActiveSpan('POST /chat', async (root) => {
  root.setAttribute('openinference.span.kind', 'CHAIN')
  root.setAttribute('input.value', question)      // ← the one line you cannot skip
  const answer = await runAgent(question)
  root.setAttribute('output.value', answer)
  root.end()
  return answer
})
```

`src/example-agent.ts` is a full request — nested steps, a sub-agent, a tool that reports failure
properly, and a service hop with `traceparent` injection. Read the four numbered comments before
adapting your own code.

```bash
npm run example
```

## 4. Check it

```bash
python scripts/validate_traces.py --platform langfuse --last 50
```

Fix whatever it prints, and re-run until you see **✓ entry_seatable**.

Validate traces that crossed a real service or queue boundary — a single-process smoke test
passes whether or not propagation works, which is exactly the bug you are trying to rule out.

## Gotchas

- **Nothing exported.** The process exited before the batch processor flushed. `await
  shutdownTracing()` first.
- **Every span is a root.** Context was lost. `async_hooks`-based context propagation is enabled
  by `provider.register()`; if you replaced the context manager, keep an async-aware one.
- **`startSpan` instead of `startActiveSpan`.** `startSpan` does not make the span current, so
  the next span parents to whatever was current before. Use `startActiveSpan` unless you are
  deliberately building a detached span.
