"""A correctly-traced request: one root, nested steps, a sub-agent, and a service hop.

Run it and the platform should show **one** trace shaped like this:

    POST /chat                CHAIN   ← root, carries input.value
    ├─ plan                   LLM
    ├─ query_orders           TOOL
    ├─ research_agent         AGENT   ← a sub-agent, not a new trace
    │  └─ search_docs         RETRIEVER
    └─ answer                 LLM

Then:

    python scripts/validate_traces.py --platform <yours> --last 5

The point of this file is not the fake model calls — it is the four places where a request
normally fragments, each handled explicitly and commented.
"""

from __future__ import annotations

import json
from typing import Any

from instrument import setup_tracing
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import Status, StatusCode

tracer = setup_tracing(service_name="orders-agent", service_version="1.4.2")


def handle_request(question: str) -> str:
    """The request. Everything below it belongs to this one span."""
    with tracer.start_as_current_span("POST /chat") as root:
        root.set_attribute("openinference.span.kind", "CHAIN")
        # (1) The root carries the user's question. Without this the trace cannot be replayed,
        #     and every other thing you do right stops mattering.
        root.set_attribute("input.value", question)

        plan = plan_step(question)
        rows = query_orders(plan["window"])
        context = research_agent(question)
        answer = answer_step(question, rows, context)

        root.set_attribute("output.value", answer)
        return answer


def plan_step(question: str) -> dict[str, Any]:
    with tracer.start_as_current_span("plan") as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.model_name", "claude-sonnet-5")
        span.set_attribute("input.value", question)

        # (2) Messages are indexed from 0, contiguously, with standard roles.
        span.set_attribute("llm.input_messages.0.message.role", "system")
        span.set_attribute("llm.input_messages.0.message.content", "You answer order questions.")
        span.set_attribute("llm.input_messages.1.message.role", "user")
        span.set_attribute("llm.input_messages.1.message.content", question)

        plan = {"window": "last_week"}
        span.set_attribute("llm.output_messages.0.message.role", "assistant")
        span.set_attribute("llm.output_messages.0.message.content", "I will query the orders.")
        span.set_attribute(
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.name", "query_orders"
        )
        span.set_attribute(
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments",
            json.dumps(plan),  # must parse as a JSON object
        )
        span.set_attribute("llm.token_count.prompt", 412)
        span.set_attribute("llm.token_count.completion", 38)
        span.set_attribute("llm.token_count.total", 450)
        span.set_attribute("output.value", "I will query the orders.")
        return plan


def query_orders(window: str) -> list[dict[str, Any]]:
    with tracer.start_as_current_span("query_orders") as span:
        span.set_attribute("openinference.span.kind", "TOOL")
        span.set_attribute("input.value", json.dumps({"window": window}))
        try:
            rows = [{"id": 1, "late": True}, {"id": 2, "late": True}]
        except Exception as exc:
            # (3) A failure is reported as a failure. Returning {"error": ...} with an OK status
            #     is the single most common way a real bug becomes invisible to detection.
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        span.set_attribute("output.value", json.dumps(rows))
        return rows


def research_agent(question: str) -> str:
    """A sub-agent is a span inside this trace, never a trace of its own."""
    with tracer.start_as_current_span("research_agent") as span:
        span.set_attribute("openinference.span.kind", "AGENT")
        span.set_attribute("input.value", question)
        docs = search_docs(question)
        span.set_attribute("output.value", docs)
        return docs


def search_docs(query: str) -> str:
    with tracer.start_as_current_span("search_docs") as span:
        span.set_attribute("openinference.span.kind", "RETRIEVER")
        span.set_attribute("input.value", query)
        span.set_attribute("retrieval.documents.0.document.content", "Shipping SLA is 3 days.")
        span.set_attribute("retrieval.documents.0.document.score", 0.91)
        return "Shipping SLA is 3 days."


def answer_step(question: str, rows: list[dict[str, Any]], context: str) -> str:
    with tracer.start_as_current_span("answer") as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.model_name", "claude-sonnet-5")
        span.set_attribute("input.value", json.dumps({"rows": rows, "context": context}))
        span.set_attribute("llm.input_messages.0.message.role", "user")
        span.set_attribute("llm.input_messages.0.message.content", question)
        answer = f"{len(rows)} orders shipped late."
        span.set_attribute("llm.output_messages.0.message.role", "assistant")
        span.set_attribute("llm.output_messages.0.message.content", answer)
        span.set_attribute("llm.token_count.prompt", 486)
        span.set_attribute("llm.token_count.completion", 21)
        span.set_attribute("llm.token_count.total", 507)
        span.set_attribute("output.value", answer)
        return answer


def call_downstream_service(url: str, payload: dict[str, Any]) -> dict[str, str]:
    """(4) The service hop. This is where traces fragment if you forget one line.

    `inject` writes the W3C `traceparent` header from the *current* span. The receiving service
    calls `extract` on its incoming headers and opens its spans under that context — see
    references/context-propagation.md. Most HTTP client auto-instrumentation does this for you;
    do it by hand only for clients that are not instrumented.
    """
    headers: dict[str, str] = {}
    inject(headers)
    # requests.post(url, json=payload, headers=headers)
    return headers


if __name__ == "__main__":
    print(handle_request("How many orders shipped late last week?"))
    trace.get_tracer_provider().shutdown()  # flush before exit, or you export nothing
