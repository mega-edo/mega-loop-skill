---
description: Disconnect this repo from its saved mega-loop project (stop auto-reconnecting)
---
Delete `.mega/companion/project.json` in the current working directory to un-link this repo from its
saved mega-loop project. After this, a new session won't auto-connect — run `/mega-loop:connect` to
pick a project again. This does not touch your PAT (API access stays); it only clears the saved
project binding for this repo.
