"""The fifteen checks, and the verdict they roll up to.

This mirrors `mega_loop/readiness.py` — same ids, same tiers, same order of precedence — with one
addition: every check carries a **fix**. Upstream only has to explain a verdict to an operator
looking at a dashboard; here the developer is going to act on it, in their own code, right now,
so a check that cannot say what to change has no reason to exist.

The grader answers one question: *is this trace well-formed enough that MEGA Loop's detection and
gate can run on it at all?* It never asks whether the trace contains a bug. A real application
failure showing up in a well-formed trace is a success for the instrumentation, not a defect in
it, and must never lower a check.
"""

from __future__ import annotations

import re
from contextlib import suppress
from heapq import nlargest
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict

from trace_validator import contract as C
from trace_validator.span import Span

_TOOL_CALL_KEY = re.compile(r"^llm\.output_messages\.(\d+)\.message\.tool_calls\.(\d+)\.")


class Check(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    tier: str  # hard | detection | soft | mechanical
    verdict: str  # pass | fail | warn | not_observed
    detail: str  # what it costs you — mirrors readiness.py
    fix: str  # what to change — this skill's addition
    sample_size: int
    fail_count: int
    evidence: tuple[str, ...] = ()  # span labels that tripped it, for a nameable fix
    #: mechanical (trace-fix can apply it) | architectural (a decision for the developer).
    #: Required, so a check cannot reach a report without answering who has to act on it.
    finding_class: str

    @property
    def failing(self) -> bool:
        return self.verdict in ("fail", "warn")


class TraceGrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    trace_id: str = ""
    label: str = ""  # the root span's name, when there is one
    graded: bool
    checks: tuple[Check, ...] = ()
    verdict: str

    @property
    def ok(self) -> bool:
        return self.verdict == "entry_seatable"

    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.failing]


class SampleGrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    traces: tuple[TraceGrade, ...] = ()
    checks: tuple[Check, ...] = ()  # aggregated, worst-wins
    verdict: str

    @property
    def ok_count(self) -> int:
        return sum(1 for t in self.traces if t.ok)


def _label(span: Span) -> str:
    return span.name or span.span_id or "<unnamed span>"


#: Which class each check falls into — see ``contract.MECHANICAL`` for what the two mean. Keyed
#: by id and kept in one block rather than passed at each call site, because the useful question
#: a reader asks is "which of these are decisions?", and that is only answerable from a list.
#: The L-family is source mode (``source.py``); the rest are graded from traces.
FINDING_CLASS = {
    "L0_any_instrumentation": C.ARCHITECTURAL,  # whether to trace at all
    "L1_mechanical_autoinstrumentation": C.ARCHITECTURAL,  # which instrumentation runs
    "L2_span_kind_at_open": C.MECHANICAL,  # the source-mode twin of M1_kind_present
    "R0_addressable": C.ARCHITECTURAL,  # an exporter or serializer, not the instrumentation
    "R1_entry_seat": C.MECHANICAL,
    "R1b_clean_root": C.ARCHITECTURAL,  # where the entry span lives is a design choice
    "R3_error_status": C.MECHANICAL,
    "M1_kind_present": C.MECHANICAL,
    "M2_tree_intact": C.ARCHITECTURAL,  # propagation and provider topology
    "M3_duration_sane": C.MECHANICAL,
    "M4_index_contiguous": C.MECHANICAL,
    "M5_status_coherent": C.MECHANICAL,
    "M6_role_known": C.MECHANICAL,
    "M7_token_usage": C.MECHANICAL,
    "S1_step_io": C.MECHANICAL,
    "S2_signal_density": C.ARCHITECTURAL,  # which instrumentation runs at all
    "S3_detectable_work": C.ARCHITECTURAL,  # whether this traffic belongs in the sample
    "S4_payload_weight": C.ARCHITECTURAL,  # storing a reference instead of the bytes
}


# --- R-family: entry seat + detection-side spec -------------------------------


