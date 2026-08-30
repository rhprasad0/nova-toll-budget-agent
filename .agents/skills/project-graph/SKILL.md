---
name: project-graph
description: Run this repository's explorer, pre-checker, builder, and checker graph for a non-trivial change.
---

# Project Graph

Treat the text following `$project-graph` as the intent.

Follow the **When to use the graph**, **Graph**, **Parent checklist**, and
**Artifacts** sections of `AGENTS.md` exactly.

The parent orchestrates only. Do not inspect the repository, implement, or
verify in the parent thread.

If `.graph/checklist.md` has blocking gaps, return it to the original explorer
and rerun the pre-checker; do not stop solely for that checklist.

Continue until:

- the checker returns PASS
- a blocking gap requires human input after the prescribed explorer return
- two failed fix loops require user intervention
