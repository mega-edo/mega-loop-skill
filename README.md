# MEGA Loop for Claude Code

**Your users hit a bug in production. MEGA Loop already found it. Now fix it without leaving your terminal.**

MEGA Loop watches the traces your AI app writes in production, works out what is actually broken, and points at the exact file and line. This plugin brings all of that into Claude Code — ask in plain words, get a draft pull request.

```
you: what's broken?

  1. Refund answers cite the wrong policy page      high    41 traces
  2. Empty reply when the question has no verb      medium  12 traces
  3. Timeout on multi-step tool calls               low      3 traces

you: fix the refund one

  → retriever.py:88 — the policy filter drops the date range
  → branch autofix/hf_9c21 · 41/41 recorded failures now pass
  → draft PR #212 opened
```

No dashboard. No bug ids to copy.

The plugin does two jobs, and only the second one needs an account:

| Part | What it does | Needs |
|---|---|---|
| **1 — Traces** | Get your app emitting traces MEGA Loop can actually read | The plugin, and somewhere for traces to go. No MEGA Loop account, no project — its verbs never read your token. |
| **2 — Bugs** | See what MEGA Loop found in those traces, then fix it | A MEGA Loop account and a personal access token |

Part 1 never calls MEGA Loop — it talks only to your own tracing backend. Start there if your app has no tracing, or if MEGA Loop is showing you no bugs — trace quality is the input to everything else.

---

## Install — once per machine

**1. Add the marketplace.**

```bash
claude plugin marketplace add https://github.com/mega-edo/mega-loop-skill.git
```

The repository is private. If this fails, check that you can open it in a browser while signed in to GitHub — a 404 there means your account has not been granted access yet.

**2. Install the plugin.**

```bash
claude plugin install mega-loop@mega-loop --config base_url=https://loop.megacode.ai
```

`base_url` picks which MEGA Loop server you talk to: `https://loop.megacode.ai` for production, `https://loop-beta.megacode.ai` if you are a beta tester. There is **no token on this line**: it goes in through a masked prompt in Part 2, never the shell.

`api_token` is required plugin config, so Claude Code will report it as not yet set. Part 1 still works — its three verbs run locally and never read the token — and Part 2 sets it below.

**3. Restart Claude Code.** The plugin's server is loaded at startup, so a session that was already open will not see it.

That is the whole install, and it is not per repository. The once-per-repository step is `/mega-loop:connect`, in Part 2.

---

## Part 1 — Make your traces readable

*No MEGA Loop account, no project, no PR. These three verbs run locally and never read your token.*

MEGA Loop can only find a bug in a trace it can read: **one clean trace per request**, OpenInference-compliant. Three verbs get you there, and which one you want depends on what you have today.

| You have | Verb | Touches your code |
|---|---|---|
| no tracing at all | `/mega-loop:trace-gen` | yes |
| traces, and a question about them | `/mega-loop:trace-analyze` | no — read only |
| traces that fail the contract | `/mega-loop:trace-fix` | yes |

Plain words work here too — *"are my traces good enough?"*, *"make my traces pass"* — and reach the same three skills.

**`/mega-loop:trace-gen`** — *"I emit nothing yet."* It reads your repository to decide what *one request* is, installs the kit for your stack, writes the spans, then runs your app and grades the traces that came out — because a codebase with no traces cannot be graded, only guessed at. Kits ship for **Python and Node**; on another language it says so and writes the spans against that language's own OpenTelemetry SDK instead of improvising a kit nobody has run.

**`/mega-loop:trace-analyze`** — *"are my traces good enough?"* It grades them against the readiness contract MEGA Loop runs internally and hands back the exact fix for every finding, ordered by how many traces each one clears. Three of its fourteen checks are reported but never fatal: they ask whether a trace MEGA Loop *can* read actually holds anything worth detecting.

**`/mega-loop:trace-fix`** — *"make them pass."* It applies the kit, works the findings in the order that clears the most traces, and re-runs the validator until every trace reaches `entry_seatable` — the verdict that means MEGA Loop can read it — reporting before and after.

### What Part 1 needs

**A tracing backend.** Spans have to land somewhere before anything can grade them, so `trace-gen` wires the exporter at one of these and `trace-analyze` reads back from it. Set it up first — a Langfuse or Phoenix account, or a collector you already run — because a codebase with no traces cannot be graded, only guessed at.

