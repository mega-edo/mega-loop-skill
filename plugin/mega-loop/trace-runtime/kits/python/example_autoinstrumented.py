"""The version you should actually write: let the SDK emit the LLM spans.

`example_agent.py` sets every OpenInference attribute by hand, because its job is to show what
the contract *is*. This file shows what you write once you know it — which is much less.

The OpenInference instrumentor wraps your LLM client and emits a complete `LLM` span for every
call: kind, model, input and output messages, token counts, invocation parameters. You never
type any of those keys.

What is left for you is the part no library can infer:

    1. a root span for the request, carrying `input.value`   ← the one line that cannot be automated
    2. `openinference.span.kind` on your own tool / retriever / agent spans
    3. ERROR status when a step fails

Run it:

    pip install openai openinference-instrumentation-openai \\
                opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
    PHOENIX_HOST=http://localhost:6006 OPENAI_API_KEY=… python example_autoinstrumented.py
"""

from __future__ import annotations

import json
import os

from instrument import setup_tracing
from openai import OpenAI
from opentelemetry.trace import Status, StatusCode

# setup_tracing installs the OpenInference instrumentors for whichever LLM SDKs are present, so
# this must run before the client is built.
tracer = setup_tracing(service_name="orders-agent", service_version="1.4.2")

client = OpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None)
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def handle_request(question: str) -> str:
    """One request, one root span. This function is the only place the contract needs you."""
    with tracer.start_as_current_span("POST /chat") as root:
        root.set_attribute("openinference.span.kind", "CHAIN")
        root.set_attribute("input.value", question)  # ← nothing can infer this for you

        rows = query_orders("last_week")
        answer = ask_model(question, rows)

        root.set_attribute("output.value", answer)
        return answer


def ask_model(question: str, rows: list[dict[str, object]]) -> str:
    """No span, no attributes, no token counting — the instrumentor emits all of it."""
    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You answer questions about the orders database."},
            {"role": "user", "content": f"{question}\nRows: {json.dumps(rows)}"},
        ],
    )
    return completion.choices[0].message.content or ""


def query_orders(window: str) -> list[dict[str, object]]:
    """Your own code still needs its kind and its status — a library cannot know what this is."""
    with tracer.start_as_current_span("query_orders") as span:
        span.set_attribute("openinference.span.kind", "TOOL")
        span.set_attribute("input.value", json.dumps({"window": window}))
        try:
            rows: list[dict[str, object]] = [{"id": 1, "late": True}, {"id": 2, "late": True}]
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        span.set_attribute("output.value", json.dumps(rows))
        return rows


if __name__ == "__main__":
    from opentelemetry import trace

    print(handle_request("How many orders shipped late last week?"))
    trace.get_tracer_provider().shutdown()
