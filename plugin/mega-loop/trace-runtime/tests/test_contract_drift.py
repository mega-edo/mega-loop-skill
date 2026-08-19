"""Guards on the three constants that make the validator lie if they are widened.

These are not tests of behaviour so much as tests of *restraint*. Each one encodes a rule that
looks like an oversight to a reader who has not seen the upstream code, and which a well-meaning
contributor would therefore "fix". The assertion is there to make that fix fail loudly, with the
reason attached.
"""

from __future__ import annotations

from tests.conftest import span

from trace_validator import contract as C
from trace_validator.checks import (
    _check,
    entry_seatable,
    error_in_ok_content,
    grade,
    rollup,
)


def test_step_kinds_stay_at_three() -> None:
    """AGENT and CHAIN are not step kinds. Widening this is the false-ready bug."""
    assert {"LLM", "TOOL", "RETRIEVER"} == C.STEP_KINDS


def test_an_input_message_on_an_agent_span_does_not_seat_an_entry() -> None:
    """The behavioural half of the guard above.

    A trace whose only entry text sits on an AGENT span is `entry_missing` upstream. If this
    starts passing, the validator will be telling developers their traces are fine while MEGA
    Loop refuses them — the single worst outcome for a tool whose whole job is to answer that
    question.
    """
    agent_only = [
        span(
            span_kind="AGENT",
            attributes={
                "openinference.span.kind": "AGENT",
                "llm.input_messages.0.message.role": "user",
                "llm.input_messages.0.message.content": "How many orders shipped late?",
            },
        )
    ]
    assert entry_seatable(agent_only) is False
    assert grade(agent_only).verdict == "entry_missing"

    # The same content on an LLM span *does* seat it — proving the fixture is otherwise sound.
    llm_only = [
        span(
            span_kind="LLM",
            attributes={
                "openinference.span.kind": "LLM",
                "llm.input_messages.0.message.role": "user",
                "llm.input_messages.0.message.content": "How many orders shipped late?",
            },
        )
    ]
    assert entry_seatable(llm_only) is True


def test_error_in_content_ignores_llm_and_agent_spans() -> None:
    """Model prose discusses errors constantly; that is not a failed span.

    Without this filter R3 warns on ordinary answers, and since the CLI exits non-zero on any
    non-`entry_seatable` trace, the developer is blocked on a non-problem.
    """
    text = "Error: permission denied for relation orders"
    for kind in ("LLM", "AGENT"):
        prose = span(
            span_kind=kind, attributes={"openinference.span.kind": kind, "output.value": text}
        )
        assert error_in_ok_content([prose]) == []

    for kind in sorted(C.CONTENT_ERROR_KINDS):
        result = span(
            span_kind=kind, attributes={"openinference.span.kind": kind, "output.value": text}
        )
        assert len(error_in_ok_content([result])) == 1, kind


def test_error_in_content_skips_long_output() -> None:
    """The length guard reads the WHOLE text, not just the matched head."""
    long_reply = "Error: permission denied. " + ("detail " * 400)
    assert len(long_reply) > C.MAX_ERROR_REPLY_CHARS
    noisy = span(
        span_kind="TOOL",
        attributes={"openinference.span.kind": "TOOL", "output.value": long_reply},
    )
    assert error_in_ok_content([noisy]) == []


def test_sentinels_are_the_tool_refusal_vocabulary() -> None:
    """Stack-trace idioms are deliberately absent — MEGA Loop does not match on them."""
    assert "traceback" not in " ".join(C.ERROR_SENTINELS).lower()
    assert "exception" not in " ".join(C.ERROR_SENTINELS).lower()
    # The trailing spaces matter: "could not " must not fire on "could nothing".
    assert "could not " in C.ERROR_SENTINELS
    innocent = span(
        span_kind="TOOL",
        attributes={"openinference.span.kind": "TOOL", "output.value": "It could nothing else"},
    )
    assert error_in_ok_content([innocent]) == []


