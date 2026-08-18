---
name: trace-gen
description: >
  Add tracing to an agent that emits none, then prove the first traces are readable by running the
  app and grading what came out. Use when a repository has no instrumentation at all, when the
  user asks how to start tracing, or when MEGA Loop has no traces to read because none are being
  sent. Use trace-analyze when traces already exist; use trace-fix when they exist and fail.
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

# mega-loop trace-gen — instrument from nothing, then measure

Start where there is no telemetry and finish with traces MEGA Loop can read. **You decide what
gets measured**; the kit only supplies the plumbing.

This verb exists because the greenfield case is a different job from the repair case. trace-fix
turns a failing report into a passing one — it starts from evidence. Here there is none, and the
first real work is deciding what a request *is* in this codebase. Getting that wrong produces a
tidy trace of the wrong thing, which grades well and helps nobody.

> Paths written `${CLAUDE_PLUGIN_ROOT}/…` point inside this installed plugin. `trace-runtime/` is
> the shared validator bundle; `trace-runtime/kits/` holds templates to copy into the user's repo,
> not dependencies of this plugin. Everything without that prefix is in the user's own repo.

## Before anything, check the stack is one you can serve

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/trace-runtime/scripts/validate_traces.py" --source .
```

Read the language line, not the verdict. A clean board here means only that the Python it could
read is fine — on a repository this grader cannot parse it says so outright, and that message is
the answer to whether you can continue.

**Kits ship for Python and Node.** For anything else — Go, Java, Ruby, .NET — say so plainly
rather than improvising: the OpenTelemetry SDK for that language is mature and the OpenInference
attribute names are the same strings, so the work is doable, but a kit you invent on the spot is
one nobody has run. Offer to write the spans by hand against the language's own SDK, and be clear
that the result is unproven until it runs.

## Step 1 — find out what one request is

This is the step that decides whether any of the rest is worth having. Read the code; do not ask
the user to describe it.

- **The entry point.** An HTTP route, a CLI command, a queue consumer, a scheduled job. Find where
  the process takes work in.
- **The unit.** One user question? One ticket? One batch of a thousand rows? The unit is whatever
  a person would re-run when they say "this answer was wrong" — that is the definition, and it is
  the one the whole contract rests on.
- **The steps inside it.** Retrieval, tool calls, the model call, post-processing.
- **The boundaries.** Does a request cross a process, a queue, a thread pool? Note every one now;
  each is a place a single request becomes several traces, which is the hardest failure to fix
  later and the cheapest to prevent today.

Say what you found before you write anything. If the unit is genuinely ambiguous — a batch job
where either the batch or the row could be the unit — that is worth one question to the user,
because instrumenting the wrong one wastes the whole exercise.

## Step 2 — install the kit

Copy the kit for the stack into the repo:

- Python — `${CLAUDE_PLUGIN_ROOT}/trace-runtime/kits/python/`
- Node — `${CLAUDE_PLUGIN_ROOT}/trace-runtime/kits/node/`

Each carries a `README.md`, a setup module, and a worked example. Call setup once, first thing in
the entry point, before the app imports anything that might emit.

Wire the exporter to wherever the user's traces go. The kit READMEs cover the environment
variables; Langfuse needs OTLP over **HTTP** with basic auth, which is not the same exporter as a
gRPC collector.

## Step 3 — write the spans

**One root span per request**, kind `CHAIN` or `AGENT`, carrying `input.value` — the request as it
arrived, scrubbed. Everything else hangs under it.

Then label the steps for what they are:

| Step | Kind | Must carry |
|---|---|---|
| model call | `LLM` | prompt, answer, token counts |
| tool / function | `TOOL` | `input.value`, `output.value`, `tool.name` |
| retrieval | `RETRIEVER` | the documents, in the flat `retrieval.documents.N.*` layout |
| a sub-agent | `AGENT` | its own input and output |
| structure | `CHAIN` | nothing more than a name |

Reference: `${CLAUDE_PLUGIN_ROOT}/trace-runtime/references/span-kinds.md` for the keys each kind
expects, and `context-propagation.md` for every boundary found in step 1.

Three rules the contract will not forgive:

1. **A step with no input and no output can be seen to have run but not blamed.** That is the
   whole reason to trace it.
2. **A failure must set span status `ERROR`.** A caught exception that returns a polite message
   with an `OK` status is invisible to every detector.
3. **Never stamp a kind you have not decided.** `CHAIN` means "structure" and is the honest
   default; using it to silence a check on a step that really is a tool makes the trace worse
   while making the board look better.

## Step 4 — run it, and grade what comes out

A source with no traces cannot be graded. Nothing before this point is evidence.

Run the app the way a user would — a request, a ticket, a command — enough times to see more than
one path, then:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/trace-runtime/scripts/validate_traces.py" \
  --platform <langfuse|phoenix|langsmith> --last 20
```

Work every failure line: each is followed by a `→` with the exact fix. Re-run until the sample
reaches `entry_seatable`.

**Watch the sample composition, not just the verdict.** If the traffic you generated is mostly
health checks or one repeated call, a passing grade says nothing about the traffic that matters.
Grade a window wide enough to include the real work.

## Step 5 — hand back what it cost

Report what a reader can act on:

- the unit you chose, and why
- how many spans one request produces, and what each is for
- the verdict on real traces, before-and-after where there is a before
- every boundary from step 1 you did **not** instrument, and what that leaves unmeasured

## Applicability is not a defect

`S3_detectable_work` warns when a trace holds nothing a detector reads. On a CRUD or health
endpoint that is the true answer — the fix is to stop tracing it, not to add spans until the
warning goes away. Same for `S2_signal_density`: turn auto-instrumentation off for the mechanical
layers rather than burying them in more spans.

## Guardrails

- **Do not instrument what you did not read.** A span named after a function you guessed at is
  worse than no span.
- **Do not send anything anywhere without saying so.** The exporter target is the user's
  decision, and traces carry their users' text.
- **Scrub before recording.** A prompt or a tool argument is exactly where a token, an email or a
  customer name ends up.
- **This opens no PR and needs no PAT.** It is groundwork, so MEGA Loop has something to read.

## Handoffs

- Traces exist and you only want them graded → `/mega-loop:trace-analyze`
- Traces exist and fail → `/mega-loop:trace-fix`
- Traces are readable and you want the bugs in them → `/mega-loop:diagnose`