def entry_seatable(spans: list[Span]) -> bool:
    """Can a fix be re-run against this trace at all?

    Either any span carries a non-blank ``input.value``, or a **step-kind** span carries a
    non-blank input message. Step kinds are LLM/TOOL/RETRIEVER only — a message on a CHAIN or
    AGENT span never seats an entry, because the forward-runner's text ladder does not walk
    those. This is the single easiest place to accidentally make the validator lie.
    """
    if any(s.input_value() for s in spans):
        return True
    return any(
        (m.get("message.content") or "").strip()
        for s in spans
        if s.span_kind in C.STEP_KINDS
        for m in s.messages(C.OI_IN_MESSAGES).values()
    )


def clean_root(spans: list[Span]) -> bool:
    """Exactly one root, it is not an LLM span, and it carries the request text."""
    roots = [s for s in spans if s.is_root]
    if len(roots) != 1:
        return False
    root = roots[0]
    return root.span_kind != "LLM" and bool(root.input_value())


def error_in_ok_content(spans: list[Span]) -> list[Span]:
    """Spans that returned an error as *text* while reporting OK status.

    Four gates, all of them from `detect.observe_error_in_content`. Each one exists to keep the
    check quiet: without the kind filter it fires on every model answer that discusses an error,
    and without the length guard it fires on any long reply containing "not found".
    """
    hits = []
    for span in spans:
        if span.span_kind not in C.CONTENT_ERROR_KINDS or span.status_code == "ERROR":
            continue
        text = span.output_value() or next((c for c in span.output_message_contents() if c), "")
        text = text.strip()
        if not text or len(text) > C.MAX_ERROR_REPLY_CHARS:
            continue
        head = text[: C.HEAD_CHARS].lower()
        if any(sentinel in head for sentinel in C.ERROR_SENTINELS):
            hits.append(span)
    return hits


# --- M-family: mechanical spec compliance ------------------------------------


def kind_counts(spans: list[Span]) -> tuple[list[Span], list[Span]]:
    """``(present_non_enum, absent)``.

    A *present but unknown* kind is the worse of the two: it looks instrumented, so nobody goes
    looking, while every kind-filtering detector skips the span. An absent kind is at least
    honest about being absent.
    """
    non_enum: list[Span] = []
    absent: list[Span] = []
    for span in spans:
        if span.span_kind in C.SPAN_KINDS:
            continue
        (absent if span.span_kind in C.ABSENT_KINDS else non_enum).append(span)
    return non_enum, absent


def unknown_role(span: Span) -> bool:
    for prefix in (C.OI_IN_MESSAGES, C.OI_OUT_MESSAGES):
        for message in span.messages(prefix).values():
            role = (message.get("message.role") or "").strip().lower()
            if role and role not in C.KNOWN_ROLES:
                return True
    return False


def _tool_call_gap(span: Span) -> bool:
    """``tool_calls.{j}`` must be contiguous *within each output message*, not globally."""
    by_message: dict[int, set[int]] = {}
    for key in span.attributes:
        match = _TOOL_CALL_KEY.match(key)
        if match:
            by_message.setdefault(int(match.group(1)), set()).add(int(match.group(2)))
    return any(js != set(range(len(js))) for js in by_message.values())


def has_index_gap(span: Span) -> bool:
    for family in C.INDEX_FAMILIES:
        indices = span.family_indices(family)
        if indices and indices != set(range(len(indices))):
            return True
    return _tool_call_gap(span)


# --- grading ------------------------------------------------------------------


def carries_signal(span: Span) -> bool:
    """Does this span say anything a reader could use?

    Any input/output text counts, in any of the four shapes. A span with text is legible even
    without a kind — the normalizer can still reconstruct what went in and what came back.
    """
    for key in C.SIGNAL_KEYS:
        value = span.attributes.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if value:  # message families arrive as dicts/lists once lowered
            return True
    return any(
        str(k).startswith(("llm.input_messages", "llm.output_messages")) for k in span.attributes
    )


def opaque_spans(spans: list[Span]) -> list[Span]:
    """Spans with neither a recognised kind nor any text — mechanical detail, not steps.

    This is what a database driver, an HTTP client or a cache emits when its auto-instrumentation
    is left on: one span per round-trip, correct and useless to a reader. Deliberately defined by
    what the span LACKS rather than by naming libraries, so it holds for a stack this validator
    has never seen.

    Exempting only the kinds a detector reads, rather than trusting an absent kind, is what makes
    it hold on Langfuse: a bare OTLP span arrives typed `span` there and lowers to CHAIN, so a
    kind-label test would exempt the very driver spans this check exists to find.
    """
    return [
        s
        for s in spans
        if s.span_kind not in C.DETECTOR_KINDS and not carries_signal(s) and not s.is_root
    ]