def test_span_is_absent_not_unknown() -> None:
    """`SPAN` means "no kind was set" — a warning, not the harder present-non-enum failure."""
    assert "SPAN" not in C.SPAN_KINDS
    assert "SPAN" in C.ABSENT_KINDS

    unset = grade([span(span_kind="SPAN", attributes={"input.value": "hi"})])
    unknown = grade([span(span_kind="SUMMARISER", attributes={"input.value": "hi"})])
    m1 = {
        g.verdict: next(c for c in g.checks if c.id == "M1_kind_present") for g in (unset, unknown)
    }
    assert m1[unset.verdict].verdict == "warn"
    assert m1[unknown.verdict].verdict == "fail"


def test_prompt_is_a_real_kind_not_an_absent_one() -> None:
    """`PROMPT` is a full enum member — the mirror image of the `SPAN` rule above.

    The two look interchangeable ("neither one names a step"), and moving `PROMPT` across to
    `ABSENT_KINDS` is the tidying a reader reaches for. Upstream `readiness.py` keeps it in
    `_SPAN_KINDS` with `_ABSENT_KINDS = {"", "SPAN"}`, so making it absent here would report
    `warn` where MEGA Loop reports nothing at all. No detector filters on it either way —
    `DETECTOR_KINDS` is the constant that decides visibility.
    """
    assert "PROMPT" in C.SPAN_KINDS
    assert "PROMPT" not in C.ABSENT_KINDS
    assert "PROMPT" not in C.DETECTOR_KINDS

    prompt = grade([span(span_kind="PROMPT", attributes={"input.value": "hi"})])
    assert next(c for c in prompt.checks if c.id == "M1_kind_present").verdict == "pass"


def graded_ids() -> list[str]:
    """The check ids `grade` emits, in order — the population the two tests below quantify over."""
    return [c.id for c in grade([span(attributes={"input.value": "hi"})]).checks]


def test_blocking_agrees_with_rollup_on_every_check_and_verdict() -> None:
    """``Check.blocking`` claims to be a transcription of ``rollup``. This is the comparison.

    The split between the fix plan and the advisory block rests on that claim: a finding is in
    the plan iff it moved the trace's verdict. If ``rollup`` grows a branch and ``WARN_IS_FATAL``
    does not, a real failure is quietly filed as advice — the failure mode is under-reporting a
    blocker, which is worse than the overcount this replaced, and no report-level test would see
    it. So ask ``rollup`` directly, for every check id at every verdict it can hold.
    """
    ids = graded_ids()
    assert set(ids) >= C.WARN_IS_FATAL

    for cid in ids:
        for verdict in ("pass", "warn", "fail", "not_observed"):
            checks = tuple(
                _check(i, "soft", verdict if i == cid else "pass", "", "", 1, 0) for i in ids
            )
            by_id = {c.id: c for c in checks}
            moved = (
                rollup(
                    by_id["R1_entry_seat"],
                    by_id["R3_error_status"],
                    by_id["M1_kind_present"],
                    checks,
                )
                != "entry_seatable"
            )
            assert by_id[cid].blocking is moved, (cid, verdict)


def test_never_fatal_is_the_four_checks_the_docs_promise() -> None:
    """Vocabulary only — it no longer decides anything, so nothing else would catch it drifting.

    README and docs/commands.md both say "four of fifteen are reported but never fatal", and
    ``S4``'s own comment says a heavy trace is still a usable one. A check listed here that grew
    a ``fail`` branch would make those sentences false while the code stayed correct.
    """
    assert len(C.NEVER_FATAL) == 4
    assert set(graded_ids()) >= C.NEVER_FATAL

    # A never-fatal check that acquired a fatal warn would be the contradiction in terms.
    assert not (C.NEVER_FATAL & C.WARN_IS_FATAL)


def test_the_healthy_verdict_keeps_mega_loops_word() -> None:
    """`entry_seatable`, not `ready` — the dashboard shows the developer these five words."""
    assert set(C.VERDICT_GLOSS) == {
        "entry_seatable",
        "degraded",
        "detection_gap",
        "entry_missing",
        "ungraded",
    }
