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
│   ├── refine/                  apply PR review feedback to the same branch
│   ├── trace-gen/               instrument code that emits nothing, then grade the result
│   ├── trace-analyze/           grade traces against the readiness contract (read only)
│   └── trace-fix/               fix the instrumentation until traces pass
├── commands/                    slash-command shortcuts
│   ├── status.md                setup doctor + connected project + fixes in flight
│   ├── bugs.md · explain.md · groups.md      → into the diagnose skill
│   ├── projects.md · disconnect.md           → read / clear the saved project
│   └── trace-gen.md · trace-analyze.md · trace-fix.md  → start / grade / repair tracing
├── trace-runtime/               the trace validator both trace-* skills share — maintained here
│   ├── scripts/validate_traces.py   run with `uv run` — deps are self-contained
│   ├── src/trace_validator/     the fourteen checks and the readiness contract
│   ├── kits/{python,node}/      instrumentation templates to copy into a repo
│   ├── references/              the trace spec, span kinds, context propagation
│   ├── assets/                  good / broken example traces for a smoke test
│   ├── examples/orders-agent/   one agent, naive vs instrumented — the discrimination proof
│   ├── tests/                   `uv run --extra dev pytest`; test_contract_drift.py pins the contract
│   └── pyproject.toml · uv.lock     dev deps and the pinned lock for the test suite
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