def step_spans_missing_io(spans: list[Span]) -> list[Span]:
    """Step spans that record neither what they were given nor what they returned.

    ``STEP_KINDS`` are the three the reconstruction walks. One of them with no text says a step
    ran and nothing else — enough to draw the shape of the trace, not enough to say which step
    produced the wrong answer.
    """
    return [s for s in spans if s.span_kind in C.STEP_KINDS and not carries_signal(s)]


def _attr_bytes(value: Any) -> int:
    """UTF-8 length of one attribute value, as it travels on the wire.

    ``isascii()`` reads a flag off the string header, so the values this check exists to catch —
    base64, JSON, scraped HTML, all ASCII — are measured without encoding anything. Encoding a
    20 MB attribute just to call ``len`` on the result would allocate the very copy the check is
    warning about; the fallback keeps the number exact for everything else.
    """
    text = str(value)
    return len(text) if text.isascii() else len(text.encode("utf-8"))


class HeavyAttribute(NamedTuple):
    span: Span
    key: str
    size: int


class PayloadWeight(NamedTuple):
    total: int
    heaviest: list[HeavyAttribute]
    by_span: list[tuple[Span, int]]


def payload_weight(spans: list[Span]) -> PayloadWeight:
    """Total attribute text in the trace, the individual attributes carrying the bulk, and the
    per-span totals.

    One walk for all three: the heavy test is an integer compare on a size the total already
    needed, and measuring a multi-megabyte attribute twice is the mistake this check reports.

    ``by_span`` is the fallback that keeps the finding actionable. A trace can cross the
    threshold without any single attribute crossing it — forty spans each carrying 40 kB is a
    heavy trace with no heavy attribute — and a size with no location is not a fix.

    Attribute values only — span ids, timestamps and the envelope are the same handful of bytes
    on every trace and tell the developer nothing they can change.
    """
    total = 0
    heavy: list[HeavyAttribute] = []
    by_span: list[tuple[Span, int]] = []
    for span in spans:
        span_total = 0
        for key, value in span.attributes.items():
            size = _attr_bytes(value)
            span_total += size
            if size >= C.PAYLOAD_ATTR_MIN_BYTES:
                heavy.append(HeavyAttribute(span, key, size))
        total += span_total
        by_span.append((span, span_total))
    return PayloadWeight(total, heavy, by_span)


def _human_bytes(size: int) -> str:
    """Bytes in the unit a developer would say out loud. 22 MB, not 23068672."""
    for unit, step in (("GB", 1_000_000_000), ("MB", 1_000_000), ("kB", 1_000)):
        if size >= step:
            return f"{size / step:.1f} {unit}"
    return f"{size} B"


def _heaviest_labels(weight: PayloadWeight) -> tuple[str, ...]:
    """Where the bytes went, biggest first.

    Per attribute when one is individually large enough to be the answer; per span when the
    weight is spread thin, because "no attribute is heavy and the trace still is" is a different
    problem with a different fix. ``nlargest`` and not a full sort: a trace that inlines a
    document on every span has a hundred candidates and five slots.
    """
    if weight.heaviest:
        return tuple(
            f"{_label(row.span)} ({row.key}, {_human_bytes(row.size)})"
            for row in nlargest(C.EVIDENCE_LIMIT, weight.heaviest, key=lambda row: row.size)
        )
    return tuple(
        f"{_label(span)} ({_human_bytes(size)})"
        for span, size in nlargest(C.EVIDENCE_LIMIT, weight.by_span, key=lambda row: row[1])
    )


