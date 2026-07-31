---
name: fix
description: >
  Fix a bug that mega-loop diagnosed from production traces — from inside this session.
  Use when the user asks to fix/autofix a mega-loop bug, mentions a bug id or bug title
  from the mega-loop dashboard, or says "fix" / "autofix". One verb; the SERVER decides who
  fixes: project bound to a GitHub repo → the engine fixes and opens a draft PR;
  unbound → THIS session pulls the handoff package, fixes locally, verifies, reports
  back, and opens the PR (or ends honestly at a verified branch when it can't).
---

# mega-loop fix — one verb, routed server-side

The fix orchestrator over the companion MCP. It needs the **active project** (pick it with
**connect**); pass its `id` as `project` to every verb.

## Resolve the bug first (the user gives a description, not ids)

The user names a bug by **words** ("fix the answer bug"), not an id. Resolve it — never ask them
for a project id:

1. **`list_projects`** → the user's projects. Exactly one → use it. Several and they didn't name
   one → look across them (step 2) or ask which.
2. **`list_bugs(project=<active>)`** → match the user's words to a bug's **title**; take its
   `bug_id`. If the match is ambiguous, show the candidates and ask — never guess.
3. **`autofix(project=<active>, bug_id=<that bug>)`** (scope defaults to `bug`; use
   `group_id` / `group_ids` / `scope="all"` for a group or a whole batch).

## If any verb returns `unauthorized`

The **PAT isn't set** (or is invalid/expired/revoked). Tell the user to run **`/mega-loop:status`**
(the setup doctor — it says whether the token is set and how to set it via `/plugin`), then retry the
original call. **Never ask for an email + password**; the terminal authenticates only with a PAT
(design 56 §6 / design 57). A **`forbidden`** means that project isn't theirs → re-run
`list_projects` and re-pick.

## Read the reply, then route

`autofix` returns `{project, scope, results: [...]}`. Each result carries `mode`. **Never decide the
mode yourself** — the server owns the routing (design 37). Handle the non-result replies first:

- **`error: "nothing_to_fix"`** → no bug/group matched; re-run `list_bugs` and re-resolve.
- **`error: "no_llm_connection"` / `"unsupported_analyst_model"` / `"unresolved_tier_models"`** →
  the repo is bound so the engine fixes it, but the user's LLM connection is missing/unusable. Tell
  them to fix it on the dashboard (Account → LLM connections), then retry.
- **`error: "missing_provider_keys"`** (template ⑤) → the engine's re-run needs a provider key this
  project hasn't stored. Show `requirements[].envVars` (setting ANY one in a row satisfies it) and
  offer: add it in the dashboard (Project → Settings → Env vars) and retry, **or** fix locally in
  this session instead.
- **`error: "already_running"` / `"group_only"` / `"overlapping_run"`** → surface the `message`
  verbatim (a fix is in flight, or the bug ships as part of a group). Offer `restart=true` only for
  `already_running` when the user explicitly wants to re-run.

Otherwise take `results[0]` and follow its `mode`.

## mode: "autodebug" (project is bound to a GitHub repo — the ENGINE fixes)

You are the mouth, not the hands. The engine clones the repo server-side, fixes on a new branch,
verifies, and opens the draft PR itself. The result carries a `job_id`.

1. Tell the user what started (template ①): bug title, "engine is fixing it", the `job_id`.
2. Poll **`status(project=<active>, job_id=<from the result>)`** when the user asks (or after a
   while) → the job's live status/progress. Report honestly; the engine opens the draft PR itself
   when it finishes (the job view carries the PR URL). The dashboard shows the same job.
3. **The engine already gated it.** When the job finishes, call **`gate(project=<active>,
   bug_id=<the bug>)`** → the engine's `PASS` / `FAIL` verdict (its own counterfactual+regression
   check). Report the verdict; never re-judge it yourself.
4. Remind them **local files did not change** — the fix is a server-side branch/PR; once the PR
   exists they pull it with `git fetch && git checkout <branch>`.
5. **The job ended with no PR (`unverified`), or the gate said FAIL — do NOT stop there.** Call
   **`get_job_artifacts(project=<active>, job_id=<the job>)`** (add `bug_id` to scope to one member
   of a group) → per bug: the unified `diff` the engine wrote, its `counterfactual` (expected vs
   observed error the gate judged), the `regression` output, and each rejected attempt's reasoning.
   Show the user that work and offer to continue from it **locally in this session** rather than
   redoing the fix from zero. Read-only — it never overrides the gate, and the engine still judges
   whatever you produce.

`status(project)` with no `job_id` is the whole-project glance — bug counts + every engine job and
handoff in flight — for "what's mega-loop doing right now?".

## mode: "handoff" (no repo bound — THIS SESSION fixes)

Pull the package and do the whole loop yourself. The result carries a `handoff_id`.

