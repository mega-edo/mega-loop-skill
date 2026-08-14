"""Langfuse — the observations REST API.

Langfuse stores observations, not OTel spans, so its field names are its own. Rather than
translating them here, the reader re-emits them under the `langfuse.observation.*` keys that
`span.lower_attributes` already knows — the same keys Langfuse's own OTel exporter writes. One
mapping table serves both ingestion routes, and a Langfuse-specific bug shows up in one place.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from trace_validator.readers import ReaderError, as_text, require_env

_PAGE_LIMIT = 100
_MAX_PAGES = 50  # a runaway pager on a busy project is worse than an incomplete sample


class LangfuseReader:
    def __init__(self, *, since_hours: int = 24, timeout: float = 30.0) -> None:
        self.host = require_env(
            "LANGFUSE_HOST",
            hint="Set it to your Langfuse URL, e.g. https://cloud.langfuse.com",
        ).rstrip("/")
        self.public_key = require_env(
            "LANGFUSE_PUBLIC_KEY", hint="Project Settings → API Keys → public key (pk-lf-…)."
        )
        self.secret_key = require_env(
            "LANGFUSE_SECRET_KEY", hint="Project Settings → API Keys → secret key (sk-lf-…)."
        )
        self.since_hours = since_hours
        self.timeout = timeout

    def fetch(self, *, last: int, trace_id: str | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": _PAGE_LIMIT}
        if trace_id:
            params["traceId"] = trace_id
        else:
            since = datetime.now(tz=UTC) - timedelta(hours=self.since_hours)
            params["fromStartTime"] = since.isoformat()

        raw: list[dict[str, Any]] = []
        seen_traces: set[str] = set()
        with httpx.Client(
            base_url=self.host, auth=(self.public_key, self.secret_key), timeout=self.timeout
        ) as client:
            for page in range(1, _MAX_PAGES + 1):
                body = self._get(client, {**params, "page": page})
                observations = body.get("data") or []
                if not observations:
                    break
                for obs in observations:
                    raw.append(self._to_raw(obs))
                    seen_traces.add(str(obs.get("traceId") or ""))
                # Stop once we hold enough whole traces; the last page may overshoot, which is
                # fine — grading an extra trace costs nothing and truncating one costs accuracy.
                if not trace_id and len(seen_traces) >= last:
                    break
                if page >= int((body.get("meta") or {}).get("totalPages") or page):
                    break
        return raw

    def _get(self, client: httpx.Client, params: dict[str, Any]) -> dict[str, Any]:
        response = client.get("/api/public/observations", params=params)
        if response.status_code in (401, 403):
            raise ReaderError(
                "Langfuse rejected the credentials. Check LANGFUSE_PUBLIC_KEY / "
                "LANGFUSE_SECRET_KEY belong to the project you are validating."
            )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    @staticmethod
    def _to_raw(obs: dict[str, Any]) -> dict[str, Any]:
        metadata = obs.get("metadata")
        attributes: dict[str, Any] = {}
        # OTel-forwarded attributes ride in metadata; keep them, they may already be OpenInference.
        if isinstance(metadata, dict):
            nested = metadata.get("attributes")
            attributes.update(nested if isinstance(nested, dict) else metadata)

        attributes["langfuse.observation.type"] = str(obs.get("type") or "")
        for field, key in (
            ("input", "langfuse.observation.input"),
            ("output", "langfuse.observation.output"),
        ):
            if obs.get(field) is not None:
                attributes[key] = as_text(obs.get(field))
        if obs.get("model"):
            attributes["langfuse.observation.model.name"] = obs["model"]

        usage = obs.get("usageDetails") or obs.get("usage")
        if isinstance(usage, dict):
            attributes["langfuse.observation.usage_details"] = {
                "input": usage.get("input", usage.get("promptTokens")),
                "output": usage.get("output", usage.get("completionTokens")),
                "total": usage.get("total", usage.get("totalTokens")),
            }
        if obs.get("environment"):
            attributes["langfuse.environment"] = obs["environment"]

        return {
            "span_id": obs.get("id") or "",
            "trace_id": obs.get("traceId") or "",
            "parent_id": obs.get("parentObservationId") or "",
            "name": obs.get("name") or "",
            "start_time": obs.get("startTime"),
            "end_time": obs.get("endTime") or obs.get("startTime"),
            "status_code": "ERROR" if str(obs.get("level") or "").upper() == "ERROR" else "OK",
            "status_message": obs.get("statusMessage") or "",
            "attributes": attributes,
        }
