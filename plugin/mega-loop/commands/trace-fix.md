---
description: Fix an agent's instrumentation so its traces pass MEGA Loop's readiness contract, then prove it
---
Invoke the **trace-fix** skill to edit the developer's instrumentation until their traces are usable
by MEGA Loop — one clean trace per request, OpenInference-compliant — applying the kit, working the
findings in the order that clears the most traces, and re-running the validator until the verdicts
reach `entry_seatable`. This edits code. To only see what is wrong without changing anything, use
`/mega-loop:trace-analyze` first.
