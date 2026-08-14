# The trace spec

What MEGA Loop needs from a trace, and why. Everything here is enforced by
`scripts/validate_traces.py` — if the validator and this page ever disagree, the validator is
right, because it is generated from the same constants the product uses.

## The one-sentence version

**One user request produces one trace, whose root span carries the request text, and every span
declares what kind of thing it is.**

Everything below is a consequence of that sentence.

## 1. One request = one trace

MEGA Loop reads the question from the **root span** — the single span with no parent. That is
where it learns what the user asked, and it is the input it replays when it verifies a fix.

```
✓ correct                          ✗ fragmented
trace A                            trace A          trace B
└─ POST /chat        (root)        └─ POST /chat    └─ retriever.search
   ├─ plan           LLM              └─ plan          └─ rerank
   ├─ search         RETRIEVER
   └─ answer         LLM
```

The right-hand shape is what you get by default when a request crosses a service, a queue, or a
background task without carrying its trace context. Each piece looks fine on its own; together
they are unusable, because no single trace holds the question *and* the answer.

Fixing this is the subject of [context-propagation.md](context-propagation.md), and it is the
hardest part of instrumenting honestly. It is worth doing first.

## 2. The root span carries the request

The root should be:

- **the only** parentless span in the trace,
- of kind `CHAIN` or `AGENT` — not `LLM` (an LLM call is a step inside the request, not the
  request), and
- carrying the user's text in `input.value`.

If MEGA Loop cannot find a re-runnable input, the trace is graded `entry_missing` and no fix can
be verified against it. This is the only check with no workaround.

There is a fallback: an input message on an `LLM`, `TOOL` or `RETRIEVER` span can seat the entry
instead. Note the omission — a message on an `AGENT` or `CHAIN` span **does not count**. Set
`input.value` on the root and you never need to think about this again.

## 3. Every span declares its kind

`openinference.span.kind`, uppercase, one of:

`LLM` · `TOOL` · `RETRIEVER` · `AGENT` · `CHAIN` · `EMBEDDING` · `RERANKER` · `EVALUATOR` ·
`GUARDRAIL`

A span with an unrecognised kind is skipped by every kind-filtering detector — silently. No
error, no warning, just weaker results that look like MEGA Loop not finding anything. That
silence is why this check exists.

Per-kind required keys: [span-kinds.md](span-kinds.md).

## 4. Failures are reported as failures

When a step fails, set the span status to `ERROR`. Returning `{"success": false, "message":
"..."}` with an OK status means the failure reaches only the quality stream, at reduced fidelity,
instead of the deterministic error path.

Conversely: `status_message` belongs **only** on an errored span. OTel reserves the status
description for errors.

## 5. Indices run 0..n-1

Messages, retrieved documents and tool calls are written as indexed keys. The indices must be
contiguous. A filtered list has to be re-indexed before it is emitted, or the detectors
undercount.

```
✓ llm.input_messages.0.message.role      ✗ llm.input_messages.0.message.role
  llm.input_messages.1.message.role        llm.input_messages.2.message.role
```

Tool-call indices are counted **within each output message**, not across the span.

## 6. Message roles are standard

`system` · `user` · `assistant` · `tool` · `function`

## 7. Every step records what it was given and what it returned

`input.value` / `output.value`, or the message families, on every **LLM**, **TOOL** and
**RETRIEVER** span.

A step with neither can be seen to have run and cannot be blamed. The trace shows the shape of a
failure but not which step produced it, so root-cause analysis stops at "something in here". The
common version of this is instrumenting the model call carefully and leaving the tools around it
bare — and tools are where most failures actually are.

Either direction on its own is enough. Both is better.

## 8. LLM spans report their token counts

`llm.token_count.prompt` and `llm.token_count.completion` on every LLM span.

Without them, cost per run, budgets and cost-regression attribution are all blind — a run that
doubles in price looks identical to one that did not. Most SDK instrumentors record these for
you; a hand-rolled client usually has the counts sitting in the provider response and drops them.

Only flagged on spans that returned something substantial: a span with almost no output may
honestly have ~0 completion tokens.

## 9. Something in the trace has to be work

Detectors filter on **LLM**, **AGENT**, **TOOL** and **RETRIEVER**. Everything else is structure
they walk past — including CHAIN.

So "every span has a kind" and "there is something here to detect" are different statements, and
the gap between them is easy to miss: a platform that assigns a default kind makes a trace look
fully classified. Langfuse types a bare OTLP span as `span`, which lowers to CHAIN, so a service
that never labelled anything still grades as fully classified — and no detector examines a single
span of it.

Label the agent's steps: the model call **LLM**, the things it calls **TOOL** or **RETRIEVER**,
a sub-agent **AGENT**.

If a request genuinely runs no agent — a CRUD or health endpoint — then it is not agent traffic.
Tracing it is not wrong, but it costs storage and dilutes the sample the product grades.

## 10. Spans a reader can use, and not many more

There is no span budget, and no rule against detail. But a span with **neither a kind nor any
text** offers a reader nothing: it cannot be filtered on, cannot be reconstructed from, and
cannot be blamed.

They arrive in bulk rather than one at a time. Auto-instrumentation for a database driver, an
HTTP client, a cache or a queue emits one span per round-trip, and a request that loops over a
query can turn a six-step agent into a sixty-span trace. Nothing is malformed; the six steps are
simply hard to find, and you pay ingest and retention for the other fifty-four.

The validator warns — never fails — once more than half a trace is spans of that shape. Two ways
out, and either is fine:

- turn that layer's instrumentation off for this service, or
- give those spans a kind and some text, if they really are part of the story.

Keep the spans that describe the agent's own steps. This is about what a reader can see, not
about being frugal.

## You do not have to emit OpenInference directly

MEGA Loop lowers several dialects onto these keys before anything reads them, and the validator
applies the same lowering, so you are graded on what the product sees:

| If you emit | It becomes |
|---|---|
| `gen_ai.*` (OpenTelemetry GenAI semconv) | the OpenInference equivalents |
| `traceloop.span.kind` (OpenLLMetry) | `openinference.span.kind` |
| `langfuse.observation.*` | kind, model, I/O, token counts |
| `llm.request.type` | `openinference.span.kind` |

Native OpenInference always wins where both are present. If you are choosing, choose
OpenInference — it is the only dialect that needs no translation.

## What a passing grade means

`entry_seatable` means **MEGA Loop can read this trace**. It is necessary, not sufficient:
whether a particular failure becomes a bug MEGA Loop can fix also depends on the failure. The
validator will not claim otherwise, and neither should we.
