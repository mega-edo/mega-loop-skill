"""The MEGA Loop trace contract, as constants — the one file that mirrors upstream.

Every value here was read out of the `mega-loop` source, and each block cites the module it
came from. Keeping them together (rather than inlined where they are used) is deliberate: the
stated risk for this skill is *drifting from the real contract*, and drift is only auditable if
there is exactly one page to diff against upstream.

Three of these constants are narrower than they look, and widening any of them makes the
validator lie:

* ``STEP_KINDS`` — three kinds, not five. A message on a CHAIN/AGENT span never seats an entry.
  Widen it and the validator says "readable" where MEGA Loop says ``entry_missing``.
* ``CONTENT_ERROR_KINDS`` — LLM/AGENT are excluded on purpose. Model prose discusses errors all
  the time; that is not a failed span.
* ``ERROR_SENTINELS`` — a tool's refusal vocabulary, not a stack-trace vocabulary. Upstream:
  "Kept tight on purpose: broadening trades precision for recall."
"""

from __future__ import annotations

# --- span kinds (mega_loop/readiness.py, mega_loop/normalize.py) ---------------

#: OpenInference SpanKind is required + enumerated. ``SPAN`` is NOT a member — it is the
#: normalizer's stand-in for an *absent* kind, so it reads as absent, not as present-non-enum.
SPAN_KINDS = frozenset(
    {
        "LLM",
        "CHAIN",
        "TOOL",
        "RETRIEVER",
        "RERANKER",
        "EMBEDDING",
        "AGENT",
        "GUARDRAIL",
        "EVALUATOR",
        "PROMPT",
    }
)

#: Reads as "no kind was set". Distinct from a present-but-unknown kind, which is the real
#: detect blind spot and therefore the harder verdict.
ABSENT_KINDS = frozenset({"", "SPAN"})

#: The kinds any detector actually filters on (mega_loop/detect.py: ``TOOL_KINDS`` = TOOL,
#: RETRIEVER and ``_GENERATIVE_KINDS`` = LLM, AGENT). Mirrored, not chosen — every detector in
#: that module narrows to one of these two sets before it looks at anything.
#:
#: CHAIN is deliberately absent, and that is the whole point of the check that uses this. A
#: platform that hands an unlabelled span a default kind (Langfuse types a bare OTLP span as
#: ``span``, which lowers to CHAIN) produces traces that look fully classified and that every
#: detector still walks straight past.
DETECTOR_KINDS = frozenset({"LLM", "AGENT", "TOOL", "RETRIEVER"})

#: The kinds the gate reconstructs its text ladder over (mega_loop/replay/graph.py). Exactly
#: three. See the module docstring before touching this.
STEP_KINDS = frozenset({"LLM", "TOOL", "RETRIEVER"})

#: Structural spans whose output is a tool/business result rather than model prose — the only
#: kinds where a leading error idiom under an OK status is worth reporting (mega_loop/detect.py).
CONTENT_ERROR_KINDS = frozenset({"TOOL", "RETRIEVER", "SPAN", "CHAIN"})

KNOWN_ROLES = frozenset({"system", "user", "assistant", "tool", "function"})

# --- error-in-OK-content (mega_loop/detect.py) --------------------------------

#: Only the head of the output is matched, lowercased.
HEAD_CHARS = 120

#: Longer than this and the text is prose, not a tool's rejection — skip the span entirely.
MAX_ERROR_REPLY_CHARS = 2_000

#: Verbatim from ``detect._ERROR_SENTINELS``. The trailing spaces are load-bearing: "could not "
#: must not match "could nothing". Do not add ``Traceback`` / ``Exception`` / HTTP status text —
#: MEGA Loop does not match on those, so flagging them reports failures it never raises.
ERROR_SENTINELS = (
    "cannot write",
    "already exists",
    "permission denied",
    "not found",
    "no such file",
    "access denied",
    "operation failed",
    "could not ",
    "failed to ",
    "unable to ",
    '{"error"',
    "error:",
)

# --- OpenInference keys -------------------------------------------------------

OI_KIND = "openinference.span.kind"
OI_MODEL = "llm.model_name"
OI_TOK_PROMPT = "llm.token_count.prompt"
OI_TOK_COMPLETION = "llm.token_count.completion"
OI_TOK_TOTAL = "llm.token_count.total"
OI_IN_MESSAGES = "llm.input_messages"
OI_OUT_MESSAGES = "llm.output_messages"
OI_INVOCATION = "llm.invocation_parameters"

