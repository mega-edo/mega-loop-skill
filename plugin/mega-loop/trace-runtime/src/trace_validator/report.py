"""Rendering a grade into something a developer can act on.

Two rules shape this file. First, the report is read by someone who is about to edit code, so
every failing line ends in an instruction, not a diagnosis. Second, a sample of fifty traces
usually has three problems, not fifty — so the per-trace detail is capped and the summary groups
by *fix*, ordered by how many traces each one clears.

Output goes to stdout by design: this module is the product of a CLI, not library logging.
"""

from __future__ import annotations

import json
from typing import Any

from trace_validator import contract as C
from trace_validator.checks import SampleGrade, TraceGrade, fix_summary
from trace_validator.source import SourceGrade

_TICK, _CROSS, _WARN = "✓", "✗", "!"

#: Sites printed per finding before the tail is folded into a count. Enough to see the shape of
#: the problem; short enough that a board with several findings still fits on one screen.
_SITES_SHOWN = 5
_MAX_TRACE_DETAIL = 8  # beyond this the per-trace list stops teaching and starts scrolling


def _short(trace_id: str, width: int = 8) -> str:
    return trace_id[:width] + "…" if len(trace_id) > width else trace_id or "<no trace id>"


def _mark(verdict: str) -> str:
    return _CROSS if verdict == "fail" else _WARN


def _plural(count: int, noun: str, plural: str | None = None) -> str:
    """Naive -s pluralisation, with an escape hatch — "fixs" is not a word."""
    if count == 1:
        return f"{count} {noun}"
    return f"{count} {plural or noun + 's'}"


def render_trace(grade: TraceGrade) -> list[str]:
    head = f"trace {_short(grade.trace_id)}"
    if grade.label:
        head += f"  ({grade.label})"
    lines = [f"{head}   verdict: {grade.verdict}"]
    for check in grade.failures():
        evidence = f" — {', '.join(check.evidence)}" if check.evidence else ""
        lines.append(f"  {_mark(check.verdict)} {check.id} — {check.detail}{evidence}")
        lines.append(f"      → {check.fix}")
    return lines


def render(sample: SampleGrade, *, checked: int) -> str:
    """The full report. ``checked`` is how many traces were fetched, gradable or not."""
    if not sample.traces:
        return (
            "No gradable traces found.\n"
            "  → Check that your app has run since instrumentation was added, and that the "
            "platform credentials point at the right project."
        )

    ok = sample.ok_count
    below = len(sample.traces) - ok
    headline = (
        f"Checked {_plural(checked, 'trace')} · "
        f"{_TICK} {ok} entry_seatable · {_CROSS} {below} below"
    )
    lines = [headline, ""]

    failing = [t for t in sample.traces if not t.ok]
    for grade in failing[:_MAX_TRACE_DETAIL]:
        lines += render_trace(grade) + [""]
    if len(failing) > _MAX_TRACE_DETAIL:
        hidden = len(failing) - _MAX_TRACE_DETAIL
        lines += [f"… and {_plural(hidden, 'more trace')} with the same fixes.", ""]

    # With one failing trace the summary would just repeat what was printed directly above it.
    # The grouping earns its space only when it collapses several traces into a shorter list.
    fixes = fix_summary(list(sample.traces))
    if fixes and len(failing) > 1:
        lines.append(
            f"{_plural(len(fixes), 'distinct fix', 'distinct fixes')} "
            f"across {_plural(below, 'trace')}, most-clearing first:"
        )
        for i, entry in enumerate(fixes, start=1):
            lines.append(f"  {i}. {entry['fix']}")
            cleared = _plural(entry["traces"], "trace")
            lines.append(f"     clears {cleared} · {', '.join(entry['checks'])}")
        lines.append("")

    gloss = C.VERDICT_GLOSS.get(sample.verdict, "")
    lines.append(f"Sample verdict: {sample.verdict}" + (f" — {gloss}" if gloss else ""))
    if sample.verdict == "entry_seatable":
        lines.append(
            "This means MEGA Loop can read these traces. Whether a given failure becomes a "
            "bug it can fix also depends on the failure itself."
        )
    lines.append("Reference: references/trace-spec.md")
    return "\n".join(lines)


def render_source(grade: SourceGrade) -> str:
    """The source report. Deliberately ends by naming what it could not answer.

    A developer who reads a clean board here and stops has been misled: the hardest failure this
    skill exists for — one request arriving as several traces — is not visible in source at all.
    """
    if not grade.scanned:
        return (
            "No Python files found to scan.\n"
            "  → Point --source at the repository root, or grade real traces with --platform."
        )

    lines = [f"Scanned {_plural(grade.scanned, 'Python file')}", ""]
    for check in grade.findings:
        lines.append(
            f"  {_mark(check.verdict)} {check.id} — {check.detail} "
            f"({_plural(check.fail_count, 'site')})"
        )
        # Truncated for the reader, not on the record: `--json` carries every site, so a caller
        # can open all of them while a terminal shows the first handful.
        shown = check.evidence[:_SITES_SHOWN]
        for site in shown:
            lines.append(f"      {site}")
        if len(check.evidence) > len(shown):
            lines.append(f"      … and {len(check.evidence) - len(shown)} more (--json for all)")
        lines.append(f"      → {check.fix}")
        lines.append("")

    if not grade.findings:
        lines.append(f"{_TICK} Nothing the source can decide is wrong.")
        lines.append("")

    lines.append(
        "This reads the source, so it answers only what the source decides. Fragmentation across "
        "a real hop, a platform's default span kind, and how much of a trace is mechanical all "
        "need real traces — run --platform once the app has."
    )
    return "\n".join(lines)


def render_source_json(grade: SourceGrade) -> str:
    payload: dict[str, Any] = {
        "scanned": grade.scanned,
        "ok": grade.ok,
        "checks": [c.model_dump() for c in grade.checks],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def render_json(sample: SampleGrade, *, checked: int) -> str:
    """Machine-readable form, for CI or for another agent to read."""
    payload: dict[str, Any] = {
        "checked": checked,
        "verdict": sample.verdict,
        "entry_seatable": sample.ok_count,
        "below": len(sample.traces) - sample.ok_count,
        "checks": [c.model_dump() for c in sample.checks],
        "traces": [
            {
                "trace_id": t.trace_id,
                "label": t.label,
                "verdict": t.verdict,
                "failures": [
                    {"id": c.id, "verdict": c.verdict, "fix": c.fix, "evidence": list(c.evidence)}
                    for c in t.failures()
                ],
            }
            for t in sample.traces
        ],
        "fixes": fix_summary(list(sample.traces)),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
