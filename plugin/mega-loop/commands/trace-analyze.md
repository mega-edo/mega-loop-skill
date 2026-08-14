---
description: Grade an agent's traces against MEGA Loop's readiness contract and report every fix — read-only
---
Invoke the **trace-analyze** skill to grade the developer's traces (or their source, before any
traces exist) against the same readiness contract MEGA Loop runs internally, and hand back a report:
per trace, whether MEGA Loop can use it, why not, and the exact fix — plus a separate applicability
line for traces that are readable but hold nothing worth detecting. Read-only; it never edits code.
To then apply the fixes, hand off to `/mega-loop:trace-fix`.
