# Python kit

## 1. Install

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
# plus the instrumentor(s) for the SDKs you actually use:
pip install openinference-instrumentation-openai
pip install openinference-instrumentation-anthropic
pip install openinference-instrumentation-langchain     # LangChain / LangGraph
```

Also install the auto-instrumentation for your web framework and HTTP client — it is what makes
`traceparent` propagate without you writing a line:

```bash
pip install opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-httpx
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

Copy `instrument.py` into your project and call it **first**, before your app builds any clients
— the instrumentors patch libraries at import time.

```python
from instrument import setup_tracing

tracer = setup_tracing(service_name="orders-agent", service_version="1.4.2")
```

`service_version` is optional and worth setting: it is the standard OpenTelemetry field for
"which build produced this trace".

Then wrap each user request in a root span that carries the question:

```python
with tracer.start_as_current_span("POST /chat") as root:
    root.set_attribute("openinference.span.kind", "CHAIN")
    root.set_attribute("input.value", question)      # ← the one line you cannot skip
    answer = run_agent(question)
    root.set_attribute("output.value", answer)
```

`example_agent.py` is a full request — nested steps, a sub-agent, a tool that reports failure
properly, and a service hop with `traceparent` injection. Read it before adapting your own code;
the comments mark the four places requests normally fragment.

## 4. Check it

```bash
python scripts/validate_traces.py --platform langfuse --last 50
```

Fix whatever it prints, and re-run until you see **✓ entry_seatable**.

Validate traces that crossed a real service or queue boundary — a single-process smoke test
passes whether or not propagation works, which is exactly the bug you are trying to rule out.

## Gotchas

- **Nothing exported.** A short-lived script exits before the batch processor flushes. Call
  `trace.get_tracer_provider().shutdown()` before returning.
- **Every span is a root.** Context was lost. Background tasks and thread pools do not carry it
  by default — see `references/context-propagation.md`.
- **The framework already traces for me.** Good; keep it. This kit adds the OpenInference
  attributes on top, and the two compose.
