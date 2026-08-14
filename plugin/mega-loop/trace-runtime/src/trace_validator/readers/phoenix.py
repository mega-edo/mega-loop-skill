"""Phoenix — native OpenInference, so the reader barely maps anything.

Phoenix stores the OpenInference attributes verbatim, which makes it the cheapest platform to
read and the best one to develop against: what you see in Phoenix is what MEGA Loop sees. The
only real work is that Phoenix returns attributes nested, while the contract is written in flat
dotted keys — `span.flatten` handles that.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from trace_validator.readers import ReaderError, require_env

_PAGE_LIMIT = 1000
_MAX_PAGES = 20


class PhoenixReader:
    def __init__(
        self, *, project: str = "default", since_hours: int = 24, timeout: float = 30.0
    ) -> None:
        self.host = require_env(
            "PHOENIX_HOST",
            hint="Set it to your Phoenix URL (self-hosted default: http://localhost:6006).",
        ).rstrip("/")
        # Cloud requires a key; a self-hosted instance is usually open, so this stays optional.
        self.api_key = os.environ.get("PHOENIX_API_KEY", "").strip()
        self.project = project
        self.since_hours = since_hours
        self.timeout = timeout

    def fetch(self, *, last: int, trace_id: str | None) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        since = datetime.now(tz=UTC) - timedelta(hours=self.since_hours)
        params: dict[str, Any] = {"limit": _PAGE_LIMIT, "start_time": since.isoformat()}

        raw: list[dict[str, Any]] = []
        seen_traces: set[str] = set()
        with httpx.Client(base_url=self.host, headers=headers, timeout=self.timeout) as client:
            cursor: str | None = None
            for _ in range(_MAX_PAGES):
                body = self._get(client, {**params, **({"cursor": cursor} if cursor else {})})
                spans = body.get("data") or []
                if not spans:
                    break
                for span in spans:
                    normalized = self._to_raw(span)
                    if trace_id and normalized["trace_id"] != trace_id:
                        continue
                    raw.append(normalized)
                    seen_traces.add(normalized["trace_id"])
                if not trace_id and len(seen_traces) >= last:
                    break
                cursor = body.get("next_cursor")
                if not cursor:
                    break
        return raw

    def _get(self, client: httpx.Client, params: dict[str, Any]) -> dict[str, Any]:
        response = client.get(f"/v1/projects/{self.project}/spans", params=params)
        if response.status_code in (401, 403):
            raise ReaderError(
                "Phoenix rejected the request. Set PHOENIX_API_KEY if this instance requires one."
            )
        if response.status_code == 404:
            raise ReaderError(
                f"Phoenix has no project named {self.project!r}. Pass --project with the name "
                "shown in the Phoenix UI."
            )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    @staticmethod
    def _to_raw(span: dict[str, Any]) -> dict[str, Any]:
        context = span.get("context") or {}
        return {
            "span_id": context.get("span_id") or span.get("span_id") or "",
            "trace_id": context.get("trace_id") or span.get("trace_id") or "",
            "parent_id": span.get("parent_id") or "",
            "name": span.get("name") or "",
            "start_time": span.get("start_time"),
            "end_time": span.get("end_time") or span.get("start_time"),
            "span_kind": span.get("span_kind") or "",
            "status_code": span.get("status_code") or "OK",
            "status_message": span.get("status_message") or "",
            "attributes": span.get("attributes") or {},
        }
