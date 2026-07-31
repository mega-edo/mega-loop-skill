# MEGA Loop for Claude Code

**Your users hit a bug in production. MEGA Loop already found it. Now fix it without leaving your terminal.**

MEGA Loop watches the traces your AI app writes in production, works out what is actually broken,
and points at the exact file and line. This plugin brings all of that into Claude Code — ask in
plain words, get a draft pull request.

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

No dashboard. No bug ids to copy. No local setup beyond the install below.

---

## Install — 4 steps, once per machine

**1. Add the marketplace.** This tells Claude Code where the plugin lives.

```bash
claude plugin marketplace add https://github.com/mega-edo/mega-loop-skill.git
```

**2. Get your token.** In the MEGA Loop dashboard, open **Account settings → Personal Access
Tokens → Generate token**. Pick a name and an expiry. The token starts with `mlp_` and is shown
**only once**, so copy it right away.

**3. Install the plugin.** Run this in the repository you want to work on:

```bash
claude plugin install mega-loop@mega-loop --config base_url=https://loop.megacode.ai
```

`base_url` picks which MEGA Loop server you talk to. Use `https://loop.megacode.ai` for
production, or `https://loop-beta.megacode.ai` if you are a beta tester. There is **no token on
this line** — that comes next, in a masked prompt.

**4. Add the token, then restart Claude Code.**

```
/plugin  →  mega-loop  →  configure  →  api_token
```

> ⚠️ **Never put the token on the command line** (`--config api_token=…`) **or paste it into the
> chat.** A token typed in the shell is saved in your shell history and is visible to anyone who
> can list running processes. A token pasted in the chat is written into the session transcript.
> The masked prompt puts it straight into your operating system's keychain, so it never touches a
> file, your shell, or the conversation.

**Check it worked:**

```
/mega-loop:status
```

This is your setup doctor. It tells you whether the token is set and valid, which server it
reached, who you are signed in as, and which projects you have. If a step went wrong, this is the
command that says which one.

---

## Use it — just say what you want

The plugin understands plain language. You never type a project id or a bug id; it works them out
from your words.

| Say this | What happens |
|---|---|
| *"connect to mega-loop"* | Lists your projects and remembers the one you pick — for this repo, forever. |
| *"what's broken?"* | The bugs found in your traces, worst first, by title. |
| *"why is the refund answer wrong?"* | The cause plus the exact `file:line`, taken from a real trace. |
| *"fix that one"* | Runs the fix and gets you a **draft** PR. |
| *"apply the review comments"* | Takes your reviewer's feedback and updates the same PR. |
| *"what's mega-loop doing?"* | Your setup, your projects, and any fix currently running. |

Prefer typing commands? Every one of them has a slash command too:

| Command | Does |
|---|---|
| `/mega-loop:status` | Setup check, connected project, fixes in flight |
| `/mega-loop:connect` | Pick the project this repo works on |
| `/mega-loop:projects` | List your projects (read only) |
| `/mega-loop:bugs` | List the open bugs |
| `/mega-loop:explain <bug>` | Cause + `file:line` for one bug |
| `/mega-loop:groups` | Bugs grouped the way a fix actually ships |
| `/mega-loop:disconnect` | Unlink this repo from its project |

You connect a repo to a project **once**. Every later session picks it up on its own.

---

## What happens when you say "fix it"

The server decides who does the work. You do not choose, and you cannot get it wrong.

**If your project is connected to a GitHub repo** — the MEGA Loop engine does everything on its
own servers: clones, fixes, tests, and opens a **draft** PR. Your local files are not touched. You
get a job id to watch and a PR link when it lands.

**If no repo is connected** — your Claude Code session does the work, using a fix package the
engine hands over. It creates a branch, makes the change, and then has to *earn* the word
"verified":

| Check | What it proves |
|---|---|
| Replays every recorded failure | The real production inputs pass now |
| Writes a lasting regression test | The bug cannot come back unnoticed |
| Reverses the fix and re-runs the test | The test really catches this bug, and the fix is what closes it |
| Checks every caller | Nothing downstream broke |
| Runs your full test suite | No new failures anywhere |

Then it opens the draft PR — and reports the evidence back to MEGA Loop.

**The engine is the only judge.** Claude Code runs the code and reports what happened; the server
decides PASS or FAIL, using the exact same gate as the dashboard and CI. A session cannot mark its
own work as good. If something could not be checked honestly, it says so instead of showing you a
green wall.

Every PR is a **draft**, and nothing is ever merged for you.

---

## Good to know

- **Open Claude Code in the repo you want to fix**, not somewhere else. When your session does the
  fixing, it edits files in the current folder.
- **Creating a project and connecting a trace source is done on the web.** It needs provider secret
  keys and a live connection test, which belong in a browser. Do it once, then live here.
- **Tokens are web only.** You can hold up to 10 and revoke any of them from the dashboard. The
  plugin uses a token but can never create or delete one.
- **You need `git`.** For opening PRs you also need the `gh` CLI (GitHub), `glab` (GitLab), or an
  app password (Bitbucket). Missing one is not fatal — you get a ready branch and a patch file,
  plus instructions, instead of silence.

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
