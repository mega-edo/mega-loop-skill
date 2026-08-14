"""The report is the product. These test what a developer actually reads."""

from __future__ import annotations

from tests.conftest import span

from trace_validator.checks import fix_summary, grade_sample
from trace_validator.report import render


def failing_trace(trace_id: str) -> list:
    """A trace with no entry input — one failure, one fix."""
    return [span(span_id=f"{trace_id}-root", trace_id=trace_id, span_kind="CHAIN")]


def test_one_failing_trace_does_not_repeat_itself_as_a_summary() -> None:
    """With a single trace the grouped list is the detail again, one screen lower."""
    out = render(grade_sample([failing_trace("t1")]), checked=1)
    assert "most-clearing first" not in out
    assert out.count("Set `input.value` on the root span") == 1


def test_several_failing_traces_get_the_grouped_fix_list() -> None:
    """The grouping earns its space once it collapses several traces into a shorter list."""
    sample = grade_sample([failing_trace(f"t{i}") for i in range(3)])
    out = render(sample, checked=3)

    assert "most-clearing first" in out
    assert "clears 3 traces" in out


def test_one_root_cause_stays_one_fix_however_many_spans_it_left_parentless() -> None:
    """Grouping keys on the fix text, so no check may vary that text per trace.

    Two traces broken the same way — context never propagated — differ only in how many spans
    ended up parentless. If that count reaches the fix string they group apart, and one systemic
    cause is printed as two problems that each clear one trace.
    """
    sample = grade_sample(
        [
            [span(span_id=f"a{i}", trace_id="ta") for i in range(2)],
            [span(span_id=f"b{i}", trace_id="tb") for i in range(3)],
        ]
    )

    root_fixes = [e for e in fix_summary(list(sample.traces)) if "R1b_clean_root" in e["checks"]]
    assert len(root_fixes) == 1
    assert root_fixes[0]["traces"] == 2
    assert "parentless" not in root_fixes[0]["fix"]

    # And the count it used to carry still reaches the reader, via the per-trace detail.
    assert "Found 3 parentless spans" in render(sample, checked=2)


def test_counts_read_as_english() -> None:
    single = render(grade_sample([failing_trace("t1")]), checked=1)
    assert "Checked 1 trace ·" in single

    plural = render(grade_sample([failing_trace("t1"), failing_trace("t2")]), checked=2)
    assert "Checked 2 traces ·" in plural


def test_a_long_failing_sample_is_truncated_with_a_pointer_to_the_rest() -> None:
    sample = grade_sample([failing_trace(f"t{i}") for i in range(12)])
    out = render(sample, checked=12)

    assert "and 4 more traces with the same fixes" in out
    per_trace = [ln for ln in out.splitlines() if ln.startswith("trace ")]
    assert len(per_trace) == 8  # the per-trace cap, not all twelve


def test_a_clean_sample_says_what_the_verdict_does_not_promise(good_trace: list) -> None:
    out = render(grade_sample([good_trace]), checked=1)
    assert "entry_seatable" in out
    assert "depends on the failure itself" in out


def test_an_empty_sample_explains_where_to_look() -> None:
    out = render(grade_sample([]), checked=0)
    assert "No gradable traces" in out
    assert "credentials" in out


def test_the_summary_says_fixes_not_fixs() -> None:
    """Naive -s pluralisation produced "3 distinct fixs" in a real run. It is user-facing text."""
    sample = grade_sample([failing_trace(f"t{i}") for i in range(3)])
    out = render(sample, checked=3)

    assert "distinct fixes" in out
    assert "fixs" not in out
