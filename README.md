# MEGA Loop for Claude Code

**Your users hit a bug in production. MEGA Loop already found it. Now fix it without leaving your terminal.**

MEGA Loop reads the traces your AI app writes in production. It works out what is broken and points at the exact file and line. This plugin brings that into Claude Code. Ask in plain words, get a draft pull request.

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

---

## Install

Once per machine, not per repository.

**1. Add the marketplace.**

```bash
claude plugin marketplace add https://github.com/mega-edo/mega-loop-skill.git
```

The repository is private. If this fails, open it in a browser while signed in to GitHub. A 404 there means your account does not have access yet.

**2. Install the plugin.**

```bash
claude plugin install mega-loop@mega-loop --config base_url=https://loop.megacode.ai
```

`base_url` picks which server you talk to. Use `https://loop.megacode.ai` for production, or `https://loop-beta.megacode.ai` if you are a beta tester.

Do not put a token on this line. Claude Code will say `api_token` is not set. That is fine — you set it later, through a masked prompt.

**3. Restart Claude Code.** A session that is already open will not see the plugin.

---

## Traces only — no account, nothing leaves your machine

Start here if your app has no tracing. These three verbs run on your machine. They never call MEGA Loop and never read your token, so you can use them before you have an account.

MEGA Loop can only find a bug in a trace it can read: **one clean trace per request**, in OpenInference format. Which verb you want depends on what you have today.

| You have | Verb | Touches your code |
|---|---|---|
| no tracing at all | `/mega-loop:trace-gen` | yes |
| traces, and a question about them | `/mega-loop:trace-analyze` | no — read only |
| traces that fail the contract | `/mega-loop:trace-fix` | yes |

Plain words work too: *"are my traces good enough?"*, *"make my traces pass"*.

**`/mega-loop:trace-gen`** — *"I emit nothing yet."* It reads your repository to decide what **one request** is, installs the kit for your stack, writes the spans, then runs your app and grades the traces that came out. A codebase with no traces cannot be graded, only guessed at. Kits ship for **Python** and **Node** — plain Node, Express, Koa, **NestJS** and **Next.js**, the last two handled specially because the framework opens the request span before your code runs. On another language it says so rather than inventing a kit nobody has run, and offers to write the spans by hand: that language's own OpenTelemetry SDK, carrying the same OpenInference attribute names MEGA Loop reads.

**`/mega-loop:trace-analyze`** — *"are my traces good enough?"* It grades them against the same contract MEGA Loop runs inside, and gives you the exact fix for each finding, ordered by how many traces each one clears. It also says whether a finding is mechanical, so `trace-fix` can apply it, or a design choice only you can make.

**`/mega-loop:trace-fix`** — *"make them pass."* It works the findings in the order that clears the most traces, and re-runs the validator until every trace reaches `entry_seatable`. That verdict means MEGA Loop can read it.

### What this needs

**Nothing, to start.** While `trace-gen` and `trace-fix` are still getting the instrumentation right, traces go to a local collector the skill starts and removes itself. One command: `uvx arize-phoenix serve`, or the same thing in Docker if you do not have `uv`. The attempts stay on your machine. **Nothing reaches your platform until you say so.**

**Your platform's keys, when you choose to grade it.** The local loop proves the spans are written right. It cannot prove the export works — the keys, the URL, and what your platform does to a span when it arrives. So the skill stops, shows you the local result, and asks before it reads your platform.

Set these in the shell you start `claude` from. Claude only sees the environment it was started with, so a variable you export later needs a restart.

