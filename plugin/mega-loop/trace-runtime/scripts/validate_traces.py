#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pydantic>=2.6", "httpx>=0.27"]
# ///
"""Run the validator without installing it.

The skill invokes this path, because a developer mid-setup should not have to install a package
to find out why their traces are wrong. Run it with `uv run`, which reads the inline script
metadata above and provides pydantic/httpx in a throwaway environment — nothing is installed into
the developer's own project:

    uv run scripts/validate_traces.py --platform langfuse --last 50
    uv run scripts/validate_traces.py --file assets/good-trace.json

No uv? Fall back to `pip install pydantic httpx` once, then `python scripts/validate_traces.py …`.
Either way both paths call the same `cli.main`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trace_validator.cli import main  # noqa: E402  (path set up above)

if __name__ == "__main__":
    raise SystemExit(main())
