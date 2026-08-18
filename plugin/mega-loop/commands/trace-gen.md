---
description: Instrument an agent that emits no traces yet, then prove the first ones are readable
---
Invoke the **trace-gen** skill to add tracing to a codebase that has none. It reads the repository
to find where a request begins and what the agent does inside one, installs the kit for the stack,
writes the spans, then runs the app for real and grades the traces that come out — because a
source with no traces cannot be graded, only guessed at. Use `/mega-loop:trace-analyze` when
traces already exist, and `/mega-loop:trace-fix` when they exist and fail.
