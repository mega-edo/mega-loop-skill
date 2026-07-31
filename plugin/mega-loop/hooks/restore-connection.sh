#!/usr/bin/env bash
# mega-loop · restore-connection reflex
#
# At session start, if THIS repo was previously connected to a mega-loop project
# (`/mega-loop:connect` wrote `.mega/companion/project.json`), inject that choice so the session
# reuses it — the developer connects a repo to a project ONCE, not every session. Cleared by
# `/mega-loop:disconnect`. Silent when the repo has no saved connection.
set -uo pipefail

payload="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0

cwd="$(printf '%s' "$payload" | jq -r '.cwd // empty')"
[ -n "$cwd" ] || exit 0
marker="$cwd/.mega/companion/project.json"
[ -f "$marker" ] || exit 0

id="$(jq -r '.id // empty' "$marker" 2>/dev/null)"
name="$(jq -r '.name // empty' "$marker" 2>/dev/null)"
[ -n "$id" ] || exit 0

ctx="mega-loop: this repo is already connected to project \"${name:-$id}\" (id ${id}). Use it as the \`project\` for every mega-loop verb — do NOT run connect again. To change it, the user runs /mega-loop:connect; to clear it, /mega-loop:disconnect."
jq -nc --arg c "$ctx" \
  '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $c}}'
exit 0
