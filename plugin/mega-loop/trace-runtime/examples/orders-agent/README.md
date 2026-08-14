# orders-agent — the same agent, three ways

The discrimination proof for the validator: the same four functions in all three files, and the
only thing that changes is the tracing. `tests/test_source.py` grades the naive and instrumented
versions to confirm a rule catches one and clears the other.

| File | Tracing | Graded |
|---|---|---|
| `orders_agent.py` | none | nothing to grade |
| `orders_agent_naive.py` | hand-written, plausible, wrong keys | `entry_missing` · exit 1 |
| `orders_agent_instrumented.py` | the kit | `entry_seatable` · exit 0 |

## Run all three

```bash
python3 -m pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

# mega-loop dev stack — Phoenix is the `observability` service, host port 16006
export PHOENIX_HOST=http://localhost:16006
# standalone Phoenix instead: export PHOENIX_HOST=http://localhost:6006

python3 orders_agent.py               # works, emits nothing
python3 orders_agent_naive.py         # → Phoenix project `broken-demo`
python3 orders_agent_instrumented.py  # → Phoenix project `instrumented-demo`
```

Then, from the repo root:

```bash
python3 -m trace_validator.cli --platform phoenix --project broken-demo       --last 1 ; echo "exit=$?"
python3 -m trace_validator.cli --platform phoenix --project instrumented-demo --last 1 ; echo "exit=$?"
```

Give the batch exporter a couple of seconds between running an agent and grading it — spans are
flushed on shutdown, but Phoenix still has to ingest them.

## What actually differs

`orders_agent_naive.py` is not careless code. It has spans, they nest, the exporter works, and
Phoenix renders a clean tree. Three things make it unusable, none of which raise an error:

1. the question is stored as `user_question` — a key nothing reads, so the request has no input;
2. the step spans carry no `openinference.span.kind`, so every kind-filtering detector skips them;
3. nothing says so until you grade it.

`orders_agent_instrumented.py` changes only those: `input.value` on the root, and a real kind on
each span. The business logic is untouched — diff them and see.

> In a real project you would not hand-write the `llm.*` attributes at all. The OpenInference
> instrumentors emit them for you; `plan` and `summarize` spell them out here only because this
> example has no actual model call to instrument. See
> [`kits/python/example_autoinstrumented.py`](../../kits/python/example_autoinstrumented.py) for
> the shape you should copy — five hand-written attributes, graded clean.
