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


def test_the_report_ends_with_a_line_worth_pasting_into_a_status_update() -> None:
    """A developer who improves their instrumentation has to be able to say by how much.
    Assembling that from the headline by hand is work the report can just do."""
    out = render(grade_sample([failing_trace(f"t{i}") for i in range(4)]), checked=4)
    assert "Score: 0/4 entry_seatable (0%) · entry_missing" in out
    assert "compare the two Score lines" in out


def test_the_score_is_a_percentage_of_what_was_graded(good_trace: list) -> None:
    out = render(grade_sample([good_trace, failing_trace("t2")]), checked=2)
    assert "Score: 1/2 entry_seatable (50%)" in out


def test_the_plan_says_which_fixes_trace_fix_can_actually_apply() -> None:
    """Two field pilots skipped trace-fix because the findings were design decisions and nothing
    said so. The split has to be in the report, not in the reader's head."""
    sample = grade_sample([failing_trace(f"t{i}") for i in range(3)])
    out = render(sample, checked=3)

    assert "trace-fix can apply this" in out
    assert "needs your decision" in out
    assert "mechanical — `/mega-loop:trace-fix` can apply" in out
    assert "design decision" in out


def test_a_plan_of_pure_decisions_does_not_offer_the_fix_verb() -> None:
    """R1b alone is a design question. Offering an automated pass here is the promise that
    breaks trust the first time it is taken up."""
    sample = grade_sample(
        [
            [
                span(span_id=f"{t}-a", trace_id=t, attributes={"input.value": "hi"}),
                span(span_id=f"{t}-b", trace_id=t, attributes={"input.value": "hi"}),
            ]
            for t in ("ta", "tb")
        ]
    )
    out = render(sample, checked=2)
    assert "No finding here is mechanical" in out
    assert "trace-fix can apply" not in out


# --- the never-fatal findings need a channel of their own ---------------------


def heavy_clean_trace(trace_id: str, size: int = 3_000_000) -> list:
    """Well-instrumented and far too heavy — entry_seatable, so it appears nowhere else."""
    return [
        span(
            span_id=f"{trace_id}-root",
            trace_id=trace_id,
            span_kind="CHAIN",
            name="run_agent",
            attributes={"openinference.span.kind": "CHAIN", "input.value": "hi"},
        ),
        span(
            span_id=f"{trace_id}-llm",
            trace_id=trace_id,
            parent_id=f"{trace_id}-root",
            span_kind="LLM",
            name="describe_image",
            attributes={
                "openinference.span.kind": "LLM",
                "input.value": "x" * size,
                "output.value": "a cat",
                "llm.token_count.prompt": 10,
                "llm.token_count.completion": 5,
            },
        ),
    ]


def test_a_passing_trace_that_is_far_too_heavy_is_still_reported() -> None:
    """The case S4 exists for produces no failing trace, so without its own line the whole
    finding reaches nobody — which is what shipped before this test."""
    out = render(grade_sample([heavy_clean_trace("t1")]), checked=1)

    assert "S4_payload_weight" in out
    assert "3.0 MB" in out
    assert "describe_image" in out
    assert "none of these change a verdict" in out.lower()


def test_the_plan_never_claims_more_traces_than_the_header_admits_exist() -> None:
    """`clears 5 traces` under a header reading `2 below` was the visible shape of the bug:
    the plan counted every trace, including the passing ones a never-fatal check warns on."""
    sample = grade_sample(
        [failing_trace("f1"), failing_trace("f2")] + [heavy_clean_trace(f"h{i}") for i in range(5)]
    )
    out = render(sample, checked=7)

    below = len([t for t in sample.traces if not t.ok])
    assert below == 2
    for entry in fix_summary(list(sample.traces)):
        assert entry["traces"] <= below, entry

    # And the advisory finding is not ranked above the check that blocks the replay.
    plan = out[out.index("most-clearing first") :]
    assert plan.index("R1_entry_seat") < plan.index("Worth knowing")
    assert "S4_payload_weight" not in plan[: plan.index("Worth knowing")]


def test_a_trace_heavy_in_no_single_attribute_still_names_where_the_bytes_are() -> None:
    """40 spans of 40 kB is a heavy trace with no heavy attribute. A size with no location is
    not a fix, so the evidence falls back to the spans."""
    spans = [
        span(
            span_id="root",
            trace_id="t1",
            span_kind="CHAIN",
            name="run_agent",
            attributes={"openinference.span.kind": "CHAIN", "input.value": "hi"},
        )
    ] + [
        span(
            span_id=f"s{i}",
            trace_id="t1",
            parent_id="root",
            span_kind="TOOL",
            name=f"tool_{i}",
            attributes={"openinference.span.kind": "TOOL", "input.value": "y" * 40_000},
        )
        for i in range(40)
    ]
    out = render(grade_sample([spans]), checked=1)

    assert "S4_payload_weight" in out
    assert "tool_" in out  # a span name, since no single attribute crossed the floor
