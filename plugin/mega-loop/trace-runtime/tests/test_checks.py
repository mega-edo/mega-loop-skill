"""Each check, on the smallest trace that isolates it."""

from __future__ import annotations

from tests.conftest import span

from trace_validator.checks import grade, grade_sample, group_by_trace, opaque_spans


def verdict_of(spans: list, check_id: str) -> str:
    return next(c for c in grade(spans).checks if c.id == check_id).verdict


def test_the_good_asset_is_entry_seatable(good_trace: list) -> None:
    result = grade(good_trace)
    assert result.verdict == "entry_seatable", [
        (c.id, c.verdict) for c in result.checks if c.failing
    ]
    assert result.failures() == []


def test_the_broken_asset_trips_every_check_it_is_built_for(broken_trace: list) -> None:
    result = grade(broken_trace)
    tripped = {c.id: c.verdict for c in result.failures()}
    assert tripped == {
        "R1_entry_seat": "fail",
        "R1b_clean_root": "fail",
        "R3_error_status": "warn",
        "M1_kind_present": "fail",
        "M2_tree_intact": "fail",
        "M3_duration_sane": "fail",
        "M4_index_contiguous": "fail",
        "M5_status_coherent": "fail",
        "M6_role_known": "fail",
    }
    assert result.verdict == "entry_missing"


def test_r1b_wants_exactly_one_non_llm_root_carrying_the_request() -> None:
    two_roots = [
        span(span_id="a", attributes={"input.value": "hi"}),
        span(span_id="b", attributes={"input.value": "hi"}),
    ]
    assert verdict_of(two_roots, "R1b_clean_root") == "fail"

    llm_root = [span(span_kind="LLM", attributes={"input.value": "hi"})]
    assert verdict_of(llm_root, "R1b_clean_root") == "fail"

    clean = [span(attributes={"input.value": "hi"})]
    assert verdict_of(clean, "R1b_clean_root") == "pass"


def test_m2_only_fails_on_a_parent_outside_the_trace() -> None:
    intact = [
        span(span_id="root", attributes={"input.value": "hi"}),
        span(span_id="child", parent_id="root"),
    ]
    assert verdict_of(intact, "M2_tree_intact") == "pass"

    fragmented = [
        span(span_id="root", attributes={"input.value": "hi"}),
        span(span_id="child", parent_id="elsewhere"),
    ]
    assert verdict_of(fragmented, "M2_tree_intact") == "fail"


def test_m4_counts_tool_call_indices_per_message_not_globally() -> None:
    """Two messages each holding tool_call 0 is contiguous; a gap inside one message is not."""
    ok = [
        span(
            span_kind="LLM",
            attributes={
                "input.value": "hi",
                "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "a",
                "llm.output_messages.1.message.tool_calls.0.tool_call.function.name": "b",
            },
        )
    ]
    assert verdict_of(ok, "M4_index_contiguous") == "pass"

    gapped = [
        span(
            span_kind="LLM",
            attributes={
                "input.value": "hi",
                "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "a",
                "llm.output_messages.0.message.tool_calls.2.tool_call.function.name": "b",
            },
        )
    ]
    assert verdict_of(gapped, "M4_index_contiguous") == "fail"


def test_m5_allows_a_status_message_on_an_errored_span() -> None:
    errored = [
        span(
            attributes={"input.value": "hi", "status_message": "boom"},
            status_code="ERROR",
        )
    ]
    assert verdict_of(errored, "M5_status_coherent") == "pass"


def test_a_real_application_failure_does_not_lower_readiness() -> None:
    """A correctly reported error is good instrumentation, not a defect in it.

    This is the distinction the whole grader rests on: it judges whether MEGA Loop can see the
    trace, never whether the trace contains a bug.
    """
    honest_failure = [
        span(span_id="root", attributes={"input.value": "delete the file"}),
        span(
            span_id="tool",
            parent_id="root",
            span_kind="TOOL",
            status_code="ERROR",
            status_message="permission denied",
            attributes={
                "openinference.span.kind": "TOOL",
                "output.value": "permission denied",
                "status_message": "permission denied",
            },
        ),
    ]
    assert grade(honest_failure).verdict == "entry_seatable"


def test_rollup_precedence_entry_missing_outranks_everything() -> None:
    """A trace nobody can re-run is not a candidate, however clean the rest of it is."""
    unusable_but_tidy = [span(span_kind="CHAIN", attributes={"openinference.span.kind": "CHAIN"})]
    assert grade(unusable_but_tidy).verdict == "entry_missing"


def test_detection_gap_outranks_degraded() -> None:
    seatable_with_unknown_kind = [
        span(span_id="root", attributes={"input.value": "hi"}),
        span(span_id="odd", parent_id="root", span_kind="SUMMARISER"),
    ]
    assert grade(seatable_with_unknown_kind).verdict == "detection_gap"


