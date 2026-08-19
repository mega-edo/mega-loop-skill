---
name: trace-analyze
description: >
  Grade an AI agent's traces against the same readiness contract MEGA Loop runs internally, and
  produce a report with a fix for every finding — read-only, no edits. Use when the user's
  traces are missing, fragmented or ignored, when MEGA Loop reports low trace readiness, or when
  they ask "are my traces good enough for MEGA Loop". To then apply the fixes, hand off to
  trace-fix.
allowed-tools: Read, Bash, Glob, Grep
---

# mega-loop trace-analyze — grade traces against the contract (read-only)

Grade the user's traces the way MEGA Loop grades them internally, and hand back a report that says —
for each trace — whether MEGA Loop can use it, and exactly what to change if not. **Reads and
reports; never edits code** — applying the fixes is **trace-fix**'s job. It runs the validator
locally, so unlike the diagnose / fix verbs it needs no active project and no PAT.

> Paths written `${CLAUDE_PLUGIN_ROOT}/…` point inside this installed plugin. `trace-runtime/` is
> the shared validator bundle. Everything without that prefix is in the user's own repo.

## Running the validator

Prefer `uv run` — it reads the script's inline dependency metadata and provisions pydantic/httpx in
a throwaway environment, touching nothing in the user's project:

```bash
# Against real traces (needs the platform's read credentials in the environment):
uv run "${CLAUDE_PLUGIN_ROOT}/trace-runtime/scripts/validate_traces.py" --platform <langfuse|phoenix|langsmith> --last 50

# Against the source (Python only), before any traces exist — no credentials required:
uv run "${CLAUDE_PLUGIN_ROOT}/trace-runtime/scripts/validate_traces.py" --source .

# Against a single exported trace file:
uv run "${CLAUDE_PLUGIN_ROOT}/trace-runtime/scripts/validate_traces.py" --file <trace.json>
```

No `uv`? Run `pip install pydantic httpx` once, then use `python` in place of `uv run`.

## What to run, and when

1. **If they already emit traces, grade those first** (`--platform … --last 50`). It tells you which
   of the problems you are dealing with and gives you a real before-number for trace-fix to beat.
2. **No traces yet, or no credentials? Grade the source** (`--source .`). This works with nothing
   emitted, and every finding names a `file:line` to open. A clean board here is **not** a pass —
   only real traces settle it — but it is the fastest way to start.

   Read the language line before the verdict. This grader parses Python; on a repository written
   in something else it says so, and that message is the finding. If the repo emits **nothing at
   all**, grading it is the wrong verb — hand off to `/mega-loop:trace-gen`, which instruments
   first and grades after.

Detect the stack while you are there: `pyproject.toml` / `requirements.txt` / `package.json`, the
web framework, the LLM SDK, and — the one that decides how much of the work is propagation —
whether the request crosses a process boundary (a second service, a worker, a queue).

## The report: four questions, in priority order

The validator rolls fifteen checks into one **verdict** per trace — the worst thing wrong wins.
Present it as four answers, and keep question 4 on its own line, because it is **not** part of the
verdict.

| verdict | meaning | priority |
|---|---|---|
| `entry_missing` | the request cannot be re-run — no fix can be verified | **fix first, nothing else matters** |
| `detection_gap` | readable, but failures here will be missed | fix second |
| `degraded` | readable and detectable, but some spans are malformed | fix third |
| `entry_seatable` | MEGA Loop can read the trace | done |

### 1 · Can the request be re-run at all? → `entry_missing`

- `R1_entry_seat` — the one hard gate: is `input.value` on the root span? Without it no fix can be
  verified, so an `R1` failure alone forces `entry_missing` however clean the rest is.

### 2 · Will failures be seen? → `detection_gap`

Readable, but failures here slip past the detectors:
- `R3_error_status` — a failing step set status ERROR, or hid it as `{"success": false}` under OK?
- `S1_step_io` — does every LLM/TOOL/RETRIEVER span carry input **and** output? Without both a step
  can be seen to have run but not blamed.
- `M1_kind_present` — every span has a recognised `openinference.span.kind`? An unknown kind makes
  the span invisible to every detector, silently — which is why a bare kind failure lands here, not
  in question 3.

### 3 · Where else is the trace malformed? → `degraded`

