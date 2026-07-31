---
name: connect
description: >
  Pick which mega-loop project this session works on. Use when the user says "connect", "which
  project", "switch project", or before listing bugs / fixing when no project is chosen yet. Lists
  the user's projects and remembers the one they pick for later commands.
---

# mega-loop connect — choose the active project

The companion works on one project at a time. This skill picks it; later skills (bugs, explain, fix)
reuse that choice, so the user names it **once**.

## Steps

1. Call the **`list_projects`** MCP tool → the user's projects (`id` + `name`). On `unauthorized`,
   tell the user to run **`/mega-loop:status`** first (it checks setup + how to set the PAT).
2. Present them **by name** (never make the user type an id):
   - Exactly one project → use it, no prompt.
   - Several → list them and ask which; match the user's words to a name.
   - None → they have no projects yet; tell them to create one on the **web dashboard** first (see
     "Setting up a project" below).
3. **Remember the chosen project's `id`** for the rest of this session — pass it as the `project`
   argument to `list_bugs`, `get_bug`, `autofix`, etc. Do not ask for the project again unless the
   user switches.
4. **Persist the choice to this repo** so a future session reuses it (connect once, not every
   time). Write `.mega/companion/project.json` in the current working directory:
   ```json
   {"id": "<project id>", "name": "<project name>", "base_url": "<user_config.base_url>"}
   ```
   (create `.mega/companion/` if needed; add `.mega/` to `.gitignore` if it isn't already — it's
   local state, not repo content). On the next session the **restore-connection** hook reads this
   and tells you the active project automatically — no re-connect. The user clears it with
   **`/mega-loop:disconnect`**.

## Setting up a project / trace source (web-only, by design)

Creating a project and connecting a **trace source** (Langfuse / Phoenix / LangSmith) is done on the
**web dashboard**, not here — it needs provider secret keys and a live "test connection" check that
belong in the browser, not pasted through the terminal. If a chosen project has **no bugs yet**, it
likely has no trace source or hasn't been analyzed: tell the user to connect a source on the web,
then come back. (A future `connect_project` verb may bring source-binding into the terminal; for now
it's web-only — see design 56 §7.)

## Guardrails

- Never invent a project id — only use ids returned by `list_projects`.
- If the user names a project that isn't in the list, say so and show the actual list; don't guess.
