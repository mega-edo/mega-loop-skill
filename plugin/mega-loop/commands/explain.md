---
description: Explain one mega-loop bug — its cause and the exact file:line
argument-hint: "[bug name or id]"
---
Invoke the **diagnose** skill to explain this bug: its cause and the exact `file:line`
(and the failing input, via `get_trace`, if the user asks). Resolve the bug from the words below;
if none is given, list the open bugs and ask which.

Bug: $ARGUMENTS