def test_empty_input_is_ungraded_not_failed() -> None:
    assert grade([]).verdict == "ungraded"
    assert grade_sample([]).verdict == "ungraded"


def test_sample_aggregation_is_worst_wins_and_counts_failing_traces() -> None:
    good = [span(span_id="r1", trace_id="t1", attributes={"input.value": "hi"})]
    bad = [span(span_id="r2", trace_id="t2")]
    sample = grade_sample([good, bad])

    assert sample.ok_count == 1
    assert sample.verdict == "entry_missing"
    r1 = next(c for c in sample.checks if c.id == "R1_entry_seat")
    assert (r1.verdict, r1.sample_size, r1.fail_count) == ("fail", 2, 1)


def test_group_by_trace_keeps_first_seen_order() -> None:
    spans = [
        span(span_id="a", trace_id="t2"),
        span(span_id="b", trace_id="t1"),
        span(span_id="c", trace_id="t2"),
    ]
    grouped = group_by_trace(spans)
    assert [[s.span_id for s in g] for g in grouped] == [["a", "c"], ["b"]]


# --- signal density: is the trace worth reading, not just readable -------------


def _agent_trace(extra: list) -> list:
    """A well-formed agent trace, plus whatever the test wants to bury it under."""
    return [
        span(
            span_id="root",
            parent_id="",
            span_kind="CHAIN",
            attributes={"input.value": "q", "output.value": "a"},
        ),
        span(
            span_id="llm",
            parent_id="root",
            span_kind="LLM",
            attributes={"input.value": "q", "output.value": "a"},
        ),
        *extra,
    ]


def _mechanical(n: int) -> list:
    """Spans of the shape any driver's auto-instrumentation emits: no kind, no text."""
    return [
        span(
            span_id=f"m{i}",
            parent_id="root",
            span_kind="",
            attributes={"db.statement": "SELECT 1", "net.peer.name": "host"},
        )
        for i in range(n)
    ]


def test_a_step_that_records_nothing_is_a_detection_gap() -> None:
    # It can be seen to have run and cannot be blamed: the trace shows the shape of the failure
    # but not which step produced it, which is exactly what root-cause analysis needs.
    graded = grade(
        _agent_trace([span(span_id="tool", parent_id="root", span_kind="TOOL", attributes={})])
    )
    check = next(c for c in graded.checks if c.id == "S1_step_io")
    assert check.verdict == "fail"
    assert graded.verdict == "detection_gap"


def test_a_step_with_only_an_output_still_counts_as_recorded() -> None:
    # Either direction is enough to place blame. Demanding both would fail half the tool spans
    # in the wild for no gain in what a reader can conclude.
    graded = grade(
        _agent_trace(
            [
                span(
                    span_id="tool",
                    parent_id="root",
                    span_kind="TOOL",
                    attributes={"output.value": "42"},
                )
            ]
        )
    )
    assert next(c for c in graded.checks if c.id == "S1_step_io").verdict == "pass"


def test_mechanical_spans_burying_the_agent_are_reported() -> None:
    # The generic shape of auto-instrumentation left on: correct spans, no kind, no text, one per
    # round-trip. Nothing is malformed — the cost is that a reader filters more than it reads.
    graded = grade(_agent_trace(_mechanical(9)))
    check = next(c for c in graded.checks if c.id == "S2_signal_density")
    assert check.verdict == "warn"
    assert "9 of 11" in check.detail


def test_noise_never_makes_a_trace_unreadable() -> None:
    # A warn, not a fail: the entry is still seatable and the run can still be re-run. Escalating
    # this would tell a developer their traces are broken when they are merely expensive.
    graded = grade(_agent_trace(_mechanical(9)))
    assert graded.verdict != "degraded"
    assert next(c for c in graded.checks if c.id == "R1_entry_seat").verdict == "pass"


def test_a_small_trace_is_not_judged_on_a_ratio() -> None:
    # Three of five is not a signal about instrumentation, it is a small sample. The threshold
    # exists so a short trace is not told to strip spans it barely has.
    graded = grade(_agent_trace(_mechanical(3)))
    assert next(c for c in graded.checks if c.id == "S2_signal_density").verdict == "pass"


def test_a_kind_or_text_is_enough_to_stay_out_of_the_count() -> None:
    # Both halves of the definition. A span with a kind describes the shape of the run; a span
    # with text contributes to the reconstruction. Only one with neither is opaque.
    kinded = _mechanical(9)
    for s in kinded[:5]:
        object.__setattr__(s, "span_kind", "TOOL")
    graded = grade(_agent_trace(kinded))
    assert next(c for c in graded.checks if c.id == "S2_signal_density").verdict == "pass"


# --- detectable work: classified is not the same as examined -------------------


