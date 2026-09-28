# Troubleshooting

Every entry says what caused it and what to do. When in doubt, start with `/mega-loop:status` — it
is the setup doctor and its output usually names the problem.

---

## Install

### `claude plugin marketplace add` fails

**Cause.** The repository is private, so the command fails if your GitHub account has not been
granted access, or you are not signed in to GitHub on this machine.

**Fix.** Confirm you can open
[github.com/mega-edo/mega-loop-skill](https://github.com/mega-edo/mega-loop-skill) in a browser
while signed in. If you get a 404 there, you do not have access yet — ask your MEGA Loop contact.
Then run the command again.

### Installing says a required option is not set

**Cause.** Not an error — the install succeeded. Both config keys are declared required, but only
`api_token` has no default, so it is the one Claude Code reports as not yet set.

**Fix.** Nothing, if you are starting with `/mega-loop:trace-gen`, `/mega-loop:trace-analyze` or
`/mega-loop:trace-fix` — those run the validator locally and never read the token. To list or fix
bugs, set it: `/plugin` → **mega-loop** → **configure** → the masked `api_token` field, then restart.

### The `/mega-loop:…` commands do not exist after installing

**Cause.** The plugin's server is loaded when Claude Code starts, so a session that was already
open does not see it.

**Fix.** Restart Claude Code, then run `/mega-loop:status`.

---

## Token and access

### It says I am unauthorized

**Cause.** The token is missing, expired, or was revoked. Tokens expire (90 days by default), and
MEGA Loop stores only a hash, so a lost token cannot be recovered.

**Fix.** Generate a fresh one in **Account settings → Personal Access Tokens**, then set it:
`/plugin` → **mega-loop** → **configure** → the masked `api_token` field. Restart Claude Code and
run `/mega-loop:status`.

### I cannot generate another token

**Cause.** You can hold up to 10 live tokens at a time.

**Fix.** Revoke one you no longer use on the same page, then generate the new one.

### I pasted my token into the chat by mistake

**Fix.** Treat it as leaked. Revoke it in **Account settings → Personal Access Tokens** right away,
generate a new one, and set the new one through the masked `/plugin` prompt. Anything typed in the
chat is written into the session transcript.

### My projects do not show up

**Cause.** Usually the plugin points at a different environment than the one your projects live in
(production and beta are separate accounts and separate data), or the token belongs to another
account.

**Fix.** Run `/mega-loop:status` and read the server and account it reports. To change the server:
`/plugin` → **mega-loop** → **configure** → set `base_url` to `https://loop.megacode.ai`
(production) or `https://loop-beta.megacode.ai` (beta). Restart Claude Code afterwards. Note that
projects and trace sources are created on the web, so a project you never created will not appear.

### It says `forbidden`

**Cause.** That project does not belong to your account.

**Fix.** Run `/mega-loop:connect` and pick from the list it shows you.

---

## Traces

### The validator says `LANGFUSE_BASE_URL or LANGFUSE_HOST is not set`

**Cause.** Claude only sees the environment it was started with. Variables exported after `claude`
was launched do not reach it.

**Fix.** Export the three Langfuse variables, then start `claude` again. Either URL name works —
`LANGFUSE_BASE_URL` is what Langfuse's current SDK documents, `LANGFUSE_HOST` is the same thing
before v4.

### Nothing arrives in Langfuse while a trace verb is working

**Cause.** Not an error. `trace-gen` and `trace-fix` do their whole loop on a local collector they
start themselves, so the attempts — the runs where the instrumentation is still wrong — never reach
your platform.

**Fix.** Nothing. Look at the local collector instead. The skill stops and asks before it reads
your platform at all.

### Nothing arrives in Langfuse after the verb has finished

**Cause.** `OTEL_EXPORTER_OTLP_ENDPOINT` is still set in your shell, from the local loop or from
something else. It takes precedence over every platform variable.

**Fix.** `unset OTEL_EXPORTER_OTLP_ENDPOINT`, then run the app again. If it is set in a `.env`,
remove it there — the kit reads it before it reads anything else.

### The local grade passes but the platform grade does not

**Cause.** The spans are written correctly and something between the app and the platform is not:
wrong keys, wrong URL, blocked egress, or the platform's own mapping changing a span on ingest.

**Fix.** Report both numbers rather than picking one. A difference between them is the finding, and
it is the one thing a local collector cannot show you.

### No LLM spans, and no error either

**Cause.** Two shapes, both silent. The OpenInference instrumentation for your SDK is not
installed. Or it is, but your SDK's major version is outside the range it patches — at 4.2.7 the
OpenAI one patches `^5`, `^6` and `^7` only, and pointed at anything else it registers, patches
nothing, and logs nothing.

**Fix.** `npm install @arizeai/openinference-instrumentation-openai` (or `-anthropic`,
`-langchain`, `-bedrock`); the kit loads whichever is present. If it is already installed, compare
your SDK's major against the range in that package's `init()`.

### Every span is its own trace

**Cause.** Context was not carried. On Node the kit loaded after the framework, so the modules that
pass `traceparent` were never patched. Or a queue, thread or process hop carries nothing.

**Fix.** On Node, load the kit first — `import './tracing/register'` as the first line of the entry
point, before anything else. Across a hop you own, pass `traceparent` yourself.

### A short script sends nothing

**Cause.** The process exited before the batch processor flushed.

**Fix.** Python: `trace.get_tracer_provider().shutdown()` before returning. Node:
`await shutdownTracing()`.

### A serverless function sends nothing

**Cause.** The platform froze the function as soon as it responded, before the batch was sent.

**Fix.** In Next.js, `after(() => flushTracing({ waitForRequest: true }))`. Elsewhere, flush before
returning.

### It says `No gradable traces found`

**Cause.** Nothing was sent inside the window being read — `--since-hours`, 24 by default.

**Fix.** Run the app so it serves a request, then grade again. Or widen the window. The count can
also be lower than what Langfuse shows you: the validator drops the traces MEGA Loop writes when it
verifies a fix, the same way ingest does. `--keep-verify-traffic` includes them.

---

## Fixing

### There are no bugs listed

**Cause.** One of three: the project has no trace source connected yet, it has never been analysed,
or the traces arrive but are too low-readiness for MEGA Loop to detect on — fragmented across a hop,
or missing the standard keys, so the detectors skip them silently.

**Fix.** Connect a trace source on the web dashboard and run the analysis once. If a source is
connected but nothing is found, the traces themselves are the suspect. If the app emits no
traces at all, `/mega-loop:trace-gen` starts from nothing; if it emits some, run `/mega-loop:trace-analyze`
to grade them against the readiness contract, then `/mega-loop:trace-fix` to repair the
instrumentation until they pass.

### Claude Code fixed the bug but will not say it is done

**This is on purpose.** While a fix is open, the session cannot declare it finished until MEGA Loop
returns a verdict. Your session runs the code and reports the evidence; the decision stays with the
engine, so a session can never approve its own work.

**Fix.** Let the check finish. If the verdict is FAIL, read the reason it gives and address that.

### The local fix did not open a pull request

**Cause.** On the path where your session does the fixing, the PR is opened from your machine, so it
needs `git` plus the CLI for your host: `gh` (GitHub), `glab` (GitLab), or `bkt` (Bitbucket).

**Fix.** Install and sign in to the missing CLI, then retry — whichever host you are on:

- **GitHub** — `brew install gh` (or `winget install GitHub.cli` / `scoop install gh`), then
  `gh auth login`.
- **GitLab** — `brew install glab`, which GitLab supports on macOS and Linux alike; other package
  managers are listed at `gitlab.com/gitlab-org/cli`. Then `glab auth login`.
- **Bitbucket** — `brew install avivsinai/tap/bitbucket-cli` (or `winget` / `scoop` /
  `go install`), then `bkt auth login https://bitbucket.org --kind cloud --web`.

Each `auth login` stores the credential in your OS keychain, so you never paste a token anywhere.
Bitbucket app passwords are not an option any more — they were retired in June 2026.

When it cannot open the PR the plugin stops honestly and leaves you a branch and a patch file, so
no work is lost — you can open the PR yourself.

### Asking to fix one bug returns the whole group

**This is on purpose.** Some bugs only make sense fixed together, so they ship as one coordinated
change. Run `/mega-loop:groups` to see which bugs travel together.

### A fix is already running

**Cause.** One fix at a time per bug.

**Fix.** Wait for it, or ask to restart it — say "restart the fix" and it will re-run.

### The engine's fix finished but opened no PR

**Fix.** Ask to see what it produced. The plugin can pull the engine's diff, the checks it ran, and
the reasoning behind each rejected attempt, so you can carry on from its work instead of starting
over.

---

## Still stuck

Run `/mega-loop:status` and include its output when you ask for help. It reports your setup, the
server, the account, the connected project, and anything currently running — which is most of what
anyone needs to answer the question.
