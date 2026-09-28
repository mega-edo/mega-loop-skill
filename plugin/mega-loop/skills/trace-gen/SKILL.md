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

On Node, the web framework decides how the kit is loaded and where the request is put, and the
Node README has a section for each — follow **NestJS** or **Next.js** there rather than the plain
recipe. The framework opens the root span before the handler runs, so a span you open in the
handler is a child: seat the request with `setRequestInput`, which reaches the real root.

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

**Do the loop on a local collector, and start it yourself.** The loop below runs the app several
times, and the early runs are the ones where the instrumentation is still wrong. Sent to the user's
platform they sit beside the good traces for good: every grade computed afterwards — this skill's,
and MEGA Loop's own — averages the attempts with the result, and a reader who sees `Degraded 16/69`
concludes the code is wrong when what is wrong is the history. Nothing un-mixes them later, and
clearing a customer's traces is not yours to do.

Start ONE of these. `uv` is what this plugin expects and Docker is not, so prefer it; either
listens on `http://localhost:6006`.

```bash
UV_HTTP_TIMEOUT=120 uvx arize-phoenix serve > /tmp/mega-loop-phoenix.log 2>&1 &
echo $! > /tmp/mega-loop-phoenix.pid
```

```bash
rm -f /tmp/mega-loop-phoenix.pid    # a pid left by an earlier uv run would mislead the wait
docker run -d --name mega-loop-phoenix -p 6006:6006 arizephoenix/phoenix
```

The raised timeout is not decoration: uv defaults to 30 s per request, and one index page in
Phoenix's dependency tree is large enough to exceed it on an ordinary link. Without it the install
fails at `watchfiles` and never starts.

Its output goes to a log rather than to your terminal. Left attached, a backgrounded process keeps
the Bash call open until it exits — and the log is what tells you why an install failed.

**Wait for it before sending anything.** The first run downloads a large package — measured at
three minutes here, longer than a Bash call's default two — and every span sent before it listens
is lost. The loop gives up rather than spinning forever when the install is the thing that failed.
If the call times out before Phoenix answers, raise the timeout or simply run it again: the install
carries on in the background, so the second wait is short.

```bash
for i in $(seq 150); do
  curl -sf -o /dev/null http://localhost:6006/ && break
  # only when uv started it: under Docker there is no pid file, and an absent one
  # must not read as "it died"
  [ -f /tmp/mega-loop-phoenix.pid ] && ! kill -0 "$(cat /tmp/mega-loop-phoenix.pid)" 2>/dev/null \
    && { tail /tmp/mega-loop-phoenix.log; break; }
  sleep 2
done
curl -sf -o /dev/null http://localhost:6006/ \
  || echo "Phoenix is not up — see /tmp/mega-loop-phoenix.log, or docker logs mega-loop-phoenix"
```

Stop it when the loop is done, by the id you saved. Two shorter-looking ways are both wrong here:
a job number (`%1`) is gone, because each Bash call runs in its own shell; and `pkill -f
"arize-phoenix serve"` matches the command line of the shell running the `pkill`, so it kills that
too.

```bash
kill "$(cat /tmp/mega-loop-phoenix.pid)"     # or: docker rm -f mega-loop-phoenix
```

Point the app at it with `OTEL_EXPORTER_OTLP_ENDPOINT`. The kit reads that before any platform
variable, and `dotenv` does not overwrite a variable the shell already set — so this wins over a
`.env` holding Langfuse credentials, and you never edit the user's file:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006 <run the app>
```

Drive it the way a user would — a request, a ticket, a command — enough times to see more than one
path, then grade what arrived:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/trace-runtime/scripts/validate_traces.py" \
  --platform phoenix --last 20
```

Work every failure line: each is followed by a `→` with the exact fix. Re-run until the sample
reaches `entry_seatable`.

**Watch the sample, not just the verdict.** A grade is only as good as the traffic behind it. If
what you drove was mostly health checks, or one call repeated, every trace can pass and still say
nothing about the paths that matter. Drive the real work, and drive it across any boundary a
request really crosses — a test inside one process passes whether or not context propagates, which
is the failure you are trying to rule out.

**Stop here and ask before the platform is involved at all.** The local loop is the last thing you
do on your own. Pointing the app at the user's platform changes where their application sends data,
and reading that platform is reading production — neither is yours to decide. So report the local
result, name what is still unproven, and wait:

> The instrumentation passes on a local collector: 12 traces, all `entry_seatable`. What local
> cannot prove is the export path — credentials, endpoint, and what your platform does to a span on
> ingest. Shall I drop the local override and grade what your platform has, once the app has served
> a request on its own configuration?

On a yes, and not before:

```bash
kill "$(cat /tmp/mega-loop-phoenix.pid)"     # or: docker rm -f mega-loop-phoenix
uv run "${CLAUDE_PLUGIN_ROOT}/trace-runtime/scripts/validate_traces.py" \
  --platform <langfuse|phoenix|langsmith> --last 20
```

Read it; do not feed it. The app exports on its own configuration, so whatever it really serves —
in a demo, the one request someone makes — is the confirmation. Generating extra requests would put
synthetic rows in someone's real data and prove nothing local did not already prove.

Two outcomes, both worth reporting:

- **Nothing arrived.** The spans were right and the export is not — a wrong key, a wrong URL, a
  blocked egress. That is the whole finding, and it is invisible from local.
- **They arrived and grade differently from local.** The spans left in one shape and came back in
  another, which is the platform's own mapping. Report both numbers rather than picking one.

On a no, stop at the local result and say plainly that the export path is untested.

## Step 5 — hand back what it cost

Report what a reader can act on:

- the unit you chose, and why
- how many spans one request produces, and what each is for
- the verdict on real traces, before-and-after where there is a before
- every boundary from step 1 you did **not** instrument, and what that leaves unmeasured
- **which traces the numbers came from** — the local run, the confirming platform run, or both —
  and any disagreement between the two

## Applicability is not a defect

`S3_detectable_work` warns when a trace holds nothing a detector reads. On a CRUD or health
endpoint that is the true answer — the fix is to stop tracing it, not to add spans until the
warning goes away. Same for `S2_signal_density`: turn auto-instrumentation off for the mechanical
layers rather than burying them in more spans. And `S4_payload_weight` warns when the trace is
carrying the payload rather than describing it — put a reference on the span, not the bytes.

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
