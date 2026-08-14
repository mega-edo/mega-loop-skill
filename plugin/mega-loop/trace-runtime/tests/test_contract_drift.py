"""Guards on the three constants that make the validator lie if they are widened.

These are not tests of behaviour so much as tests of *restraint*. Each one encodes a rule that
looks like an oversight to a reader who has not seen the upstream code, and which a well-meaning
contributor would therefore "fix". The assertion is there to make that fix fail loudly, with the
reason attached.
"""

from __future__ import annotations

from tests.conftest import span

from trace_validator import contract as C
from trace_validator.checks import entry_seatable, error_in_ok_content, grade


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


def test_the_healthy_verdict_keeps_mega_loops_word() -> None:
    """`entry_seatable`, not `ready` — the dashboard shows the developer these five words."""
    assert set(C.VERDICT_GLOSS) == {
        "entry_seatable",
        "degraded",
        "detection_gap",
        "entry_missing",
        "ungraded",
    }
