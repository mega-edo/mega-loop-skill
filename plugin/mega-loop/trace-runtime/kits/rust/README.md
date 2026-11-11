# Rust kit

Rust has no OpenInference auto-instrumentation, so this kit is the plumbing plus helpers: you open
every LLM / TOOL / AGENT / RETRIEVER span yourself, and `instrument.rs` keeps the kinds and
attribute names exact.

## 1. Install

```bash
cargo add opentelemetry@0.33.1 --features trace
cargo add opentelemetry_sdk@0.33.1 --features trace
cargo add opentelemetry-otlp@0.33.1 --no-default-features --features trace,http-proto,reqwest-blocking-client
cargo add serde_json
```

Pin the three `opentelemetry*` crates to one version: they move in lockstep and mixed versions do
not share a global provider. 0.33.1 is what this kit is tested against; check crates.io for a
newer one before you pin.

## 2. Point it at your platform

The same variables as the Python and Node kits:

```bash
# Langfuse — OTLP over HTTP with basic auth
export LANGFUSE_BASE_URL=https://cloud.langfuse.com   # LANGFUSE_HOST also works (pre-v4 name)
export LANGFUSE_PUBLIC_KEY=pk-lf-…
export LANGFUSE_SECRET_KEY=sk-lf-…

# or Phoenix (the default with nothing set is http://localhost:6006)
export PHOENIX_HOST=http://localhost:6006

# or any OTel collector (wins over both of the above)
export OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318
```

## 3. Wire it up

Copy `src/instrument.rs` into your crate and call `setup_tracing` first thing in `main`. Keep the
provider and shut it down before exit:

```rust
let provider = instrument::setup_tracing("orders-agent", Some(env!("CARGO_PKG_VERSION")))?;
// ...
provider.shutdown()?;
```

Then wrap each request in a root span that carries the request:

```rust
let root = instrument::start("POST /chat", "CHAIN", &opentelemetry::Context::new());
instrument::input(&root, &question);          // ← the one line you cannot skip
let answer = run_agent(&root, &question).await;
instrument::output(&root, &answer);
instrument::end(&root);
```

Pass `&root` (or the context of the step you are in) down to every step. The helpers:

| Helper | For |
|---|---|
| `start(name, kind, parent)` | any span; the kind is set at creation |
| `tool(parent, name, &args, \|cx\| …)` | a tool call: input, output, and ERROR when it returns `Err` |
| `record_llm(&cx, &LlmCall { … })` | a model call: messages, tool calls, the tools offered, tokens |
| `input` / `output` / `fail` / `end` | the rest; `input` is kept verbatim (the root's is replayed), other long text is clipped to `MAX_VALUE_CHARS` |
| `start_at` / `end_at` | a step recorded after it ran, from a log with its own timestamps |
| `inject` / `extract` | the W3C `traceparent` headers for a service hop |

`src/example.rs` is a full request — a model call that offers tools, a tool on a blocking thread,
a sub-agent with a retriever, and a service hop. The numbered comments mark where Rust requests
fragment.

## 4. Check it

```bash
cargo run --example example_agent             # sends one trace to localhost:6006
uv run ../../scripts/validate_traces.py --platform phoenix --last 1
```

Or offline: `cargo test` writes the example's spans to `target/example-trace.json` in the flat
shape the validator reads, then

```bash
uv run ../../scripts/validate_traces.py --file target/example-trace.json
```

`--source .` cannot grade a Rust repository — it parses Python only. Grade real traces.

## Gotchas

- **Every span is a root, or a step is missing.** Context does not follow work onto
  `tokio::spawn` or `spawn_blocking`. Move the parent `Context` into the task and open the span
  with it, or wrap the future with `opentelemetry::context::FutureExt::with_context`. Do not rely
  on `Context::current()` inside a spawned task.
- **Nothing exported.** A CLI exits before the batch processor flushes. Call
  `provider.shutdown()` (or `force_flush()` after each request in a long-lived process).
- **A panic about blocking inside a runtime.** A simple (synchronous) processor with the blocking
  HTTP client runs the export on the calling tokio worker. Use the batch processor
  `setup_tracing` installs; it exports from its own thread.
- **Model calls inside another process.** When the model runs behind a subprocess or a sidecar
  (an agent harness, a CLI), the calls are not in your process to wrap. If it writes a session
  log with timestamps, replay each call into an LLM span with `start_at` / `end_at` under the
  span that started the session; otherwise record what crosses the boundary (tool calls and the
  final result) and say what is unmeasured.