#: Indexed families whose index sits directly after the prefix. ``tool_calls`` is absent on
#: purpose — it nests under the output-message index and is checked separately.
INDEX_FAMILIES = (OI_IN_MESSAGES, OI_OUT_MESSAGES, "retrieval.documents")

# --- foreign → OpenInference (mega_loop/normalize.py) -------------------------

SCALAR_TOKENS = {
    "gen_ai.usage.input_tokens": OI_TOK_PROMPT,  # gen_ai current
    "gen_ai.usage.output_tokens": OI_TOK_COMPLETION,
    "gen_ai.usage.prompt_tokens": OI_TOK_PROMPT,  # legacy aliases
    "gen_ai.usage.completion_tokens": OI_TOK_COMPLETION,
    "llm.usage.total_tokens": OI_TOK_TOTAL,  # Traceloop-only total
}

MODEL_SOURCES = ("gen_ai.request.model", "gen_ai.response.model")

OP_NAME_KIND = {
    "chat": "LLM",
    "text_completion": "LLM",
    "generate_content": "LLM",
    "embeddings": "EMBEDDING",
    "execute_tool": "TOOL",
    "invoke_agent": "AGENT",
    "create_agent": "AGENT",
    "invoke_workflow": "CHAIN",
    "retrieval": "RETRIEVER",
}

REQUEST_TYPE_KIND = {
    "chat": "LLM",
    "completion": "LLM",
    "embedding": "EMBEDDING",
    "rerank": "RERANKER",
}

TRACELOOP_KIND = {"agent": "AGENT", "tool": "TOOL", "workflow": "CHAIN", "task": "CHAIN"}

#: Langfuse writes its own family instead of OpenInference keys, so a Langfuse-instrumented
#: pipeline normalizes to unclassified spans and every kind-filtering detector goes silent.
LANGFUSE_KIND = {
    "generation": "LLM",
    "agent": "AGENT",
    "tool": "TOOL",
    "chain": "CHAIN",
    "retriever": "RETRIEVER",
    "embedding": "EMBEDDING",
    "evaluator": "EVALUATOR",
    "guardrail": "GUARDRAIL",
    "span": "CHAIN",
    "event": "CHAIN",
}

LF_PREFIX = "langfuse.observation."
LF_TYPE = f"{LF_PREFIX}type"
LF_USAGE = f"{LF_PREFIX}usage_details"

LANGFUSE_SCALARS = {
    f"{LF_PREFIX}input": "input.value",
    f"{LF_PREFIX}output": "output.value",
    f"{LF_PREFIX}model.name": OI_MODEL,
}

LANGFUSE_USAGE = {"input": OI_TOK_PROMPT, "output": OI_TOK_COMPLETION, "total": OI_TOK_TOTAL}

REQUEST_PARAM_PREFIX = "gen_ai.request."
REQUEST_PARAM_LEAVES = frozenset(
    {
        "temperature",
        "top_p",
        "top_k",
        "max_tokens",
        "frequency_penalty",
        "presence_penalty",
        "stop_sequences",
    }
)

# --- token accounting (mega_loop/detect.py zero_usage_spans, readiness.py M7) --

#: Below this much output text, zero tokens is plausible rather than missing — a span that
#: returned nothing may honestly have ~0 completion tokens. Upstream's floor, not a guess.
MIN_SUBSTANTIVE_CHARS = 200

# --- signal density (this skill) ----------------------------------------------
#
# The three constants below are NOT mirrored from upstream — MEGA Loop reads whatever it is
# given and has no opinion on trace size. They exist because "readable" and "worth reading" are
# different questions, and only the first one had a check.
#
# The shape they describe is generic and vendor-neutral: auto-instrumentation for a database
# driver, an HTTP client, a cache or a queue emits one span per round-trip, none of which carry
# an OpenInference kind or any input/output. Nothing is malformed — the trace simply buries the
# handful of steps a reader cares about under mechanical detail, and pays ingest and retention
# for the privilege. That is a judgement about the trace, not about any particular library, so
# nothing here names one.

#: A span carrying NEITHER a recognised kind NOR any input/output text. Not "a span we dislike":
#: one with a kind still describes the shape of the run, and one with text still contributes to
#: the reconstruction, so a span is only opaque when it offers neither.
#:
#: Half. Below that, a reader skims past the mechanical spans; above it, they are filtering more
#: than reading, and a step that failed is genuinely hard to find by eye. It is a reporting
#: threshold, not a contract — crossing it never makes a trace unreadable, which is why the check
#: that uses it warns and never fails.
OPAQUE_SPAN_WARN_RATIO = 0.5

#: Below this a trace is too small for the ratio to mean anything — three opaque spans out of
#: four is noise in the statistical sense, not in the instrumentation sense.
OPAQUE_MIN_SPANS = 8

