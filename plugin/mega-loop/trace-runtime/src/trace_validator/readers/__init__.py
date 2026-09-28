"""Platform readers — three thin adapters, one checker.

Each reader's whole job is to turn a platform's API response into the raw dicts
`span.normalize` accepts. None of them decide anything: the contract is judged after
normalization, identically for every platform, which is why adding a fourth platform later costs
a reader and nothing else.

Where a platform has its own vocabulary (Langfuse especially), the reader hands the foreign keys
through *unchanged* and lets `span.lower_attributes` map them. That keeps one mapping table
instead of one per reader, and it means the validator exercises the same lowering MEGA Loop runs.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol


class ReaderError(RuntimeError):
    """A reader could not fetch — missing credentials, bad project, or an API refusal.

    Always carries what to do about it: the developer is mid-setup, and "401 Unauthorized" with
    no next step is where they give up.
    """


class Reader(Protocol):
    def fetch(self, *, last: int, trace_id: str | None) -> list[dict[str, Any]]:
        """Raw span dicts, newest window first. ``trace_id`` narrows to a single trace."""
        ...


def require_env(name: str, *alternates: str, hint: str) -> str:
    """The first of ``name``/``alternates`` that is set, or a ReaderError naming all of them.

    Alternates exist because a platform renames its variables and both spellings stay in the wild:
    the reader has to accept whatever the app that WROTE the traces was configured with, or a
    project is asked to set the same URL twice under two names.
    """
    for candidate in (name, *alternates):
        value = os.environ.get(candidate, "").strip()
        if value:
            return value
    names = " or ".join((name, *alternates))
    raise ReaderError(f"{names} is not set. {hint}")


def as_text(value: Any) -> str:
    """Platform I/O fields are sometimes strings, sometimes JSON objects. Keep both readable."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def build(platform: str, **kwargs: Any) -> Reader:
    """Resolve a platform name to its reader. Imports lazily so `--file` needs no httpx."""
    if platform == "langfuse":
        from trace_validator.readers.langfuse import LangfuseReader

        return LangfuseReader(**kwargs)
    if platform == "phoenix":
        from trace_validator.readers.phoenix import PhoenixReader

        return PhoenixReader(**kwargs)
    if platform == "langsmith":
        from trace_validator.readers.langsmith import LangSmithReader

        return LangSmithReader(**kwargs)
    raise ReaderError(f"Unknown platform {platform!r}. Use langfuse, phoenix, or langsmith.")
