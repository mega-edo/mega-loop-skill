#!/usr/bin/env bash
# Shared helpers for the mega-loop reflex hooks. Sourced, never executed directly.
#
# Every reflex is OPT-IN and degrades silently: no marker / no local analysis API means the hook
# does nothing, so installing the plugin never changes behaviour for a repo that hasn't set anything
# up. NO hook is ever a judge — the engine's gate is the only pass/fail (design 56 rule 1). The old
# local-scorer hooks (pre-commit / guard), which ran a *second* judge over
# `.mega/companion/config.json`, stay removed. gate-on-stop is engine-gated: it only blocks 'done'
# while a fix marker is present and tells the agent to run the `gate` verb — the ENGINE judges via
# that call, the hook never scores.

# cd into the session's cwd from the hook payload, so git resolves against the user's repo.
# Returns NON-ZERO when there's no cwd or the cd fails, so the caller can bail instead of
# silently acting on the wrong directory.
cd_to_payload_cwd() {
  local payload="$1" target
  target="$(printf '%s' "$payload" | jq -r '.cwd // empty')"
  [ -n "$target" ] || return 1
  cd "$target" 2>/dev/null || return 1
}