#: Keys that make a span worth reading even without a kind. Any one of them is enough.
SIGNAL_KEYS = ("input.value", "output.value", "llm.input_messages", "llm.output_messages")

# --- payload weight (this skill) ----------------------------------------------
#
# Also not mirrored: MEGA Loop reads whatever it is given and has no opinion on how heavy a
# trace is. The cost lands on the developer's platform bill and on every retry of the same
# request, which is why it is reported and never fatal.

#: A trace heavier than this is worth telling the developer about. One megabyte is roughly where
#: a trace stops being a record of a request and starts being a second copy of its payload — an
#: agent that inlines a base64 image, a whole document or a page of scraped HTML crosses it on a
#: single span. Chosen to sit under the 4 MB default OTLP message limit, so a trace that trips
#: this is still being delivered but is already close to the edge where spans get dropped.
PAYLOAD_TRACE_WARN_BYTES = 1_000_000

#: Attributes lighter than this never appear as evidence. Naming a 300-byte prompt beside a
#: 20 MB image teaches the reader nothing about where their bytes went.
PAYLOAD_ATTR_MIN_BYTES = 50_000

# --- what a finding asks of the developer (this skill) ------------------------
#
# Every check is one of two kinds of work, and the difference decides whether trace-fix can act
# on it. A *mechanical* finding is satisfied by setting an attribute on a span the code already
# creates. An *architectural* one asks where spans come from, how context flows, what reaches
# the exporter, or whether this traffic is worth tracing at all — questions with more than one
# defensible answer, which is a decision to put in front of the developer rather than an edit to
# apply for them.
#
# The vocabulary lives here because report.py renders it; which check is which lives in
# checks.py, beside the ids it keys.

MECHANICAL = "mechanical"
ARCHITECTURAL = "architectural"

#: How each class reads to a developer. The wording is the handoff contract: someone who reads
#: "trace-fix can apply this" should be able to run that verb and have it work.
FINDING_CLASS_GLOSS = {
    MECHANICAL: "trace-fix can apply this",
    ARCHITECTURAL: "needs your decision",
}

#: The checks with no ``fail`` branch: they only ever warn. Documentation vocabulary — the
#: report's "four of fifteen are never fatal" wording, and the drift test that pins it.
#:
#: It is deliberately *not* what splits the fix plan from the advisory block. That split asks
#: whether a finding moved its trace's verdict, which ``Check.blocking`` reads off the verdict
#: itself; a set of ids cannot answer it, because a check with both branches (``M1_kind_present``)
#: is blocking on one trace and advisory on another. Adding an id here to keep it out of a plan
#: would change nothing and hide a real ``fail``.
NEVER_FATAL = frozenset(
    {
        "S2_signal_density",
        "S3_detectable_work",
        "S4_payload_weight",
        "M7_token_usage",
    }
)

#: Checks whose ``warn`` ``rollup`` acts on, so a warn from them blocks like a ``fail``.
#:
#: A transcription of one ``rollup`` line — ``r3.verdict in ("warn", "fail")`` — and it has to
#: stay one. ``R3_error_status`` grades ``warn``/``not_observed`` and never ``fail``, so without
#: this its real failures would be filed as advice. Change ``rollup``, change this, and the
#: drift test that compares them will tell you if you changed only one.
WARN_IS_FATAL = frozenset({"R3_error_status"})

#: Sites named per finding before the tail is folded into a count. One number, because a reader
#: widening the evidence should not have to find four of them.
EVIDENCE_LIMIT = 5

# --- verify traffic (mega_loop/normalize.py, adr/0008) ------------------------

#: MEGA Loop stamps its own verification re-runs and excludes them from detection. A developer's
#: sample should exclude them too, or the validator grades traffic the product never sees.
VERIFY_MARK_KEY = "mega.verify"
VERIFY_ENVIRONMENT = "mega-verify"

# --- verdicts (mega_loop/readiness.py) ----------------------------------------

#: Worst-wins ordering when aggregating one check across many traces.
VERDICT_RANK = {"pass": 0, "not_observed": 1, "warn": 2, "fail": 3}

#: The healthy verdict is ``entry_seatable``. These five words are what the MEGA Loop dashboard
#: shows the same developer — do not invent a sixth.
VERDICT_GLOSS = {
    "entry_seatable": "MEGA Loop can read this trace",
    "degraded": "readable, but parts of it are malformed",
    "detection_gap": "readable, but failures here will be missed",
    "entry_missing": "MEGA Loop cannot re-run this request at all",
    "ungraded": "no spans to grade",
}
