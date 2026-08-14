"""A JSON file of spans — the offline path.

This is what makes the validator testable without a platform, runnable in CI, and usable by
someone who exported a single trace to send us. It accepts the shapes people actually have:
a bare array, or an object with the spans under `spans`, `data` or `runs`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trace_validator.readers import ReaderError

_SPAN_KEYS = ("spans", "data", "runs")


class FileReader:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def fetch(self, *, last: int, trace_id: str | None) -> list[dict[str, Any]]:
        if not self.path.exists():
            raise ReaderError(f"No such file: {self.path}")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReaderError(f"{self.path} is not valid JSON: {exc}") from exc

        spans = _spans_from(payload)
        if trace_id:
            spans = [s for s in spans if str(s.get("trace_id") or "") == trace_id]
        return spans


def _spans_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [s for s in payload if isinstance(s, dict)]
    if isinstance(payload, dict):
        for key in _SPAN_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [s for s in value if isinstance(s, dict)]
    raise ReaderError(
        "Expected a JSON array of spans, or an object with them under 'spans', 'data' or 'runs'."
    )
