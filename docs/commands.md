# Commands and skills — full reference

There are two ways to drive the plugin, and they do the same work:

- **Slash commands** (`/mega-loop:bugs`) — exact, typed, good when you know what you want.
- **Plain words** ("what's broken?") — Claude Code picks the right skill on its own.

Skills are the ones written in plain words. Commands are shortcuts into them.

---

## `/mega-loop:status` — the setup doctor

Start here whenever something looks wrong. It reports three things:

1. **Setup and sign-in** — is `api_token` set and valid, which server it reached, which account you
   are signed in as. If setup is incomplete it stops here and walks you through fixing it.
2. **Connected project** — which project this repo is linked to, plus all your projects, each
   marked with how its fixes run (**engine** if a code repo is connected, **handoff** if not).
3. **In flight** — bug counts for the active project, and any fix currently running.

Give it a job id (`/mega-loop:status abc123`) to watch one running engine job instead.

---

## `trace-gen`, `trace-analyze` and `trace-fix` — make your traces usable first

Trace quality is the input to everything else MEGA Loop does. Before it can find a bug, your agent
has to emit **one clean trace per request** that the readiness contract accepts. These three run
that loop, and which one you want depends on what you have today:

| You have | Verb |
|---|---|
| no tracing at all | `trace-gen` |
| traces, and a question about them | `trace-analyze` |
| traces that fail the contract | `trace-fix` |

**trace-gen** — *"I emit nothing yet"* · `/mega-loop:trace-gen`
Edits your code. Reads the repository to find where a request begins and what happens inside one,
installs the kit for the stack, writes the spans — then **runs your app and grades the traces that
came out**, because a codebase with no traces cannot be graded, only guessed at.

The first step is the one that matters: deciding what *one request* is. The answer is whatever a
person would re-run when they say "this answer was wrong". Get it wrong and you get a tidy trace
of the wrong thing, which grades well and helps nobody.

Kits ship for **Python and Node**. On another language it says so rather than improvising a kit
nobody has run, and offers to write the spans against that language's own OpenTelemetry SDK — the
attribute names are the same strings either way.

**trace-analyze** — *"are my traces good enough for MEGA Loop?"* · `/mega-loop:trace-analyze`
Read only. Grades your traces — or your source, before any traces exist — against the readiness
contract MEGA Loop runs internally, plus two checks of its own that can never fail a trace, and
answers four questions per trace:

1. **Can the request be re-run at all?** — the verdict (`entry_missing` → `detection_gap` →
   `degraded` → `entry_seatable`).
2. **Will failures be seen?** — error status and step input/output.
3. **Where are spans malformed?** — fragmentation, missing span kinds, and the rest.
4. **Is the trace worth it to MEGA Loop?** — a separate, never-fatal line: a trace can be perfectly
   readable and still hold nothing to detect (all CHAIN, mostly mechanical noise, no token counts).

Every finding comes with the exact fix, and the summary orders them by how many traces each clears.
It never edits your code.

**trace-fix** — *"make my traces pass"* · `/mega-loop:trace-fix`
Edits your instrumentation: applies the kit, works the findings top-down, and re-runs the validator
until the verdicts reach `entry_seatable`, reporting the before/after. Runs the validator with
`uv run`, so its dependencies never touch your project. When the traces are green, connect the
project and let MEGA Loop find the real bugs.

---

## `connect` — pick the project this repo works on

**Say:** "connect to mega-loop", "which project", "switch project"
**Or type:** `/mega-loop:connect`

Lists your projects **by name** and asks which one. You never type an id.

The choice is saved in `.mega/companion/project.json` inside your repo, so every later session in
the same folder picks it up automatically — you connect **once**, not every time. Clear it with
`/mega-loop:disconnect`.

If you have exactly one project, it is chosen for you with no question asked.

> Creating a project and connecting a trace source (Langfuse, Phoenix, LangSmith) is done on the
> web dashboard. It needs provider secret keys and a live connection test, which belong in a
> browser. If a project shows no bugs, it usually has no trace source yet.

---

## `diagnose` — read what MEGA Loop found

Read only. It reports; it never edits your code.

**bugs** — *"what's broken?"* · `/mega-loop:bugs`
Lists the open bugs by title, worst severity first, with how many traces hit each one.

