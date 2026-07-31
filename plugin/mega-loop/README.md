# Inside the plugin

Installing and using it is covered in the [main README](../../README.md). This page describes what
the package actually contains.

```
plugin/mega-loop/
├── .claude-plugin/plugin.json   manifest + the two config values (base_url, api_token)
├── .mcp.json                    the MCP server, at ${base_url}/companion/mcp
├── skills/                      what Claude Code reads when you speak in plain words
│   ├── connect/                 pick the project this repo works on
│   ├── diagnose/                list bugs · explain one (read only)
│   ├── fix/                     the fix orchestrator — routed by the server
│   └── refine/                  apply PR review feedback to the same branch
├── commands/                    slash-command shortcuts
│   ├── status.md                setup doctor + connected project + fixes in flight
│   ├── bugs.md · explain.md · groups.md      → into the diagnose skill
│   └── projects.md · disconnect.md           → read / clear the saved project
└── hooks/
    ├── restore-connection.sh    re-injects this repo's saved project at session start
    └── gate-on-stop.sh          blocks "done" while a fix is open, until the engine judges
```

Skills are also reachable by name — `/mega-loop:connect`, `/mega-loop:fix`, `/mega-loop:refine` —
so there is no separate command file for them.

## Configuration

Two values, both set through `/plugin` → **mega-loop** → **configure**:

| Key | Sensitive | What it is |
|---|---|---|
| `base_url` | no | The MEGA Loop server, no trailing slash. `https://loop.megacode.ai` (production), `https://loop-beta.megacode.ai` (beta), `http://localhost:18000` (local stack). |
| `api_token` | **yes** | A personal access token (`mlp_…`). Goes into the OS keychain, never a file. Generated on the web only. |

There is no login command and no email/password path. Authentication is the token, and only the
token.

## The MCP server

One HTTP server named `mega-loop`, at `${base_url}/companion/mcp`, authenticated with the token as
a bearer header. Everything the skills do goes through it:

| Group | Verbs |
|---|---|
| Identity | `whoami`, `list_projects` |
| Read | `list_bugs`, `get_bug`, `list_groups`, `get_trace`, `get_cases`, `status`, `get_job_artifacts` |
| Write | `autofix`, `get_handoff`, `report_status`, `gate`, `arm_refine` |

All of them are scoped to the signed-in user. A project that is not yours answers `forbidden`; a
missing or expired token answers `unauthorized`.

## The rule everything else follows

**The engine is the only judge.** No skill and no hook ever scores a fix. When a session fixes code
locally it runs the code and reports what happened; the server decides PASS or FAIL with the same
gate the dashboard and CI use. `gate-on-stop` enforces this by asking the engine — it has no
verdict of its own.
