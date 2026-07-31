#!/usr/bin/env bash
# mega-loop · gate-on-stop reflex (engine-gated — rule 1)
#
# Block "done" while a mega-loop fix is still open, until the ENGINE gate says PASS. This hook
# NEVER scores anything itself (that would be a second judge — design 56 rule 1). It only checks
# for the in-progress-fix marker the fix skill writes, and — if one is present —
# blocks the stop and tells the agent to run the `gate` verb. The agent has the MCP + PAT, so it
# calls the engine; the engine is the only judge. On PASS the agent deletes the marker and may stop.
#
# Silent + safe: no marker → the hook does nothing, so it never affects a session that isn't
# mid-fix. The stop_hook_active guard means it blocks at most once per stop sequence (no loop).
set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname "$0")/lib.sh"

payload="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0

# Loop guard: if we already blocked once in this stop sequence, let the agent stop.
[ "$(printf '%s' "$payload" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0

cd_to_payload_cwd "$payload" || exit 0
marker=".mega/companion/active-fix.json"
[ -f "$marker" ] || exit 0

# Stale-marker guard: an abandoned fix must not nag the first Stop of every later session forever.
# If the marker is older than 24h (mtime), treat it as stale and step aside — a live fix re-writes
# it each run, so a genuinely active fix is never this old.
if find "$marker" -mmin +1440 2>/dev/null | grep -q .; then
  exit 0
fi

bug="$(jq -r '.bug_id // "the active bug"' "$marker" 2>/dev/null || printf 'the active bug')"
proj="$(jq -r '.project // ""' "$marker" 2>/dev/null || printf '')"

jq -nc --arg r "mega-loop gate-on-stop — a fix for $bug is still open. Before declaring done, get the engine's verdict: call gate(project=\"$proj\", bug_id=\"$bug\"). If it is PASS, delete $marker and you may stop; if FAIL or PENDING, address it and re-verify. The engine is the only judge — do not self-certify." \
  '{decision: "block", reason: $r}'
exit 0
