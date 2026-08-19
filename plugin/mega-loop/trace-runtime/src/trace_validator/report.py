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
from trace_validator.checks import (
    SampleGrade,
    TraceGrade,
    applicability_summary,
    fix_summary,
)
from trace_validator.source import SourceGrade

_TICK, _CROSS, _WARN = "✓", "✗", "!"

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


def _handoff_lines(fixes: list[dict[str, Any]]) -> list[str]:
    """Say plainly how much of the plan can be automated.

    Without this the reader has to work out for themselves that half their findings are design
    questions — which is what actually happened in the field, twice, and cost the fix verb its
    first two users.
    """
    mech = sum(1 for f in fixes if f["finding_class"] == C.MECHANICAL)
    arch = len(fixes) - mech
    if mech and arch:
        rest = (
            "The other is a design decision; make that yourself first."
            if arch == 1
            else f"The other {arch} are design decisions; make those yourself first."
        )
        message = (
            f"{_plural(mech, 'of these is', 'of these are')} mechanical — "
            f"`/mega-loop:trace-fix` can apply {'it' if mech == 1 else 'them'}. {rest}"
        )
    elif mech:
        # No count in these two branches: "all" and "none" already say it, and a count forced
        # into the sentence only creates a plural to get wrong.
        message = "Every finding here is mechanical — `/mega-loop:trace-fix` can apply them."
    else:
        message = (
            "No finding here is mechanical. Each is a design decision about where spans come "
            "from or what belongs in a trace, so trace-fix would be guessing — read the fixes "
            "and choose."
        )
    return [message]


def _applicability_lines(sample: SampleGrade) -> list[str]:
    """The findings that moved no verdict, on their own line, counted over the whole sample.

    Not a fixed set of checks — see ``Check.blocking`` for the cut. Any check can land here with
    a warn the rollup ignored, so the line is worth printing whatever tripped it: without one, a
    warning on an otherwise-clean trace reaches nobody, because the trace is ``entry_seatable``
    and no per-trace block is printed for it. The check that measures payload weight is the case
    that made this visible, and it is the case it exists for.
    """
    entries = applicability_summary(list(sample.traces))
    if not entries:
        return []
    lines = ["Worth knowing — none of these change a verdict:"]
    for entry in entries:
        cleared = _plural(entry["traces"], "trace")
        sites = f" — {', '.join(entry['evidence'])}" if entry["evidence"] else ""
        lines.append(f"  {_WARN} {', '.join(entry['checks'])} · {cleared}{sites}")
        lines.append(f"      → {entry['fix']}")
    return lines + [""]


def _scoreline(sample: SampleGrade) -> list[str]:
    """One line to paste into a status update, and to diff against after the fix.

    A developer who improves their instrumentation has to be able to say by how much. Assembling
    that from the headline by hand is work we can just do for them.
    """
    ok, total = sample.ok_count, len(sample.traces)
    pct = round(100 * ok / total) if total else 0
    return [
        f"Score: {ok}/{total} entry_seatable ({pct}%) · {sample.verdict}",
        "  → Re-run this after fixing and compare the two Score lines.",
    ]


def render_trace(grade: TraceGrade) -> list[str]:
    head = f"trace {_short(grade.trace_id)}"
    if grade.label:
        head += f"  ({grade.label})"
    lines = [f"{head}   verdict: {grade.verdict}"]
    for check in grade.failures():
        evidence = f" — {', '.join(check.evidence)}" if check.evidence else ""
        who = C.FINDING_CLASS_GLOSS[check.finding_class]
        lines.append(f"  {_mark(check.verdict)} {check.id} [{who}] — {check.detail}{evidence}")
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
            checks = ", ".join(entry["checks"])
            who = C.FINDING_CLASS_GLOSS[entry["finding_class"]]
            lines.append(f"     clears {cleared} · {checks} · {who}")
        lines.append("")
        lines += _handoff_lines(fixes) + [""]

    gloss = C.VERDICT_GLOSS.get(sample.verdict, "")
    lines.append(f"Sample verdict: {sample.verdict}" + (f" — {gloss}" if gloss else ""))
    if sample.verdict == "entry_seatable":
        lines.append(
            "This means MEGA Loop can read these traces. Whether a given failure becomes a "
            "bug it can fix also depends on the failure itself."
        )
    lines += _applicability_lines(sample)
    lines += _scoreline(sample) + [""]
    lines.append("Reference: references/trace-spec.md")
    return "\n".join(lines)


def render_source(grade: SourceGrade) -> str:
    """The source report. Deliberately ends by naming what it could not answer.

    A developer who reads a clean board here and stops has been misled: the hardest failure this
    skill exists for — one request arriving as several traces — is not visible in source at all.
    """
    if not grade.scanned:
        # Naming the language is the whole point. "Nothing found" reads as a pass to anyone
        # skimming, and for a Go or Java repository it means the opposite: nothing was read.
        seen = ", ".join(f"{n} ({c})" for n, c in list(grade.languages.items())[:4])
        if seen:
            return (
                f"Read no source. This grader parses Python; this repository is {seen}.\n"
                "  → Nothing here is a verdict on your instrumentation — grade real traces with "
                "--platform instead, which is language-agnostic."
            )
        return (
            "No Python files found to scan.\n"
            "  → Point --source at the repository root, or grade real traces with --platform."
        )

    lines = [f"Scanned {_plural(grade.scanned, 'Python file')}", ""]
    for check in grade.findings:
        who = C.FINDING_CLASS_GLOSS[check.finding_class]
        lines.append(
            f"  {_mark(check.verdict)} {check.id} [{who}] — {check.detail} "
            f"({_plural(check.fail_count, 'site')})"
        )
        # Truncated for the reader, not on the record: `--json` carries every site, so a caller
        # can open all of them while a terminal shows the first handful.
        shown = check.evidence[: C.EVIDENCE_LIMIT]
        for site in shown:
            lines.append(f"      {site}")
        if len(check.evidence) > len(shown):
            lines.append(f"      … and {len(check.evidence) - len(shown)} more (--json for all)")
        lines.append(f"      → {check.fix}")
        lines.append("")

    if not grade.findings:
        # Name the precondition, not just the absence of findings. A clean board is only
        # meaningful because something was instrumented to grade; "nothing wrong" alone reads
        # the same on a repository that traces nothing, which is the confusion L0 exists to end.
        lines.append(f"{_TICK} L0_any_instrumentation — this repository does trace.")
        lines.append(f"{_TICK} Nothing else the source can decide is wrong.")
        lines.append("")

    # A clean Python board says nothing about the rest of a polyglot repository, and the reader
    # most likely to be misled is the one whose agent is the part this grader cannot parse.
    if grade.unreadable:
        rest = ", ".join(f"{n} ({c})" for n, c in grade.unreadable.items())
        lines.append(f"  {_WARN} Not read: {rest}. This grader parses Python only.")
        lines.append(
            "      → Whatever those files do with spans is unmeasured here. Grade real traces "
            "with --platform to cover them."
        )
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
        # A caller deciding whether to trust `ok` needs to know what was read to produce it.
        "languages": grade.languages,
        "unreadable": grade.unreadable,
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
                    {
                        "id": c.id,
                        "verdict": c.verdict,
                        "finding_class": c.finding_class,
                        "fix": c.fix,
                        "evidence": list(c.evidence),
                    }
                    for c in t.failures()
                ],
            }
            for t in sample.traces
        ],
        "fixes": fix_summary(list(sample.traces)),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
