"""Step 2 — the trap: tracing added by hand, the way most people first do it.

Nothing here is careless. There are spans, they nest, the exporter works, and the Phoenix UI
looks completely normal. Every mistake below is silent.

    export PHOENIX_HOST=http://localhost:16006   # your dev stack's Phoenix
    python3 orders_agent_naive.py

Then grade it and watch it fail:

    python3 -m trace_validator.cli --platform phoenix --project broken-demo --last 5
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

PHOENIX = os.environ.get("PHOENIX_HOST", "http://localhost:6006").rstrip("/")

provider = TracerProvider(
    resource=Resource.create(
        {"service.name": "orders-agent", "openinference.project.name": "broken-demo"}
    )
)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{PHOENIX}/v1/traces")))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("orders-agent")


def handle_request(question: str) -> str:
    with tracer.start_as_current_span("orders.ask") as root:
        root.set_attribute("openinference.span.kind", "CHAIN")
        # Feels right. Reads fine. Nothing in MEGA Loop looks at a key called `user_question`,
        # so as far as the product is concerned this request has no input at all.
        root.set_attribute("user_question", question)

        plan = plan_step(question)
        rows = query_orders(plan["window"])
        answer = summarize(question, rows)

        root.set_attribute("final_answer", answer)
        return answer


def plan_step(question: str) -> dict[str, str]:
    # No span kind — invisible to every kind-filtering detector, silently.
    with tracer.start_as_current_span("plan") as span:
        span.set_attribute("prompt", question)
        return {"window": "Q3"}


def query_orders(window: str) -> list[dict[str, object]]:
    with tracer.start_as_current_span("query_orders") as span:
        span.set_attribute("sql", f"SELECT * FROM orders WHERE quarter = '{window}'")
        rows: list[dict[str, object]] = [{"id": 1, "late": True}, {"id": 2, "late": True}]
        span.set_attribute("row_count", len(rows))
        return rows


def summarize(question: str, rows: list[dict[str, object]]) -> str:
    with tracer.start_as_current_span("summarize") as span:
        answer = f"{sum(bool(row['late']) for row in rows)} orders shipped late."
        span.set_attribute("text", answer)
        return answer


if __name__ == "__main__":
    print(handle_request("How many orders shipped late in Q3?"))
    provider.shutdown()  # flush before exit, or nothing is exported