**explain** — *"why is the refund answer wrong?"* · `/mega-loop:explain <bug>`
The cause and the exact `file:line`, taken from a real trace. It can also show you the failing
input that reproduces it.

If a trace never pinned down a location, it says so. It will not invent a `file:line`.

**groups** — `/mega-loop:groups`
Some bugs share a root cause and only make sense fixed together. This shows the bugs grouped the
way a fix actually ships — one coordinated change per group. It is also the answer to "why did
asking for one bug give me three?".

---

## `fix` — fix a bug

**Say:** "fix the refund bug", "autofix it"

You name the bug in words. The plugin matches your words to a bug title, and if two bugs could
match it shows both and asks — it does not guess.

Then **the server decides who does the work**:

### Your project is connected to a GitHub repo → the engine fixes it

The engine clones your repo on its own servers, makes the fix, verifies it, and opens a **draft**
PR itself. Your local files are untouched. You get:

- a job id, so you can ask "how is it going?" at any time
- the engine's PASS or FAIL verdict when it finishes
- a PR link — pull it with `git fetch && git checkout <branch>`

If the job ends without a PR, ask to see what it produced. The plugin can show the diff it wrote,
the checks it ran, and why each rejected attempt was rejected — so you can continue from its work
instead of starting from zero.

### No repo is connected → your session fixes it

The engine hands over a fix package: which bugs, in what order, and the real failing inputs from
production. Your Claude Code session then does the work in your working folder.

Before it may say **verified**, it has to pass five checks:

| # | Check | What it proves |
|---|---|---|
| 1 | Replay **every** recorded failing input | The real production cases pass now |
| 2 | Write a lasting regression test | The bug class cannot come back unnoticed |
| 3 | Reverse the fix, re-run that test | The test really catches this bug — a test that cannot fail proves nothing |
| 4 | Check every caller of the changed code | Nothing downstream broke |
| 5 | Run the **full** test suite | No new failures anywhere |

Everything is run for real. Faking an external call to force a green result is not allowed, and if
a check genuinely cannot be run, it is named and skipped rather than quietly claimed.

Then it opens a **draft** PR — `gh` for GitHub, `glab` for GitLab, and on Bitbucket the REST API
when an app password is configured. Without one, Bitbucket gets you the pushed branch and the
"Create pull request" URL from the push output, and you open it yourself. Either way it reports the
evidence back to MEGA Loop.

**No PR possible?** The work still counts. You get the branch, a patch file, and instructions,
and the dashboard records it honestly as "Verified — PR blocked".

### Safety rails

- The **engine is the only judge.** Your session runs code and reports; MEGA Loop decides PASS or
  FAIL using the same gate as the dashboard and CI.
- While a fix is open, the session **cannot** declare itself done. A background check blocks it
  until the engine's verdict comes back.
- It fixes **only** what the bug names. No unrelated "while I'm here" changes.
- Every PR is a **draft**. Nothing is merged for you.
- Before branching it checks for unrelated uncommitted changes, so your work in progress never
  gets swept into the fix.

---

## `refine` — apply review feedback to an open PR

**Say:** "apply the review comments", "refine that PR"

A reviewer left comments on a fix PR. This is a **revision**, not a new fix:

1. Checks out the same branch as the PR.
2. Reads the unresolved review comments (GitHub, GitLab, or Bitbucket). If it cannot read them
   automatically, it asks you to paste them.
3. Makes the **smallest** change that answers them — nothing else.
4. Re-verifies, pushes to the **same** branch, and reports the turn.

The open PR updates in place. It never opens a second PR.

---

## `/mega-loop:projects` and `/mega-loop:disconnect`

- **`projects`** — lists your projects by name. Read only; it does not change the active one.
- **`disconnect`** — removes the saved project link for this repo, so new sessions stop
  auto-connecting. Your token is untouched.

---

## What runs in the background

Two small helpers, both silent unless they have something to do:

**restore-connection** — at session start, if this repo has a saved project, it tells the session
which project to use. This is why you connect once and never again.

**gate-on-stop** — while a fix is open, it stops the session from declaring "done" until MEGA Loop
returns its verdict. It never scores anything itself; it only makes sure the engine is asked. A
marker left over from an abandoned fix is ignored after a day, so it can never nag you forever.
