# trace-runtime

The trace validator that the **trace-analyze** and **trace-fix** skills share. It grades a trace
against the eleven readiness checks MEGA Loop runs internally (R0–R3, M1–M7), plus five of its own
(S1–S5) for what MEGA Loop's detection and replay read, which MEGA Loop does not run — and, unlike
the upstream grader, every check also says what to change.

This directory is the maintained home of the validator (mega-loop-skill is its source of truth).
It is not a separately installed package; the two skills call it in place through
`${CLAUDE_PLUGIN_ROOT}/trace-runtime/scripts/validate_traces.py`.

## Run it

```bash
uv run scripts/validate_traces.py --file assets/good-trace.json          # one exported trace
uv run scripts/validate_traces.py --source examples/orders-agent         # source, before traces exist
uv run scripts/validate_traces.py --platform langfuse --last 50          # live traces (needs read creds)
```

`uv run` reads the script's inline dependency metadata and provisions pydantic/httpx in a throwaway
environment — nothing installs into the caller's project. No `uv`? `pip install pydantic httpx` once,
then use `python`.

## Maintain it

```bash
uv run --extra dev pytest        # the sixteen checks, plus the contract-drift guardrail
```

- `src/trace_validator/contract.py` — the single file mirroring MEGA Loop's contract, each constant
  cited to its upstream source. Change checks here and nowhere else.
- `tests/test_contract_drift.py` — pins the three rules that look like oversights; it fails loudly,
  with the reason attached, if anyone "fixes" them. Run the suite after any contract change.
- `references/` — the trace spec, span kinds, and context propagation the checks and skills point at.
- `kits/{python,node,rust}/` — instrumentation templates a developer copies into their own repo.