Readable and detectable, but something is off; none of these block detection:
- `M2_tree_intact` — **fragmentation**: a dangling parent means the request became several traces;
  context is not propagating across a hop. The hardest and most common. See
  `${CLAUDE_PLUGIN_ROOT}/trace-runtime/references/context-propagation.md`.
- `R1b_clean_root` — one clean CHAIN/AGENT root span? Without it verification falls back to heuristic
  text reconstruction instead of replaying the real entry.
- `R0_addressable` — every span carries a trace id? Spans without one are dropped at ingest.
- `M3_duration_sane` / `M4_index_contiguous` / `M5_status_coherent` / `M6_role_known` — negative
  latency, gapped indices, a status message on an OK span, an unknown message role.

### 4 · Is this trace worth it to MEGA Loop? — applicability (reported, never fatal)

These are **soft warnings that do not change the verdict** — a trace can be `entry_seatable` and
still be useless. Surface them on their own line so nobody reads a passing verdict as "valuable":

- `S3_detectable_work` — does any span carry a kind a detector looks at (LLM / AGENT / TOOL /
  RETRIEVER)? A trace can be perfectly well-formed with a kind on every span and still be **all
  CHAIN** — nothing to detect. Usually that means it is not agent traffic (a CRUD or health
  endpoint), and tracing it dilutes the sample the product grades.
- `S2_signal_density` — what fraction of spans carry neither a kind nor any text? Auto-instrumented
  database / HTTP / cache / queue spans are readable but pure noise; past half a trace you pay
  ingest and retention for spans nothing can use.
- `S4_payload_weight` — how many bytes of attribute text does the trace carry? Past a megabyte
  the trace is a second copy of the request's payload, stored again on every run and every retry.
  A base64 image or a whole document inlined into `input.value` is the usual cause. The evidence
  names the attribute, so the fix is "store a reference, not the bytes" — not "trace less".
- `M7_token_usage` — do LLM spans record token counts? Without them cost, budget and
  cost-regression attribution are blind.

## The summary is the plan

Every failing check is followed by a `→` line that says what to change. The summary orders the
fixes by **how many traces each one clears** — a single missing root span usually explains a whole
batch of `entry_missing` verdicts. Hand that ordered list to trace-fix; do not reorder it by taste.

Each entry also says **who has to do it**, and that is the half to read out loud:

- *trace-fix can apply this* — **mechanical**: setting an attribute on a span the code already
  creates.
- *needs your decision* — **architectural**: where spans come from, how context flows, what
  reaches the exporter, whether this traffic belongs in a trace at all. More than one answer is
  defensible, so it is a question for the developer, not an edit to apply on their behalf.

Read the split back to them before offering the handoff. A plan that is all decisions is not a
trace-fix job, and saying so is what keeps the offer worth taking up.

The four never-fatal checks are **not in that plan**. They get their own `Worth knowing` block,
counted over every trace including the ones that passed — a trace can be `entry_seatable` and
three megabytes heavy, and it appears nowhere else in the report. Keep them out of the fix
ordering when you relay it: ranking a cost warning above the check that decides whether a request
can be re-run is how a correct list becomes a misleading one.

The report closes with a **`Score:` line** — `n/total entry_seatable (pct%) · verdict`. It is one
line on purpose: it pastes into a status update, and re-running after the fix gives a second one
to set beside it. Point the user at it; the before/after pair is the thing they will be asked for.

## Handoffs

- The user wants to **apply** the fixes → switch to **trace-fix** (`/mega-loop:trace-fix`),
  and give it this report so it starts from the `Score:` line. Hand over the **mechanical**
  entries; walk the architectural ones with the user first, because trace-fix would be guessing
  at a decision only they can make.
- Verdicts are clean and applicability is fine → the traces are ready; suggest
  **`/mega-loop:connect`** to point MEGA Loop at the project and see the bugs it finds.

## Guardrails

- **Read-only.** Never edit the user's code or the contract here — this skill reports.
- **`entry_seatable` is not a promise of a fix.** It means the trace is readable. Say that, not more.
- **Applicability is advice, not a defect.** `S2` / `S3` / `S4` / `M7` never block. Report the ratio and the
  way out; do not tell the user their instrumentation is "broken" when it is merely expensive or
  not agent traffic.
- **Never invent a `file:line`.** In `--source` mode report a location only when a finding anchors
  to one.
- **Do not commit exported traces.** They carry real prompts and real user text.