1. **`get_handoff(project=<active>, handoff_id=<from the result>)`** → bugs, fix order, and
   `instructions`. FOLLOW the instructions — they carry the protocol. The essentials:
   - **Mark the fix in-progress** so the gate-on-stop reflex knows not to let you stop prematurely:
     write `.mega/companion/active-fix.json` = `{"project":"<active>","bug_id":"<bug>",
     "handoff_id":"<id>","created_at":"<ISO-8601 UTC now>"}` (create `.mega/companion/` if needed).
     The `created_at` lets the reflex ignore a stale marker from an abandoned fix. Delete the marker
     only after the engine gate says PASS (step 4).
   - **Keep the marker dir out of the fix diff.** Add `.mega/` to `.gitignore` (append the line if
     it isn't there — same line **connect** writes, so one entry covers both markers) BEFORE you
     stage anything: the in-progress marker must never land in the PR, and on the no-VCS ladder
     (step 5) `git add -A` would otherwise commit it.
   - **Clean tree first.** Before branching, check `git status --porcelain`. If there are unrelated
     uncommitted changes, do NOT sweep them into the fix — ask the user to stash/commit them (or
     `git stash push -u` yourself and restore after), so the fix diff contains ONLY your change.
   - **Anchor first, edit never before.** The file/symbol hints are HYPOTHESES from traces —
     locate them in the working tree; if they don't resolve, ASK the user for the project root;
     if still nothing, `report_status(status="failed")` honestly.
   - **Branch first** (after the clean-tree check): `git checkout -b autofix/<handoff_id>`.
2. **Get the cases, then fix — and verify with the five-layer protocol.** Call
   **`get_cases(project=<active>, bug_id=<bug>)`** → `failing` traces (fetch each input with
   `get_trace`) + a `passing` golden sample. The engine hands you the **cases + instructions +
   context**; YOU run everything for real against the local code. An isolated "it no longer throws"
   is the *weakest* possible check — a `verified=true` is earned only when the layers below pass (or
   you honestly report the ones that couldn't run and why).

   **Run everything for REAL — never stub, mock, or fake an external call to force a pass.** Feeding
   a function a recorded value to reproduce a bug is fine (that IS the recorded input); replacing an
   LLM/tool/network call with a canned answer to fabricate a green run is NOT — it proves nothing.
   If a layer can't be run honestly, skip it and say so.

   - **L1 · Reproduce EVERY recorded failing input (not a sample).** For each `failing` trace,
     `get_trace(trace_id)` → take the recorded input to the buggy symbol and confirm the fixed code
     now passes it. If `failing_total` exceeds the returned list, you only saw a sample — say so.
   - **L2 · Add a DURABLE regression test that captures the bug CLASS.** Don't stop at the recorded
     inputs — write a parametrized/property test over the failure class + derived edge variants
     (empty, whitespace, alternate delimiters, boundary sizes). Put it in the repo's test tree so it
     **ships in the diff** — a fix without a test that would re-catch the bug is incomplete.
   - **L3 · Mutation proof (causality) — this is what makes a local verdict un-fakeable.** Prove the
     new test really captures the bug and the fix is what closes it:
     1. Reverse the fix but KEEP the test: `git stash push -- <the source files you edited>`
        (leaves the new test in place), or apply the fix diff in reverse.
     2. Run the new test → it **MUST FAIL** on the pre-fix code. If it passes, the test is vacuous
        — rewrite it until it fails without the fix.
     3. Restore the fix (`git stash pop`) → run again → **MUST PASS**.
     Record the outcome ("fails without fix / passes with fix") — a test that can't fail proves
     nothing.
   - **L4 · Caller + contract check.** grep every caller of the changed symbol and run their tests.
     If the fix changed a signature or return type, treat EVERY caller as at-risk and verify each.
     If the pipeline is cheaply runnable end-to-end **for real** (deterministic, or you have the
     keys locally), do a smoke run too — but only for real; **never stub the LLM to fake it**.
   - **L5 · Full regression.** Run the **full** test suite (not the sample) + re-run all `passing`
     golden. List only REAL breakage in `regressions` (a test *supposed* to change now the bug is
     fixed is an exclusion — note it).

   If any layer fails: refine in place — smallest adjustment, re-run the layers; never re-roll an
   unchanged fix; after ~3 meaningful adjustments, stop and `report_status(status="failed")` with
   exactly which layer failed.
3. **Two-call finish** — report, then open the draft PR/MR:
   - `report_status(project=<active>, handoff_id=..., status="verified", verified=true,
     counterfactual=..., regression=..., diff=<git diff>, branch=..., tests_passed=...,
     tests_failed=..., cwd=<abs repo path>)` → the reply has `pr_title`/`pr_body` and `ok=false` —
     you are NOT done yet. **Pack the five-layer evidence into the fields** so the verdict is
     auditable, not a bare claim:
     - `counterfactual` — how many recorded failing inputs flipped (L1) + the caller/contract +
       any real end-to-end smoke result (L4, or "skipped: not runnable locally").
     - `regression` — the **full-suite** result (L5) + the **mutation proof** (L3: "new test fails
       without the fix, passes with it").
     - `diff` — MUST include the new regression test (L2); `tests_passed`/`tests_failed` = the full
       suite; put any layer you couldn't run (and why) in `notes` — honesty over a green wall.
   - **Detect the git host** from `git remote get-url origin` (github.com / gitlab.com|self-hosted /
     bitbucket.org), then open a **DRAFT** PR/MR with the `pr_title`/`pr_body` **VERBATIM** (no
     footers, no attribution):
     - **GitHub** (`gh` available): `gh pr create --draft --title "<pr_title>" --body-file <file>
       --label auto-fix --label needs-review`
     - **GitLab** (`glab` available): `glab mr create --draft --title "<pr_title>"
       --description-file <file> --label auto-fix,needs-review --yes`
     - **Bitbucket** (no `gh`/`glab` CLI): `git push -u origin <branch>` — Bitbucket prints a
       **"Create pull request"** URL in the push output; capture it. If a Bitbucket app-password +
       REST is configured, create the PR via `POST /2.0/repositories/{ws}/{repo}/pullrequests`
       (`"draft": true`); otherwise report that create-PR URL so the user opens it.
   - Then get the **PR/MR url** + the **commit list** (OLDEST→NEWEST) and call
     `report_status(..., pr_url=..., commits=[...])` → `ok=true`. Commit list per host:
     `gh pr view <n> --json commits` · `glab mr view <n>` · or host-agnostic
     `git log <base>..HEAD --reverse --pretty='%H %s'`.
4. **Gate + clear the marker** — call **`gate(project=<active>, bug_id=<bug>)`** → the engine's
   verdict on what you reported. On **PASS**, delete `.mega/companion/active-fix.json` (you may now
   stop). On **FAIL/PENDING**, do NOT declare done — address it and re-verify. The gate-on-stop
   reflex enforces this: it blocks "done" while the marker is present.
5. **The PR ladder** (when no PR/MR can be opened — the fix still counts):
   - git repo but **no remote, or no matching host CLI** (`gh`/`glab`, and Bitbucket app-password
     unset): push the branch if a remote exists (`git push -u origin <branch>` — GitLab/Bitbucket
     print a create-MR/PR URL you can report), or offer to add a remote / install the CLI. If the
     user declines → `report_status(..., pr_blocked_reason="...")` → honest terminal (dashboard
     shows "Verified — PR blocked"). Leave the branch + a patch file (`git format-patch`) and tell
     the user how to review/merge.
   - no git at all: offer `git init && git add -A && git commit` FIRST (2 seconds, full safety net).
     If declined: back up the files you will touch to `.mega/backup/<handoff_id>/`, fix in place,
     hand-build the unified diff, report it with `pr_blocked_reason="no VCS"` — and tell the user
     how to revert.

## Response contract (every reply)

Outcome + evidence + the artifact's address + a copy-pasteable next step:

- ① start: bug, mode in plain words, job/handoff id, where to watch progress.
- ② engine running: "engine is fixing it", job id, "watch the dashboard for the draft PR",
  "local files unchanged" + the checkout cmd for when the PR lands.
- ③ local done with PR: PR URL · branch · evidence · "reported back to the dashboard".
- ④ local done without PR: branch · diff stat · patch path · "dashboard shows
  Verified (PR blocked)" · merge/push next step.
- ⑤ failure / blocked: the honest reason + a way out (never a silent stop). When an ENGINE job is
  what failed, the way out is `get_job_artifacts` — show its diff + the gate's counterfactual and
  offer to continue locally.

## Guardrails

- Diagnostic honesty: fix ONLY what the handoff names. Do not "helpfully" fix or create
  unrelated things.
- Never fabricate verification — `verified=true` only after a real reproduce-and-pass.
- **A test that can't fail proves nothing.** The mutation step (L3) is mandatory: if the new test
  passes on the un-fixed code, it doesn't capture the bug — rewrite it until it fails without the
  fix. Ship the test in the diff so the guard is permanent.
- **Run for real — never stub to pass.** Reproducing a bug by feeding a function its recorded input
  is fine; replacing an LLM/tool/network call with a canned answer to force a green run is not — it
  proves nothing. If a check can't be run honestly, skip it and say so.
- **Don't fix the symptom, fix the cause.** A fix that only special-cases the recorded input
  (`if x == "<that exact value>"`) passes L1 but fails the spirit — L2's class-level test and L3's
  mutation proof exist to catch exactly that. Address the root cause the handoff named.
- **Report which layers ran.** Never imply a mutation, caller, or full-suite check you skipped —
  name the skipped layer and why (no test runner, not runnable locally, etc.). A partial-but-honest
  verdict beats a green wall.
- The server is the ONLY judge: it demotes unproven claims and answers `ok=false` until the PR debt
  is settled with `pr_url` or `pr_blocked_reason` — don't fight it, finish it.
