"""Step 1 — the starting point: a working agent that emits no traces at all.

Run it and you get an answer. MEGA Loop sees nothing, because there is nothing to see.

    python3 orders_agent.py
"""

from __future__ import annotations


def handle_request(question: str) -> str:
    plan = plan_step(question)
    rows = query_orders(plan["window"])
    return summarize(question, rows)


def plan_step(question: str) -> dict[str, str]:
    return {"window": "Q3"}


def query_orders(window: str) -> list[dict[str, object]]:
    return [{"id": 1, "late": True}, {"id": 2, "late": True}]


def summarize(question: str, rows: list[dict[str, object]]) -> str:
    return f"{sum(bool(row['late']) for row in rows)} orders shipped late."


if __name__ == "__main__":
    print(handle_request("How many orders shipped late in Q3?"))
