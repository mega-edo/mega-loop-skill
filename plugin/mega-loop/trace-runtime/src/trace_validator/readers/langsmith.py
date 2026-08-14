"""LangSmith — runs, queried by project.

LangSmith models a trace as a tree of *runs*, and exposes far less of the OpenInference surface
than the other two: no model column, no token columns on the query projection. Those checks
simply do not fire, which is correct — the validator reports what it can see and never invents a
verdict for what it cannot.

What it does see is the part that matters most: the run tree. Fragmentation (M2) and the missing
entry input (R1) are both visible here, and they are the two failures that actually stop MEGA
Loop from working.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from trace_validator.readers import ReaderError, as_text, require_env

_BASE_URL = "https://api.smith.langchain.com"
_PAGE_LIMIT = 100
_MAX_PAGES = 20
_SELECT = [
    "trace_id",
    "id",
    "parent_run_id",
    "name",
    "start_time",
    "end_time",
    "run_type",
    "status",
    "error",
    "extra",
    "inputs",
    "outputs",
]


class LangSmithReader:
    def __init__(
        self, *, project: str = "default", since_hours: int = 24, timeout: float = 30.0
    ) -> None:
        self.api_key = require_env(
            "LANGSMITH_API_KEY", hint="Settings → API Keys in LangSmith (lsv2_…)."
        )
        self.base_url = _BASE_URL
        self.project = project
        self.since_hours = since_hours
        self.timeout = timeout

    def fetch(self, *, last: int, trace_id: str | None) -> list[dict[str, Any]]:
        since = datetime.now(tz=UTC) - timedelta(hours=self.since_hours)
        raw: list[dict[str, Any]] = []
        seen_traces: set[str] = set()

        with httpx.Client(
            base_url=self.base_url, headers={"x-api-key": self.api_key}, timeout=self.timeout
        ) as client:
            session_id = self._resolve_project(client)
            cursor: str | None = None
            for _ in range(_MAX_PAGES):
                body = self._query(client, session_id, since, cursor)
                runs = body.get("runs") or []
                if not runs:
                    break
                for run in runs:
                    normalized = self._to_raw(run)
                    if trace_id and normalized["trace_id"] != trace_id:
                        continue
                    raw.append(normalized)
                    seen_traces.add(normalized["trace_id"])
                if not trace_id and len(seen_traces) >= last:
                    break
                cursor = body.get("cursors", {}).get("next") or body.get("next_cursor")
                if not cursor:
                    break
        return raw

    def _resolve_project(self, client: httpx.Client) -> str:
        """A UUID is used as-is; anything else is looked up as a project name."""
        if _looks_like_uuid(self.project):
            return self.project
        response = client.get("/api/v1/sessions", params={"name": self.project})
        if response.status_code in (401, 403):
            raise ReaderError("LangSmith rejected LANGSMITH_API_KEY.")
        response.raise_for_status()
        sessions = response.json()
        if not sessions:
            raise ReaderError(
                f"LangSmith has no project named {self.project!r}. Pass --project with the name "
                "shown in the LangSmith UI."
            )
        return str(sessions[0]["id"])

    def _query(
        self, client: httpx.Client, session_id: str, since: datetime, cursor: str | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session": [session_id],
            "limit": _PAGE_LIMIT,
            "start_time": since.isoformat(),
            "select": _SELECT,
        }
        if cursor:
            payload["cursor"] = cursor
        response = client.post("/api/v1/runs/query", json=payload)
        if response.status_code in (401, 403):
            raise ReaderError("LangSmith rejected LANGSMITH_API_KEY.")
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    @staticmethod
    def _to_raw(run: dict[str, Any]) -> dict[str, Any]:
        extra = run.get("extra") or {}
        metadata = extra.get("metadata") if isinstance(extra, dict) else None
        attributes: dict[str, Any] = dict(metadata) if isinstance(metadata, dict) else {}

        # LangSmith keeps I/O as structured columns rather than attributes; surface them under
        # the OpenInference keys so R1 can see the entry input.
        if run.get("inputs") is not None:
            attributes.setdefault("input.value", as_text(run.get("inputs")))
        if run.get("outputs") is not None:
            attributes.setdefault("output.value", as_text(run.get("outputs")))

        errored = str(run.get("status") or "").lower() == "error" or bool(run.get("error"))
        return {
            "span_id": run.get("id") or "",
            "trace_id": run.get("trace_id") or "",
            "parent_id": run.get("parent_run_id") or "",
            "name": run.get("name") or "",
            "start_time": run.get("start_time"),
            "end_time": run.get("end_time") or run.get("start_time"),
            "span_kind": str(run.get("run_type") or "").upper(),
            "status_code": "ERROR" if errored else "OK",
            "status_message": as_text(run.get("error")) if run.get("error") else "",
            "attributes": attributes,
        }


def _looks_like_uuid(value: str) -> bool:
    parts = value.split("-")
    return len(parts) == 5 and all(all(c in "0123456789abcdefABCDEF" for c in p) for p in parts)
