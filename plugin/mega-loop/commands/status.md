---
description: Show mega-loop status — setup/auth, the connected project, all your projects, and any fix in flight
argument-hint: "[job id]"
---
Produce a **mega-loop status report** in three sections. This is also the setup doctor — there is no
separate login command; the plugin's PAT is set as **plugin config** (`api_token` + `base_url`), and
this report says whether that's done and what to do if not.

Saved connection for this repo (read-only, may be empty):
!`cat .mega/companion/project.json 2>/dev/null || echo "{}  (no saved project — not connected yet)"`

## 1. Setup & auth

Call the **`whoami`** MCP tool, then report:

- **Success** (returns `email` + `base_url`) → setup is **complete**:
  - `api_token` — **set & valid** (the PAT authenticated).
  - `base_url` — the returned `base_url` (the mega-loop server the token reached).
  - **Logged in as** `<email>`.
- **`unauthorized` / 401** → `api_token` is **missing, wrong, or expired**. Setup is incomplete.
- **The tool/MCP is unreachable** (not registered, connection refused) → `base_url` is unset or the
  server is down. Setup is incomplete.

If setup is **incomplete**, stop after this section and walk the user through it:

1. **Generate a PAT** on the web dashboard → **Account → Personal Access Tokens → Generate** (copy the
   `mlp_…`, shown once).
2. **Set the plugin config** — run `/plugin` → **mega-loop** → **configure**, then paste the token in
   the masked **`api_token`** field (stored in the OS keychain, never in a file or the chat). Set
   **`base_url`** on the same screen — `https://loop.megacode.ai` (prod) or `http://localhost:18000`
   (local dev).
3. **Reload / restart Claude Code** so the MCP picks up the token, then run `/mega-loop:status` again.

Never ask the user to paste the PAT into the chat — if they do, tell them it's now in the transcript,
to revoke it on the web and set a fresh one through `/plugin`.

## 2. Connected project

- If the saved-connection block above has an `id` → **connected to** `<name>` (`<id>`). This repo
  reuses it every session (the restore-connection reflex); change it with `/mega-loop:connect`, clear
  it with `/mega-loop:disconnect`.
- If empty → **not connected to a project yet** → tell them to run `/mega-loop:connect`.

Then call **`list_projects`** and list **all** the user's projects by name, marking each with its
autofix `mode` (bound → **engine**, unbound → **handoff**) and flagging the connected one.

## 3. Active project — bugs & fixes in flight

Only if connected (or exactly one project): call the **`status`** verb for that project and report the
bug counts (total / resolved / open) plus any engine jobs and handoffs in flight.

If a **job id** is given below, poll **that** engine job's live status instead of the overview.

Job id (optional): $ARGUMENTS
