"""Exit codes and report shape — what CI and the calling agent actually read."""

from __future__ import annotations

import json
from pathlib import Path

from trace_validator.cli import EXIT_CANNOT_GRADE, EXIT_NOT_READY, EXIT_OK, main

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def test_the_good_asset_exits_zero(capsys) -> None:
    code = main(["--file", str(ASSETS / "good-trace.json")])
    assert code == EXIT_OK
    assert "entry_seatable" in capsys.readouterr().out


def test_the_broken_asset_exits_one_and_prints_a_fix_for_every_failure(capsys) -> None:
    code = main(["--file", str(ASSETS / "broken-trace.json")])
    assert code == EXIT_NOT_READY

    out = capsys.readouterr().out
    assert "entry_missing" in out
    # Every reported failure line is followed by an instruction — a hard fail must be actionable.
    failure_lines = [ln for ln in out.splitlines() if ln.strip().startswith(("✗", "!"))]
    assert failure_lines
    for line in failure_lines:
        assert out.splitlines()[out.splitlines().index(line) + 1].strip().startswith("→")


def test_a_missing_file_is_cannot_grade_not_not_ready(capsys) -> None:
    """Two different problems, two different exit codes: "your traces are wrong" and "I could
    not look at your traces" call for completely different next steps."""
    code = main(["--file", str(ASSETS / "no-such-file.json")])
    assert code == EXIT_CANNOT_GRADE
    assert "Cannot read traces" in capsys.readouterr().err


def test_json_output_is_machine_readable(capsys) -> None:
    main(["--file", str(ASSETS / "broken-trace.json"), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["verdict"] == "entry_missing"
    assert payload["below"] == 1
    assert payload["fixes"], "a failing run must name at least one fix"
    assert all("fix" in f for f in payload["traces"][0]["failures"])


def test_verify_traffic_is_dropped_by_default(tmp_path: Path, capsys) -> None:
    """MEGA Loop excludes its own verification re-runs at ingest; grading them would judge
    traffic the product never sees."""
    trace = [
        {
            "span_id": "v1",
            "trace_id": "verify",
            "name": "verify run",
            "span_kind": "CHAIN",
            "start_time": "2026-08-05T10:00:00Z",
            "end_time": "2026-08-05T10:00:01Z",
            "attributes": {"openinference.span.kind": "CHAIN", "mega.verify": "1"},
        }
    ]
    path = tmp_path / "verify.json"
    path.write_text(json.dumps(trace), encoding="utf-8")

    assert main(["--file", str(path)]) == EXIT_CANNOT_GRADE  # nothing left to grade
    assert main(["--file", str(path), "--keep-verify-traffic"]) == EXIT_NOT_READY
    capsys.readouterr()


def test_last_trims_on_trace_boundaries(capsys) -> None:
    """A reader pages in whole pages and overshoots; `--last` binds here, not in the pager.

    Trimming inside the pager would cut a trace in half, and the missing root would then be
    reported as a fault in the developer's instrumentation — a fault we invented.
    """
    from tests.conftest import span

    from trace_validator.cli import keep_first_traces

    spans = [
        span(span_id="a1", trace_id="t1"),
        span(span_id="b1", trace_id="t2"),
        span(span_id="a2", trace_id="t1"),  # t1 continues after t2 started
        span(span_id="c1", trace_id="t3"),
    ]

    kept = keep_first_traces(spans, 2)
    assert {s.trace_id for s in kept} == {"t1", "t2"}
    assert [s.span_id for s in kept] == ["a1", "b1", "a2"], "each kept trace stays whole"

    assert keep_first_traces(spans, 0) == spans, "0 means no limit"
    assert keep_first_traces(spans, 99) == spans
