---
name: trace-fix
description: >
  Fix an AI agent's instrumentation so its traces become usable by MEGA Loop — one clean trace per
  request, OpenInference-compliant — then re-run the validator to prove it. Edits the user's
  code. Use after trace-analyze finds problems, or when the user asks to make their traces pass
  MEGA Loop's readiness contract. To only see what is wrong without changing code, use
  trace-analyze. When the code emits NO traces at all, use trace-gen instead — this verb repairs
  instrumentation, it does not decide what to measure.
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

# mega-loop trace-fix — fix the instrumentation until traces pass

Turn a failing report into passing traces by editing the code that emits them — then let the
validator, not inspection, say it worked. You fix **instrumentation**; the trace is the result. It
edits code and runs the validator locally, so unlike the diagnose / fix verbs it needs no active
project and no PAT — and it opens no PR: this is groundwork so MEGA Loop has usable traces to detect
on, not a bug fix.

> Paths written `${CLAUDE_PLUGIN_ROOT}/…` point inside this installed plugin. `trace-runtime/` is
> the shared validator bundle. Everything without that prefix is in the user's own repo.

## This verb repairs; it does not start from nothing

Everything below assumes spans already exist and something about them is wrong. A repository
with no instrumentation has no report to work from and no before-number to beat, and the first
real decision there — what one request *is* — is not a repair. That is `/mega-loop:trace-gen`.

## Start from a measurement

If trace-analyze already produced a report, work from it — it has the before-number and the fixes in
the order that clears the most traces. If not, take one measurement first so you can prove an
improvement later (same runner, `uv run`, self-contained):

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/trace-runtime/scripts/validate_traces.py" --source .
# or, if traces already exist:  --platform <langfuse|phoenix|langsmith> --last 50
```

No `uv`? `pip install pydantic httpx` once, then use `python` in place of `uv run`.

## Steps

1. **Apply the kit for the stack** — `${CLAUDE_PLUGIN_ROOT}/trace-runtime/kits/python/` or
   `${CLAUDE_PLUGIN_ROOT}/trace-runtime/kits/node/`. These are templates to copy into the repo, not
   dependencies of this plugin. Install the tracer, call `setup_tracing` first thing in the
   entrypoint, and wrap each user request in a **root span** of kind CHAIN or AGENT carrying
   `input.value`.

2. **Work the report top-down.** It is ordered by how many traces each fix clears, and one missing
   root span usually explains a whole batch of `entry_missing` verdicts. The common fixes, in the
   order they usually matter:
   - **Fragmentation** (`M2`) — one request became several traces; context is not propagating across
     a hop. Carry the W3C `traceparent` header into the next service / worker / task. This is the
     hardest and most common; see
     `${CLAUDE_PLUGIN_ROOT}/trace-runtime/references/context-propagation.md`.
   - **No entry input** (`R1`) — one line: `input.value` on the root span, so a fix can be verified.
   - **Missing span kinds** (`M1`) — set `openinference.span.kind`; an unknown kind is invisible to
     detectors. `${CLAUDE_PLUGIN_ROOT}/trace-runtime/references/span-kinds.md`. When the kindless
     spans are ones the app never opens — the ASGI server, the HTTP client, a background-task
     wrapper — the fix is a `SpanProcessor` default, and it **must** skip spans that already carry
     a kind. `on_start` runs after creation-time attributes are applied, so stamping
     unconditionally overwrites the LLM spans an instrumentor labelled correctly. See the reference
     before writing it.
   - **Failures reported as OK** (`R3`) — set span status ERROR when a step fails instead of
     returning an error as OK text.
   - **Steps with no input/output** (`S1`) — set `input.value`/`output.value` on every LLM, TOOL and
     RETRIEVER span. Tools are usually bare and are where most failures actually are.

3. **Re-run the validator and fix what it prints.** Every failure line is followed by a `→`
   instruction — do exactly that, then re-run. Repeat until the verdicts clear.

4. **Stop at `entry_seatable`**, on traces that crossed the boundaries you identified. Report the
   before/after: which verdicts moved, and how few attributes it actually took.

## Applicability is not a bug to fix

`S2_signal_density`, `S3_detectable_work` and `M7_token_usage` are warnings, never failures — do not
"fix" code to silence them:
- All-CHAIN, nothing to detect (`S3`) → if it is an agent request, **label** the steps (model call
  LLM, its calls TOOL / RETRIEVER). If it is a CRUD or health endpoint, it is simply not agent
  traffic — the fix is to stop tracing it, not to add spans.
- Noisy trace (`S2`) → turn off auto-instrumentation for the mechanical layers, don't add more spans.

## Handoffs

- The user only wants to **see** what is wrong, not change code → trace-analyze
  (`/mega-loop:trace-analyze`).
- Verdicts are green on real traces → suggest **`/mega-loop:connect`** so MEGA Loop can start finding
  bugs in the now-usable traces.

## Guardrails

- **Fix only the instrumentation the report names.** Add the spans, kinds and attributes that clear
  the findings — do not "helpfully" refactor the user's logic or restructure code while you are in
  there. The business behaviour must be untouched; diff it and see.
- **Do not widen the contract to make a check pass.** The constants in
  `${CLAUDE_PLUGIN_ROOT}/trace-runtime/src/trace_validator/contract.py` mirror MEGA Loop; loosening
  one makes the validator agree with you and disagree with the product. A check that looks wrong is a
  finding to report upstream, not a value to edit.
- **Never invent attribute keys.** If a value has no key in
  `${CLAUDE_PLUGIN_ROOT}/trace-runtime/references/trace-spec.md`, leave it off rather than guessing a
  name nothing reads.
- **`entry_seatable` is not a promise of a fix.** It means the trace is readable. Say that, not more.
- **Do not commit exported traces.** They carry real prompts and real user text.