def test_a_trace_of_only_structure_has_nothing_to_detect() -> None:
    # Every span classified, nothing a detector filters on. This is what a platform default
    # produces: Langfuse types a bare OTLP span as `span`, which lowers to CHAIN, so a trace can
    # pass every kind check and still be invisible to the thing that reads it.
    structure_only = [
        span(span_id="root", parent_id="", span_kind="CHAIN", attributes={"input.value": "q"}),
        span(span_id="a", parent_id="root", span_kind="CHAIN"),
        span(span_id="b", parent_id="root", span_kind="CHAIN"),
    ]
    graded = grade(structure_only)
    check = next(c for c in graded.checks if c.id == "S3_detectable_work")
    assert check.verdict == "warn"
    # M1 passes on the same trace — the two checks are asking different questions, and that
    # difference is the finding.
    assert next(c for c in graded.checks if c.id == "M1_kind_present").verdict == "pass"


def test_one_labelled_step_is_enough_to_have_work_in_it() -> None:
    graded = grade(
        [
            span(span_id="root", parent_id="", span_kind="CHAIN", attributes={"input.value": "q"}),
            span(
                span_id="llm", parent_id="root", span_kind="LLM", attributes={"output.value": "a"}
            ),
        ]
    )
    assert next(c for c in graded.checks if c.id == "S3_detectable_work").verdict == "pass"


def test_having_nothing_to_detect_never_makes_a_trace_unreadable() -> None:
    # A CRUD endpoint's trace is not broken; it is simply not agent traffic. Saying otherwise
    # would send a developer looking for a fault in code that has none.
    graded = grade(
        [span(span_id="root", parent_id="", span_kind="CHAIN", attributes={"input.value": "q"})]
    )
    assert graded.verdict == "entry_seatable"


# --- token accounting ----------------------------------------------------------


def test_an_llm_span_with_real_output_and_no_counts_is_flagged() -> None:
    # Without counts, cost per run and cost-regression attribution are both blind.
    graded = grade(
        [
            span(span_id="root", parent_id="", span_kind="CHAIN", attributes={"input.value": "q"}),
            span(
                span_id="llm",
                parent_id="root",
                span_kind="LLM",
                attributes={"output.value": "x" * 400},
            ),
        ]
    )
    assert next(c for c in graded.checks if c.id == "M7_token_usage").verdict == "warn"


def test_a_short_answer_with_no_counts_is_not_flagged() -> None:
    # A span that returned almost nothing may honestly have ~0 completion tokens. The floor is
    # what keeps this from firing on every trivial call.
    graded = grade(
        [
            span(span_id="root", parent_id="", span_kind="CHAIN", attributes={"input.value": "q"}),
            span(
                span_id="llm", parent_id="root", span_kind="LLM", attributes={"output.value": "ok"}
            ),
        ]
    )
    assert next(c for c in graded.checks if c.id == "M7_token_usage").verdict == "pass"


def test_counts_split_across_prompt_and_completion_are_enough() -> None:
    graded = grade(
        [
            span(span_id="root", parent_id="", span_kind="CHAIN", attributes={"input.value": "q"}),
            span(
                span_id="llm",
                parent_id="root",
                span_kind="LLM",
                attributes={
                    "output.value": "x" * 400,
                    "llm.token_count.prompt": 10,
                    "llm.token_count.completion": 90,
                },
            ),
        ]
    )
    assert next(c for c in graded.checks if c.id == "M7_token_usage").verdict == "pass"


def test_driver_spans_are_opaque_even_when_the_platform_typed_them() -> None:
    """Langfuse types a bare OTLP span as `span`, which lowers to CHAIN.

    Testing opacity by kind label therefore exempted exactly the driver spans this check exists
    to find — a real trace was 89% `SELECT`/`connect` and graded clean.
    """
    spans = [
        span(span_id="root", parent_id="", span_kind="CHAIN", attributes={"input.value": "q"}),
        span(span_id="llm", parent_id="root", span_kind="LLM", attributes={"output.value": "a"}),
        *[
            span(span_id=f"db{i}", parent_id="root", span_kind="CHAIN", attributes={})
            for i in range(10)
        ],
    ]
    assert len(opaque_spans(spans)) == 10
    assert next(c for c in grade(spans).checks if c.id == "S2_signal_density").verdict == "warn"


def test_a_textless_wrapper_the_detector_reads_is_not_opaque() -> None:
    # An AGENT or TOOL span is a step whether or not it recorded text; only the mechanical
    # round-trips are noise.
    spans = [
        span(span_id="root", parent_id="", span_kind="CHAIN", attributes={"input.value": "q"}),
        *[
            span(span_id=f"a{i}", parent_id="root", span_kind="AGENT", attributes={})
            for i in range(10)
        ],
    ]
    assert opaque_spans(spans) == []