def _total_tokens(span: Span) -> int | None:
    """Reported total token usage, derived from the parts when the total itself is absent."""
    total = span.attributes.get(C.OI_TOK_TOTAL)
    if total is not None:
        with suppress(TypeError, ValueError):
            return int(total)
    prompt = span.attributes.get(C.OI_TOK_PROMPT)
    completion = span.attributes.get(C.OI_TOK_COMPLETION)
    if prompt is not None or completion is not None:
        with suppress(TypeError, ValueError):
            return int(prompt or 0) + int(completion or 0)
    return None


def zero_usage_spans(spans: list[Span]) -> list[Span]:
    """LLM spans with substantive output yet zero or absent token counts.

    Two guards keep it from over-firing, both mirrored from upstream: only LLM spans (others
    legitimately carry no counts), and only past an output floor, since a span that returned
    nothing may honestly have ~0 completion tokens.
    """
    out: list[Span] = []
    for span in spans:
        if span.span_kind != "LLM":
            continue
        total = _total_tokens(span)
        if total is not None and total > 0:
            continue
        text = str(span.attributes.get("output.value") or "")
        for key, value in span.attributes.items():
            if str(key).startswith("llm.output_messages") and str(key).endswith(".content"):
                text += str(value or "")
        if len(text) < C.MIN_SUBSTANTIVE_CHARS:
            continue
        out.append(span)
    return out


def detectable_spans(spans: list[Span]) -> list[Span]:
    """Spans a detector would actually look at.

    Everything else is structure. A trace can be perfectly well-formed, carry a kind on every
    span, and still contain nothing any detector examines — which is what happens when the
    classified spans are all CHAIN.
    """
    return [s for s in spans if s.span_kind in C.DETECTOR_KINDS]


def _check(
    id_: str,
    tier: str,
    verdict: str,
    detail: str,
    fix: str,
    n: int,
    failing: list[Span] | int,
    evidence: tuple[str, ...] | None = None,
) -> Check:
    """The one place a graded Check is built.

    ``evidence`` defaults to the deduped labels of the failing spans, which is what a reader
    wants for fourteen of the fifteen checks. A check whose evidence is a measurement rather
    than a location passes its own; keeping that a parameter rather than a second constructor
    is what stops the two drifting.

    ``FINDING_CLASS[id_]`` and not ``.get`` — a check with no class is a mistake to hear about
    at the call site, not a default to inherit silently.
    """
    spans = failing if isinstance(failing, list) else []
    return Check(
        id=id_,
        finding_class=FINDING_CLASS[id_],
        tier=tier,
        verdict=verdict,
        detail=detail,
        fix=fix,
        sample_size=n,
        fail_count=len(spans) if isinstance(failing, list) else failing,
        evidence=(
            evidence
            if evidence is not None
            else tuple(dict.fromkeys(_label(s) for s in spans))[: C.EVIDENCE_LIMIT]
        ),
    )


