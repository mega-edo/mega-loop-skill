"""Step 3 — the same agent, instrumented with the kit. The business logic is untouched.

    export PHOENIX_HOST=http://localhost:16006   # your dev stack's Phoenix
    python3 orders_agent_instrumented.py
    python3 -m trace_validator.cli --platform phoenix --project instrumented-demo --last 1

Compare with `orders_agent_naive.py`: the same four functions, the same call graph. What changed
is where the question is written down, and that every span says what kind of thing it is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# In your own project you copy `kits/python/instrument.py` next to your code and just
# `from instrument import setup_tracing`. This example imports it in place so the repo has
# one copy of the kit rather than two that can drift.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "kits" / "python"))

from instrument import setup_tracing  # noqa: E402  (path set up above)

tracer = setup_tracing(
    service_name="orders-agent",
    service_version="1.0.0",
    resource_attributes={"openinference.project.name": "instrumented-demo"},
)


def handle_request(question: str) -> str:
    """One request, one root span, carrying the question."""
    with tracer.start_as_current_span("POST /orders") as root:
        root.set_attribute("openinference.span.kind", "CHAIN")  # → M1_kind_present
        root.set_attribute("input.value", question)  # → R1_entry_seat / R1b_clean_root

        plan = plan_step(question)
        rows = query_orders(plan["window"])
        answer = summarize(question, rows)

        root.set_attribute("output.value", answer)
        return answer


def plan_step(question: str) -> dict[str, str]:
    with tracer.start_as_current_span("plan") as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.model_name", "claude-sonnet-5")
        span.set_attribute("input.value", question)
        span.set_attribute("llm.input_messages.0.message.role", "user")
        span.set_attribute("llm.input_messages.0.message.content", question)
        plan = {"window": "Q3"}
        span.set_attribute("llm.output_messages.0.message.role", "assistant")
        span.set_attribute("llm.output_messages.0.message.content", json.dumps(plan))
        span.set_attribute("llm.token_count.prompt", 96)
        span.set_attribute("llm.token_count.completion", 12)
        span.set_attribute("llm.token_count.total", 108)
        span.set_attribute("output.value", json.dumps(plan))
        return plan


def query_orders(window: str) -> list[dict[str, object]]:
    with tracer.start_as_current_span("query_orders") as span:
        span.set_attribute("openinference.span.kind", "TOOL")
        span.set_attribute("input.value", json.dumps({"window": window}))
        rows: list[dict[str, object]] = [{"id": 1, "late": True}, {"id": 2, "late": True}]
        span.set_attribute("output.value", json.dumps(rows))
        return rows


def summarize(question: str, rows: list[dict[str, object]]) -> str:
    with tracer.start_as_current_span("summarize") as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.model_name", "claude-sonnet-5")
        span.set_attribute("input.value", json.dumps(rows))
        span.set_attribute("llm.input_messages.0.message.role", "user")
        span.set_attribute("llm.input_messages.0.message.content", question)
        answer = f"{sum(bool(row['late']) for row in rows)} orders shipped late."
        span.set_attribute("llm.output_messages.0.message.role", "assistant")
        span.set_attribute("llm.output_messages.0.message.content", answer)
        span.set_attribute("llm.token_count.prompt", 143)
        span.set_attribute("llm.token_count.completion", 9)
        span.set_attribute("llm.token_count.total", 152)
        span.set_attribute("output.value", answer)
        return answer


if __name__ == "__main__":
    from opentelemetry import trace

    print(handle_request("How many orders shipped late in Q3?"))
    trace.get_tracer_provider().shutdown()  # flush before exit, or nothing is exported
