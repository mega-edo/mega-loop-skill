from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trace_validator.span import Span, normalize

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def load_asset(name: str) -> list[Span]:
    raw = json.loads((ASSETS / name).read_text(encoding="utf-8"))
    return [normalize(item) for item in raw]


@pytest.fixture
def good_trace() -> list[Span]:
    return load_asset("good-trace.json")


@pytest.fixture
def broken_trace() -> list[Span]:
    return load_asset("broken-trace.json")


def span(**overrides: Any) -> Span:
    """A minimal well-formed span, so a test can state only the field it is about."""
    base: dict[str, Any] = {
        "span_id": "s1",
        "trace_id": "t1",
        "name": "step",
        "parent_id": "",
        "span_kind": "CHAIN",
        "status_code": "OK",
        "start_time": "2026-08-05T10:00:00Z",
        "end_time": "2026-08-05T10:00:01Z",
        "attributes": {},
    }
    return normalize({**base, **overrides})