def grade(spans: list[Span]) -> TraceGrade:
    """Grade one trace. An empty span list is ``ungraded``, not a failure."""
    if not spans:
        return TraceGrade(graded=False, verdict="ungraded")
    n = len(spans)
    roots = [s for s in spans if s.is_root]

    seatable = entry_seatable(spans)
    r1 = _check(
        "R1_entry_seat",
        "hard",
        "pass" if seatable else "fail",
        "Fixes cannot be verified — the request cannot be re-run without its input.",
        "Set `input.value` on the root span (the user's request). If the entry really lives "
        "deeper, put `llm.input_messages` on the top LLM/TOOL/RETRIEVER span — a message on a "
        "CHAIN or AGENT span does not count.",
        1,
        0 if seatable else 1,
    )

    clean = clean_root(spans)
    r1b = _check(
        "R1b_clean_root",
        "soft",
        "pass" if clean else "fail",
        # The count belongs here, not in `fix`: fix_summary groups by exact fix text, so a
        # per-trace number would split one systemic root cause into one entry per count.
        "Verification falls back to heuristic text reconstruction instead of replaying the "
        "real entry." + (f" Found {len(roots)} parentless spans." if len(roots) != 1 else ""),
        "Make the user's request one single root span of kind CHAIN or AGENT (not LLM), with "
        "`input.value` set.",
        1,
        0 if clean else 1,
    )

    no_trace_id = [s for s in spans if not s.trace_id]
    r0 = _check(
        "R0_addressable",
        "soft",
        "fail" if no_trace_id else "pass",
        "Spans without a trace id are dropped at ingest — MEGA Loop never sees them.",
        "Emit a non-empty trace id on every span. This is usually an exporter or serializer "
        "issue rather than your instrumentation.",
        n,
        no_trace_id,
    )

    err_ok = error_in_ok_content(spans)
    r3 = _check(
        "R3_error_status",
        "detection",
        "warn" if err_ok else "not_observed",
        "These failures reach only the quality stream at reduced fidelity, never the "
        "deterministic error path.",
        "Set the span status to ERROR when the step fails. Returning "
        '`{"success": false, …}` with an OK status hides the failure from detection.',
        n,
        err_ok,
    )

    non_enum, absent = kind_counts(spans)
    m1 = _check(
        "M1_kind_present",
        "mechanical",
        "fail" if non_enum else ("warn" if absent else "pass"),
        "A span whose kind is unrecognised is skipped by every kind-filtering detector — "
        "silently, with no error.",
        "Set `openinference.span.kind` to one of LLM, TOOL, RETRIEVER, AGENT, CHAIN, EMBEDDING, "
        "RERANKER, EVALUATOR, GUARDRAIL.",
        n,
        non_enum or absent,
    )

    ids = {s.span_id for s in spans}
    dangling = [s for s in spans if s.parent_id and s.parent_id not in ids]
    m2 = _check(
        "M2_tree_intact",
        "mechanical",
        "fail" if dangling else "pass",
        "A dangling parent breaks root detection and subtree ancestry — this is what a "
        "fragmented request looks like from the outside.",
        "If the spans are made in one process, the usual cause is a second TracerProvider — the "
        "later one orphans everything it creates, which is why this often passes in dev and "
        "fails in production. Install one provider globally. If the request really does cross "
        "into another service, a worker or a queue, carry the W3C `traceparent` header across. "
        "See references/context-propagation.md.",
        n,
        dangling,
    )

    backwards = [s for s in spans if s.end_time < s.start_time]
    m3 = _check(
        "M3_duration_sane",
        "mechanical",
        "fail" if backwards else "pass",
        "Negative latency mis-fires the latency detectors.",
        "A span ends before it starts — usually a clock source mixed between monotonic and wall "
        "time, or a hand-built span with swapped timestamps.",
        n,
        backwards,
    )

    gapped = [s for s in spans if has_index_gap(s)]
    m4 = _check(
        "M4_index_contiguous",
        "mechanical",
        "fail" if gapped else "pass",
        "Indices with gaps undercount messages, documents and tool calls.",
        "Emit message, document and tool-call indices as 0..n-1 with no gaps — a filtered list "
        "must be re-indexed before it is written out.",
        n,
        gapped,
    )

    incoherent = [
        s
        for s in spans
        if str(s.attributes.get("status_message") or "").strip() and s.status_code != "ERROR"
    ]
    m5 = _check(
        "M5_status_coherent",
        "mechanical",
        "fail" if incoherent else "pass",
        "OTel reserves the status description for errors; setting it on an OK span is "
        "non-compliant.",
        "Only set `status_message` together with an ERROR status. For notes on a healthy span, "
        "use an attribute or an event.",
        n,
        incoherent,
    )

    bad_role = [s for s in spans if unknown_role(s)]
    m6 = _check(
        "M6_role_known",
        "mechanical",
        "fail" if bad_role else "pass",
        "An unrecognised role weakens the reconstruction of what the user actually asked.",
        "Use a standard message role: system, user, assistant, tool, function.",
        n,
        bad_role,
    )

    no_io = step_spans_missing_io(spans)
    s1 = _check(
        "S1_step_io",
        "detection",
        "fail" if no_io else "pass",
        "A step that records neither its input nor its output can be seen to have run, but not "
        "blamed — root-cause analysis cannot say which step produced the wrong answer.",
        "Set `input.value` and `output.value` (or the message families) on every LLM, TOOL and "
        "RETRIEVER span. Capturing only the model call leaves the tools around it opaque, and "
        "those are where most failures actually are.",
        n,
        no_io,
    )

    opaque = opaque_spans(spans)
    # Ratio over the whole trace, and only once the trace is big enough for a ratio to mean
    # something. Reported, never fatal: noise costs attention and money, not readability.
    dense_enough = n >= C.OPAQUE_MIN_SPANS and len(opaque) / n > C.OPAQUE_SPAN_WARN_RATIO
    s2 = _check(
        "S2_signal_density",
        "soft",
        "warn" if dense_enough else "pass",
        f"{len(opaque)} of {n} spans carry neither a span kind nor any input/output — a reader "
        "filters more than it reads, and you pay ingest and retention for spans nothing can use.",
        "Turn off auto-instrumentation for the mechanical layers (database, HTTP client, cache, "
        "queue) on this service, or give those spans a kind and text if they are genuinely part "
        "of the story. Keep the spans that describe the agent's own steps.",
        n,
        opaque,
    )

    no_usage = zero_usage_spans(spans)
    m7 = _check(
        "M7_token_usage",
        "mechanical",
        "warn" if no_usage else "pass",
        "LLM spans report no token usage — cost per run, budget and cost-regression attribution "
        "are all blind.",
        "Record `llm.token_count.prompt` and `llm.token_count.completion` on every LLM span. Most "
        "SDK instrumentors do this for you; a hand-rolled client usually has the counts in the "
        "provider response and drops them.",
        n,
        no_usage,
    )

    detectable = detectable_spans(spans)
    s3 = _check(
        "S3_detectable_work",
        "soft",
        "warn" if not detectable else "pass",
        f"No span here carries a kind a detector looks at (LLM, AGENT, TOOL, RETRIEVER) — "
        f"all {n} are structure. The trace is well-formed and there is nothing in it to detect.",
        "If this request runs an agent, label its steps: the model call LLM, the things it calls "
        "TOOL or RETRIEVER. If it does not — a CRUD or health endpoint — it is not agent traffic, "
        "and tracing it costs storage while diluting the sample the product grades.",
        1,
        0 if detectable else 1,
    )

    weight = payload_weight(spans)
    too_heavy = weight.total > C.PAYLOAD_TRACE_WARN_BYTES
    # Evidence only when it will be read: a passing check's is never rendered, and the labels
    # come from the same walk either way. Reported, never fatal — a heavy trace is still a
    # readable one, and the cost is a platform bill the developer is the one to weigh.
    s4 = _check(
        "S4_payload_weight",
        "soft",
        "warn" if too_heavy else "pass",
        f"This trace carries {_human_bytes(weight.total)} of attribute text — at that size the "
        "trace is a second copy of the request's payload, stored again on every run and every "
        "retry.",
        "Read the evidence first: one attribute carrying most of it is a blob inlined into the "
        "span — base64 image or document data in `input.value` is the usual shape — and the fix "
        "is to record a reference instead, the object's URL, key or hash. Weight spread evenly "
        "across spans is the other case, and there the fix is to truncate each span's text to a "
        "readable prefix. Detection reads the text, not the whole file.",
        1,
        1 if too_heavy else 0,
        evidence=_heaviest_labels(weight) if too_heavy else (),
    )

    checks = (r0, r1, r1b, r3, m1, m2, m3, m4, m5, m6, m7, s1, s2, s3, s4)
    root_label = roots[0].name if len(roots) == 1 else ""
    return TraceGrade(
        trace_id=spans[0].trace_id,
        label=root_label,
        graded=True,
        checks=checks,
        verdict=rollup(r1, r3, m1, checks),
    )


