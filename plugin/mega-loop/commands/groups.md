---
description: List the project's bugs grouped into packaging units (the shape a fix ships)
---
Call the mega-loop `list_groups` verb and show the active project's bugs **grouped** — one row per
group with its **shape** (single / conflict / stack), title, severity, and member bugs. This is how
`autofix` ships a fix (one coordinated PR per group), so a group with >1 member is why
`/mega-loop:fix <one bug>` can come back `group_only` — fix the whole group instead.