| Backend | Export to it | Read it back |
|---|---|---|
| Langfuse | `LANGFUSE_BASE_URL` (or `LANGFUSE_HOST`, the older name), `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | yes |
| Phoenix | `PHOENIX_HOST`, plus `PHOENIX_API_KEY` on Phoenix Cloud | yes |
| LangSmith | — | yes, with `LANGSMITH_API_KEY` |
| Any OTel collector | `OTEL_EXPORTER_OTLP_ENDPOINT` | no — export to JSON and grade the file |

These are your tracing platform's keys. None of them is a MEGA Loop token, and none of them leaves your machine.

`OTEL_EXPORTER_OTLP_ENDPOINT` beats every row above. That is how the local loop works: the skill points it at the collector it started, and your platform keys in `.env` stay untouched. It also means a leftover value in your shell will quietly send traces somewhere else. Check that first when traces do not arrive.

**Your app needs the same keys when it runs**, in its own `.env`, compose file or Kubernetes secret. Setting them in your shell configures the reader, not the app that writes.

**`uv` and Python 3.11+.** The validator declares its own dependencies, so `uv run` provides them in a throwaway environment. Nothing is installed into your project. No `uv`? Run `pip install pydantic httpx` once, then use `python` instead of `uv run`.

---

When every trace passes, go to **Run the loop** below and let MEGA Loop find the real bugs.

---

## Run the loop — from a production bug to a pull request

This needs traces MEGA Loop can read. If your app has no tracing yet, or MEGA Loop shows you no bugs, do the section above first.

You also need a MEGA Loop account, a token, and `git`. To open pull requests from your machine, install `gh` (GitHub), `glab` (GitLab) or `bkt` (Bitbucket). If none is there, you still get a ready branch and a patch file.

### Set it up

**1. Create the project on the web.** Your dashboard is your `base_url`: [loop.megacode.ai](https://loop.megacode.ai) or [loop-beta.megacode.ai](https://loop-beta.megacode.ai). Connect a trace source there. This step needs provider keys and a live connection test, so it belongs in a browser. Do it once.

**2. Get a token.** In the same dashboard: **Account settings → Personal Access Tokens → Generate token**. It starts with `mlp_` and is shown **only once**, so copy it right away.

Production and beta are separate accounts with separate data. Take the token from the same place your `base_url` points at, or your projects will not show up.

**3. Set the token, then restart Claude Code.**

```
/plugin  →  mega-loop  →  configure  →  api_token
```

> ⚠️ **Never type the token in the shell or paste it in the chat.** The shell saves it in your history. The chat saves it in the transcript. The masked prompt puts it straight into your operating system's keychain.

**4. Check it worked.**

```
/mega-loop:status
```

This is your setup doctor. It tells you if the token works, which server it reached, who you are, and what projects you have. If a step went wrong, it says which one.

**5. Connect this repo to a project.**

```
/mega-loop:connect
```

It lists your projects by name and remembers your pick. You never type an id. The choice is saved in the repo, so later sessions in this folder pick it up. `/mega-loop:disconnect` clears it.

### Then just ask

You never type a project id or a bug id. The plugin works them out from your words.

| Say this | What happens |
|---|---|
| *"what's broken?"* | The bugs in your traces, worst first |
| *"why is the refund answer wrong?"* | The cause and the exact `file:line`, from a real trace |
| *"fix that one"* | Runs the fix and opens a **draft** PR |
| *"apply the review comments"* | Updates the same PR with your reviewer's feedback |
| *"switch project"* | Lists your projects and remembers your pick |
| *"what's mega-loop doing?"* | Your setup, your projects, and any fix running now |

### Or type a command

| Command | Does |
|---|---|
| `/mega-loop:status [job id]` | Setup check, connected project, fixes in flight |
| `/mega-loop:bugs` | List the open bugs |
| `/mega-loop:explain <bug>` | Cause and `file:line` for one bug |
| `/mega-loop:groups` | Bugs grouped the way a fix actually ships |
| `/mega-loop:fix <bug>` | Fix a bug and get a draft PR |
| `/mega-loop:refine` | Apply review feedback to the same PR |
| `/mega-loop:connect` | Pick the project this repo works on |
| `/mega-loop:projects` | List your projects (read only) |
| `/mega-loop:disconnect` | Unlink this repo from its project |

### How a fix gets made

The server decides who does the work. You cannot get this wrong.

**Repo connected to GitHub.** The MEGA Loop engine does it all on its own servers: clone, fix, test, open a **draft** PR. Your local files are not touched.

**No repo connected.** Your Claude Code session does the work, from a package the engine hands over. It makes a branch, makes the change, and then has to earn the word "verified":

| Check | What it proves |
|---|---|
| Replays every recorded failure | The real production inputs pass now |
| Writes a regression test | The bug cannot come back unnoticed |
| Undoes the fix and re-runs the test | The test really catches this bug |
| Checks every caller | Nothing downstream broke |
| Runs your full test suite | No new failures anywhere |

**The engine is the only judge.** Your session runs the code and reports what happened. The server decides pass or fail, with the same gate the dashboard and CI use. A session cannot mark its own work as good.

Every PR is a **draft**. Nothing is ever merged for you.

---

## Good to know

- **Open Claude Code in the repo you want to fix.** When your session does the fixing, it edits files in the current folder.
- **No bugs showing?** That is usually a trace problem, not a bug problem. Go grade your traces.
- **Tokens are web only.** You can hold up to 10 and revoke any of them from the dashboard. The plugin uses a token, but can never make or delete one.

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