def rollup(r1: Check, r3: Check, m1: Check, checks: tuple[Check, ...]) -> str:
    """Fold per-check verdicts into the trace verdict — first match wins.

    ``entry_missing`` outranks everything because a trace nobody can re-run is not a candidate
    for a verified fix, however clean the rest of it is.
    """
    if r1.verdict == "fail":
        return "entry_missing"
    if r3.verdict in ("warn", "fail") or m1.verdict == "fail":
        return "detection_gap"
    if any(c.verdict == "fail" and c.tier == "detection" for c in checks):
        return "detection_gap"
    if any(c.verdict == "fail" for c in checks):
        return "degraded"
    return "entry_seatable"


def grade_sample(traces: list[list[Span]]) -> SampleGrade:
    """Grade many traces and aggregate each check worst-wins across them."""
    graded = [g for spans in traces if spans for g in (grade(spans),) if g.graded]
    if not graded:
        return SampleGrade(verdict="ungraded")

    aggregated: list[Check] = []
    for cid in [c.id for c in graded[0].checks]:
        per = [next(c for c in g.checks if c.id == cid) for g in graded]
        worst = max(per, key=lambda c: C.VERDICT_RANK.get(c.verdict, 0))
        evidence: tuple[str, ...] = ()
        for check in per:
            evidence += tuple(e for e in check.evidence if e not in evidence)
        aggregated.append(
            worst.model_copy(
                update={
                    "sample_size": len(graded),
                    "fail_count": sum(1 for c in per if c.failing),
                    "evidence": evidence[: C.EVIDENCE_LIMIT],
                }
            )
        )

    by_id = {c.id: c for c in aggregated}
    verdict = rollup(
        by_id["R1_entry_seat"],
        by_id["R3_error_status"],
        by_id["M1_kind_present"],
        tuple(aggregated),
    )
    return SampleGrade(traces=tuple(graded), checks=tuple(aggregated), verdict=verdict)


