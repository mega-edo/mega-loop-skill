"""`validate-traces` — fetch, grade, print, exit.

Exit status is the contract with CI and with the calling agent: 0 means every graded trace
reached `entry_seatable`, 1 means at least one did not, 2 means we could not grade at all
(bad credentials, no traces, unreadable file). The third case is separate on purpose — "your
traces are wrong" and "I could not look at your traces" call for completely different next steps.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from trace_validator.checks import grade_sample, group_by_trace
from trace_validator.readers import ReaderError, build
from trace_validator.readers.file import FileReader
from trace_validator.report import render, render_json, render_source, render_source_json
from trace_validator.source import scan
from trace_validator.span import Span, normalize

EXIT_OK, EXIT_NOT_READY, EXIT_CANNOT_GRADE = 0, 1, 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate-traces",
        description="Check that your traces are shaped the way MEGA Loop needs.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--platform", choices=("langfuse", "phoenix", "langsmith"), help="where to read traces from"
    )
    source.add_argument("--file", help="a JSON file of exported spans (no credentials needed)")
    source.add_argument(
        "--source",
        help="a repository to read instead of traces — grades what the source decides, before "
        "the app has run",
    )
    parser.add_argument("--last", type=int, default=20, help="how many recent traces to grade")
    parser.add_argument("--trace", help="grade a single trace by id")
    parser.add_argument("--project", default="default", help="Phoenix / LangSmith project name")
    parser.add_argument(
        "--since-hours", type=int, default=24, help="how far back to look (default 24)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--keep-verify-traffic",
        action="store_true",
        help="keep MEGA Loop's own verification re-runs (excluded by default, as ingest does)",
    )
    return parser


def keep_first_traces(spans: list[Span], last: int) -> list[Span]:
    """Trim to the first ``last`` distinct traces, keeping each one whole.

    A reader pages in whole pages, so it usually overshoots — it must, since truncating a page
    mid-trace would grade a fragment and report the missing root as a fault in the developer's
    code. The trim therefore happens here, on trace boundaries, never inside the pager.
    """
    if last <= 0:
        return spans
    wanted: list[str] = []
    for span in spans:
        if span.trace_id not in wanted:
            wanted.append(span.trace_id)
        if len(wanted) > last:
            break
    keep = set(wanted[:last])
    return [s for s in spans if s.trace_id in keep]


def load(args: argparse.Namespace) -> list[Span]:
    if args.file:
        reader = FileReader(args.file)
    elif args.platform == "langfuse":
        reader = build("langfuse", since_hours=args.since_hours)  # type: ignore[assignment]
    else:
        reader = build(  # type: ignore[assignment]
            args.platform, project=args.project, since_hours=args.since_hours
        )
    raw = reader.fetch(last=args.last, trace_id=args.trace)
    spans = [normalize(item) for item in raw]
    if not args.keep_verify_traffic:
        spans = [s for s in spans if not s.is_verify_traffic()]
    # A file is read whole — you asked for that file. A platform is a firehose, so `--last` binds.
    if not args.file and not args.trace:
        spans = keep_first_traces(spans, args.last)
    return spans


def _grade_source(args: argparse.Namespace) -> int:
    """`--source` path. Same three exit codes, one meaning short of the trace grader's.

    Exit 1 here means "the source already decides something is wrong", never "your traces are
    fine" — a clean board is not a pass, because most of the contract is not decidable from source
    at all. `render_source` says so; the exit code cannot, which is why it is worth saying twice.
    """
    root = Path(args.source)
    if not root.is_dir():
        print(f"Cannot read source: {root} is not a directory", file=sys.stderr)
        return EXIT_CANNOT_GRADE

    grade = scan(root)
    print(render_source_json(grade) if args.json else render_source(grade))
    if not grade.scanned:
        return EXIT_CANNOT_GRADE
    return EXIT_OK if grade.ok else EXIT_NOT_READY


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.source:
        return _grade_source(args)
    try:
        spans = load(args)
    except ReaderError as exc:
        print(f"Cannot read traces: {exc}", file=sys.stderr)
        return EXIT_CANNOT_GRADE

    traces = group_by_trace(spans)
    sample = grade_sample(traces)
    checked = len(traces)

    print(render_json(sample, checked=checked) if args.json else render(sample, checked=checked))
    if not sample.traces:
        return EXIT_CANNOT_GRADE
    return EXIT_OK if sample.ok_count == len(sample.traces) else EXIT_NOT_READY


if __name__ == "__main__":
    raise SystemExit(main())