| Backend | Export to it | Read it back with `--platform` |
|---|---|---|
| Langfuse | `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | yes |
| Phoenix | `PHOENIX_HOST` (plus `PHOENIX_API_KEY` on Phoenix Cloud; a self-hosted instance is usually open) | yes |
| LangSmith | — | yes, with `LANGSMITH_API_KEY` |
| Any OTel collector | `OTEL_EXPORTER_OTLP_ENDPOINT` (wins over the two above) | no — export the spans to JSON and grade the file |

These are your tracing platform's own credentials. None of them is a MEGA Loop token, and none of them leaves your machine for MEGA Loop.

**`uv` and Python 3.11+.** The validator declares its dependencies inline, so `uv run` provisions them in a throwaway environment and nothing is installed into your project. No `uv`? Run `pip install pydantic httpx` once, then use `python` in place of `uv run`.

**Nothing at all**, if you are only grading source. That path needs no backend and no credentials, but it parses **Python only** — on a repository that is mostly another language it says it could not read it rather than reporting a clean board, because "nothing found" and "nothing read" look identical and mean opposite things.

When every trace reaches `entry_seatable`, go to Part 2 and let MEGA Loop find the real bugs.

---

## Part 2 — Find and fix the bugs

*Needs a MEGA Loop account and a token, plus `git` — and, to open PRs from your machine, the `gh` CLI (GitHub), `glab` (GitLab), or a Bitbucket app password. Missing one is not fatal: you get a ready branch and a patch file, plus instructions, instead of silence.*

**1. Create the project and connect a trace source, on the web.** The dashboard is your `base_url` — [loop.megacode.ai](https://loop.megacode.ai) for production, [loop-beta.megacode.ai](https://loop-beta.megacode.ai) for beta. This step needs provider secret keys and a live connection test, which belong in a browser; do it once, then live here.

**2. Generate a token.** In that same dashboard, open **Account settings → Personal Access Tokens → Generate token**. It starts with `mlp_`, expires in 90 days by default, and is shown **only once**, so copy it right away.

Production and beta are separate accounts holding separate data, so the token has to come from the environment your `base_url` points at, or your projects will not appear.

**3. Set the token, then restart Claude Code.**

```
/plugin  →  mega-loop  →  configure  →  api_token
```

> ⚠️ **Never put the token on the command line** (`--config api_token=…`) **or paste it into the chat.** A token typed in the shell is saved in your shell history and is visible to anyone who can list running processes. A token pasted in the chat is written into the session transcript. The masked prompt puts it straight into your operating system's keychain, so it never touches a file, your shell, or the conversation.

**4. Check it worked.**

```
/mega-loop:status
```

This is your setup doctor. It tells you whether the token is set and valid, which server it reached, who you are signed in as, and which projects you have — and if a step went wrong, it says which one.

**5. Connect this repo to a project.**

```
/mega-loop:connect
```

It lists your projects **by name** and remembers the one you pick — you never type an id, and with exactly one project it is chosen for you. The choice is saved as `.mega/companion/project.json` inside the repo, so every later session in this folder picks it up on its own; `/mega-loop:disconnect` clears it.

### Then say what you want

The plugin understands plain language. You never type a project id or a bug id; it works them out from your words.

| Say this | What happens |
|---|---|
| *"what's broken?"* | The bugs found in your traces, worst first, by title. |
| *"why is the refund answer wrong?"* | The cause plus the exact `file:line`, taken from a real trace. |
| *"fix that one"* | Runs the fix and gets you a **draft** PR. |
| *"apply the review comments"* | Takes your reviewer's feedback and updates the same PR. |
| *"switch project"* | Lists your projects and remembers the one you pick. |
| *"what's mega-loop doing?"* | Your setup, your projects, and any fix currently running. |

### Or type the command

| Command | Does |
|---|---|
| `/mega-loop:status [job id]` | Setup check, connected project, fixes in flight |
| `/mega-loop:bugs` | List the open bugs |
| `/mega-loop:explain <bug>` | Cause + `file:line` for one bug |
| `/mega-loop:groups` | Bugs grouped the way a fix actually ships |
| `/mega-loop:fix <bug>` | Fix a bug and get a draft PR |
| `/mega-loop:refine` | Apply review feedback to the same PR |
| `/mega-loop:connect` | Pick the project this repo works on |
| `/mega-loop:projects` | List your projects (read only) |
| `/mega-loop:disconnect` | Unlink this repo from its project |

---

## What happens when you say "fix it"

The server decides who does the work. You do not choose, and you cannot get it wrong.

**If your project is connected to a GitHub repo** — the MEGA Loop engine does everything on its own servers: clones, fixes, tests, and opens a **draft** PR. Your local files are not touched. You get a job id to watch and a PR link when it lands.

**If no repo is connected** — your Claude Code session does the work, using a fix package the engine hands over. It creates a branch, makes the change, and then has to *earn* the word "verified":

| Check | What it proves |
|---|---|
| Replays every recorded failure | The real production inputs pass now |
| Writes a lasting regression test | The bug cannot come back unnoticed |
| Reverses the fix and re-runs the test | The test really catches this bug, and the fix is what closes it |
| Checks every caller | Nothing downstream broke |
| Runs your full test suite | No new failures anywhere |

Then it opens the draft PR — and reports the evidence back to MEGA Loop.

**The engine is the only judge.** Claude Code runs the code and reports what happened; the server decides PASS or FAIL, using the exact same gate as the dashboard and CI. A session cannot mark its own work as good. If something could not be checked honestly, it says so instead of showing you a green wall.

Every PR is a **draft**, and nothing is ever merged for you.

---

## Good to know

- **Open Claude Code in the repo you want to fix**, not somewhere else. When your session does the fixing, it edits files in the current folder.
- **No bugs showing, or traces MEGA Loop ignores?** That is a Part 1 problem, not a Part 2 one. Go back and grade your traces.
- **Tokens are web only.** You can hold up to 10 and revoke any of them from the dashboard. The plugin uses a token but can never create or delete one.

## Update or remove

```bash
claude plugin update mega-loop@mega-loop
claude plugin uninstall mega-loop@mega-loop
claude plugin marketplace remove mega-loop
```

## More

- [docs/commands.md](docs/commands.md) — every command and skill, in detail
- [docs/troubleshooting.md](docs/troubleshooting.md) — when something does not work
- [plugin/mega-loop/](plugin/mega-loop/) — what is inside the plugin
