---
name: refine
description: >
  Apply maintainer review feedback to an open auto-fix PR/MR — a REVISION, not a fresh fix. Use when
  the user says "refine", "apply the review comments", "address the PR feedback", or after a
  maintainer reviews a mega-loop fix PR. Reads the PR's review comments (GitHub / GitLab / Bitbucket),
  makes the smallest change, pushes to the SAME PR branch, and reports the refine turn. The engine is
  still the only judge.
---

# mega-loop refine — apply PR review feedback (a revision)

Refine ≠ fix. The fix already shipped a PR; a maintainer left review comments. This applies those
comments as the **smallest revision on the SAME PR branch**, re-verifies, and reports it — it never
opens a new PR and never re-fixes unrelated things.

On `unauthorized` → run **`/mega-loop:status`** first (setup doctor — set the PAT via `/plugin`);
`forbidden` → the project isn't yours (`connect` and re-pick).

## 1. Find the PR + check out its branch

Resolve the bug/PR from the user's words. Get the fix's PR + branch — pull the handoff
(**`get_handoff(project=<active>, handoff_id=…)`** carries `branch` + the PR url and, if a refine was
armed on the dashboard, a **refine instruction** as its `instructions`), or the user names the PR.
Then: `git fetch && git checkout <branch>` (a handoff fix's branch is `autofix/<handoff_id>`).

## 2. Read the maintainer's review comments — host-aware

Detect the host from `git remote get-url origin`, then read the **unresolved** review comments
(file · line · the ask). Ignore outdated/resolved ones.

- **GitHub** (`gh`): `gh pr view <n> --json reviews,comments`  ·  inline:
  `gh api repos/<owner>/<repo>/pulls/<n>/comments`
- **GitLab** (`glab`): `glab mr view <n>`  ·  inline:
  `glab api projects/<id>/merge_requests/<n>/notes` (or `discussions`)
- **Bitbucket** (no `gh`/`glab`): `curl -u <user>:<app_password>
  https://api.bitbucket.org/2.0/repositories/<ws>/<repo>/pullrequests/<n>/comments`

If you can't read comments programmatically (no CLI / no Bitbucket app password), **ask the user to
paste the review feedback**.

## 3. Apply the SMALLEST change

Address **only** what the comments ask — no scope creep. Then re-verify exactly like a fix: reproduce
the failing case (**`get_trace`** / **`get_cases`**) still passes, and run the relevant tests
(regressions = only REAL breakage).

## 4. Start the refine turn, push to the SAME branch, report

- **Start a tracked refine turn from the terminal** (no dashboard needed) — pass the maintainer's
  feedback so it's recorded:
  **`arm_refine(project=<active>, handoff_id=…, bug_key=<the bug's issue key>, comment=<the review
  feedback>, branch=<PR branch>, pr_url=…)`** → returns a **`refine_turn_id`**. (Already armed on the
  dashboard? `get_handoff` returned a refine instruction — reuse that turn instead of arming again;
  `arm_refine` refuses with `refine_running` if one is already open.)
- Commit and **push to the existing PR branch** (`git push`) — host-agnostic; the open PR/MR updates
  **in place**. Do **not** open a new PR.
- Report the confirm turn so the refine thread + the engine see it:
  **`report_status(project=<active>, handoff_id=…, refine_turn_id=<from arm_refine>, phase="confirm",
  verified=true, branch=…, diff=<git diff>, commits=[…], review_comments=[…])`** — after you've
  verified. (Use `phase="spot_fix"` first if you want to propose-then-confirm.)

## Guardrails

- **Same PR / same branch** — never open a new PR for a refine.
- Only address the review comments; don't re-fix or "helpfully" change unrelated code.
- **The engine is the only judge** — re-verify before you confirm; never self-certify a refine.
