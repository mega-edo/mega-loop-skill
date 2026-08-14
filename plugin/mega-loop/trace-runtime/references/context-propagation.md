# Keeping one request in one trace

This is the part that is actually hard. Calling the SDK is a few lines; keeping a request
together as it crosses a function, a service, a queue or a thread is a discipline, and getting it
wrong is the default.

## What goes wrong

A trace is held together by **context** — a small piece of state (trace id + current span id)
that OpenTelemetry keeps alongside your execution. A child span reads it to learn who its parent
is. Lose it, and the next span starts a brand-new trace with no parent.

```
                   context carried              context lost
request ─→ API     trace A                      trace A
        ─→ worker  trace A (child)              trace B  ← new root, no question, no answer
        ─→ tool    trace A (child)              trace C
```

Both look fine in the platform UI: you see spans, they have names, nothing is red. The damage is
only visible when something tries to read the *request* — which is what MEGA Loop does.

The validator reports this as **M2_tree_intact** (a span's parent is not in the trace) or as
**R1b_clean_root** (more than one parentless span).

## In-process: let the SDK do it

Within one process, OpenTelemetry propagates context for you as long as you use the SDK's own
span-creation API and do not hand-roll parents.

```python
with tracer.start_as_current_span("POST /chat") as root:      # ← current span
    root.set_attribute("input.value", question)
    plan = call_model(question)          # spans inside become children automatically
    result = run_tool(plan)
```

Two things break it:

- **Background tasks / thread pools.** Context is per-execution-context. Submitting work to a
  thread pool does not carry it, and the worker's spans become their own trace. See below.
- **Building spans by hand** with an explicit parent you got from somewhere else. If you are
  passing span ids around yourself, you have re-implemented context propagation, and it will
  drift.

### Thread pools — capture on the caller, attach in the worker

This is the most common in-process fragmentation, and it is invisible: the worker's spans look
perfectly healthy, they are just in a different trace.

```python
from concurrent.futures import ThreadPoolExecutor
from opentelemetry import context as otel_context


def in_context(ctx: otel_context.Context, fn):
    """Run `fn` under a captured OTel context — thread pools do not carry one."""

    def run(*args, **kwargs):
        token = otel_context.attach(ctx)
        try:
            return fn(*args, **kwargs)
        finally:
            otel_context.detach(token)

    return run


with tracer.start_as_current_span("POST /ask") as root:
    ctx = otel_context.get_current()          # captured HERE, on the request's thread
    with ThreadPoolExecutor(max_workers=2) as pool:
        docs = pool.submit(in_context(ctx, search_docs), question)
        orders = pool.submit(in_context(ctx, lookup_orders), question)
```

`get_current()` must be called on the **submitting** thread, inside the root span. Calling it
inside the worker returns an empty context, which is the bug you were trying to fix.

For `asyncio`, tasks created with `asyncio.create_task` inherit context automatically; work sent
to an executor via `loop.run_in_executor` does not, and needs the same treatment.

## Across a service boundary: the `traceparent` header

W3C Trace Context defines one header:

```
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
             ^  ^                                ^                ^
             |  trace id (32 hex)                parent span id   flags
             version
```

Inject it on the way out, extract it on the way in. Do not build it by hand — the SDK's
propagator does it correctly, including the flags.

**Python**

```python
from opentelemetry.propagate import inject, extract

# caller
headers = {}
inject(headers)                       # adds traceparent
requests.post(url, json=payload, headers=headers)

# callee (any framework)
ctx = extract(request.headers)
with tracer.start_as_current_span("handle", context=ctx):
    ...
```

**Node**

```ts
import { context, propagation, trace } from '@opentelemetry/api'

// caller
const headers: Record<string, string> = {}
propagation.inject(context.active(), headers)
await fetch(url, { method: 'POST', headers, body })

// callee
const ctx = propagation.extract(context.active(), req.headers)
await context.with(ctx, async () => { /* spans here join the caller's trace */ })
```

Most HTTP frameworks and clients do this automatically once their auto-instrumentation is
installed. Install it before writing any of the above by hand.

## Across a queue

Message brokers do not carry headers for you. Put the `traceparent` in the message payload or its
metadata, and extract it in the consumer:

```python
message = {"payload": data, "traceparent": headers_after_inject.get("traceparent")}
```

This is where fragmentation most often survives a first round of fixes, because the producer and
consumer are usually in different codebases and different heads.

## Sub-agents

A sub-agent is not a new request. Give it an `AGENT` span **inside** the current trace, not a new
root:

```python
with tracer.start_as_current_span("research_agent") as sub:
    sub.set_attribute("openinference.span.kind", "AGENT")
    ...
```

If the sub-agent is a separate service, it is a service boundary — use `traceparent`.

## Checking it

```bash
python scripts/validate_traces.py --platform <yours> --last 50
```

`M2_tree_intact` passing across a sample that includes real multi-service requests is the proof.
A single-service smoke test will pass whether or not propagation works, so make sure the traces
you validate actually crossed the boundary you are worried about.
