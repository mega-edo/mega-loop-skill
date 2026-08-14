---
name: diagnose
description: >
  Read what mega-loop diagnosed from production traces — list the open bugs for your project, and
  explain one bug's cause + the exact file:line. Use when the user asks "what's broken / what should
  I fix / where / why" about a mega-loop project, or says "bugs" / "explain". Read-only: it reports,
  it never edits. To actually fix, hand off to the fix skill.
---

# mega-loop diagnose — bugs + explain (read-only)

Read verbs over a project's diagnosed bugs. They need the **active project** (pick it with
connect); pass its id as `project`.

## bugs — "what's broken?"

Call **`list_bugs(project=<active>)`** (optionally `states=["open"]`). It returns the bugs — id,
title, severity, trace count. Present them **by title**, worst severity first — never make the user
read ids. Match the user's words to a title to get the `bug_id`.

## explain — "why is this failing, and where?"

Call **`get_bug(project=<active>, bug_id=<from the list>)`** → the bug's cause and the exact
`file:line` (when a trace anchored it; it may be absent — **never guess a location**). To show the
failing input, call **`get_trace(project=<active>, trace_id=<from the bug>)`** — the spans
(input / output / error) that reproduce it. Report the cause, the `file:line` if present, and the
evidence.

## Handoffs

- The user wants to **fix** it → switch to **fix** (`autofix <the bug>`).
- **No bugs, or the project has few/low-readiness traces** → MEGA Loop may have nothing to detect on
  yet. Point them at **`/mega-loop:trace-analyze`** to grade their traces (or their source) against
  the readiness contract before expecting bugs.
- Any tool returns **`unauthorized`** → the PAT isn't set; run **`/mega-loop:status`** (setup doctor).
- Any tool returns **`forbidden`** → that project isn't theirs; re-run `list_projects` and re-pick.

## Guardrails

- Read-only: never edit code or open PRs here.
- Never fabricate a `file:line` — report it as absent honestly when the anchor didn't resolve.