def group_by_trace(spans: list[Span]) -> list[list[Span]]:
    """Split a flat span list into traces, preserving first-seen order."""
    by_trace: dict[str, list[Span]] = {}
    for span in spans:
        by_trace.setdefault(span.trace_id, []).append(span)
    return list(by_trace.values())


def _group_by_fix(
    traces: list[TraceGrade], ids: set[str] | None, exclude: bool
) -> list[dict[str, Any]]:
    by_fix: dict[str, dict[str, Any]] = {}
    for grade_ in traces:
        for check in grade_.failures():
            if ids is not None and (check.id in ids) is exclude:
                continue
            entry = by_fix.setdefault(
                check.fix,
                {
                    "fix": check.fix,
                    "checks": set(),
                    "traces": 0,
                    "finding_class": C.MECHANICAL,
                    "evidence": [],
                },
            )
            entry["checks"].add(check.id)
            entry["traces"] += 1
            # Evidence from across the group, deduped and capped. A rolled-up finding still has
            # to say where to look, and one trace's sites are rarely the whole story.
            for site in check.evidence:
                if site not in entry["evidence"] and len(entry["evidence"]) < C.EVIDENCE_LIMIT:
                    entry["evidence"].append(site)
            # One fix can be reached by two checks. If either of them is a decision, the whole
            # entry is — an automated pass that applies half of a fix is worse than none.
            if check.finding_class == C.ARCHITECTURAL:
                entry["finding_class"] = C.ARCHITECTURAL
    ranked = sorted(by_fix.values(), key=lambda e: -e["traces"])
    return [{**e, "checks": sorted(e["checks"])} for e in ranked]


def fix_summary(traces: list[TraceGrade]) -> list[dict[str, Any]]:
    """Distinct fixes that would move a verdict, most-clearing first.

    One missing root span usually explains every failing trace in the sample. Printing that fix
    forty times reads as forty problems and buries the two that are actually different.

    ``NEVER_FATAL`` checks are excluded, and that exclusion does two things at once. It stops a
    cost warning being ranked above the check that decides whether a request can be re-run —
    SKILL.md tells the agent to hand this list over without reordering it, so the order has to
    be the truth. And because an ``entry_seatable`` trace can only ever carry those warnings, it
    also keeps every count here inside the failing-trace total the header prints; a plan that
    said "clears 5 traces" under a header reading "2 below" was the visible shape of the bug.
    """
    return _group_by_fix(traces, set(C.NEVER_FATAL), exclude=True)


def applicability_summary(traces: list[TraceGrade]) -> list[dict[str, Any]]:
    """The never-fatal findings, over every trace including the ones that passed.

    These have to be counted across the whole sample, not the failing part of it: a trace that
    is well-instrumented and three megabytes heavy is ``entry_seatable``, so it appears nowhere
    else in the report, and that is precisely the case the weight check exists for.
    """
    return _group_by_fix(traces, set(C.NEVER_FATAL), exclude=False)
