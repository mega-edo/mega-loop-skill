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

## Fixing

### There are no bugs listed

**Cause.** The project has no trace source connected yet, or it has never been analysed.

**Fix.** Connect a trace source on the web dashboard and run the analysis once. After that the
terminal sees everything.

### Claude Code fixed the bug but will not say it is done

**This is on purpose.** While a fix is open, the session cannot declare it finished until MEGA Loop
returns a verdict. Your session runs the code and reports the evidence; the decision stays with the
engine, so a session can never approve its own work.

**Fix.** Let the check finish. If the verdict is FAIL, read the reason it gives and address that.

### The local fix did not open a pull request

**Cause.** On the path where your session does the fixing, the PR is opened from your machine, so it
needs `git` plus the CLI for your host: `gh` (GitHub), `glab` (GitLab), or a Bitbucket app password.

**Fix.** Install and sign in to the missing CLI, then retry. When it cannot open the PR the plugin
stops honestly and leaves you a branch and a patch file, so no work is lost — you can open the PR
yourself.

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
