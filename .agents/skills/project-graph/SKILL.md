---
name: project-graph
description: Run this repository's explorer, implementer, and verifier graph for a non-trivial change.
---

# Project Graph

Treat the text following `$project-graph` as the intent.

Follow the **When to use the graph**, **Graph**, **Parent checklist**, and
**Artifacts** sections of `AGENTS.md` exactly.

The parent orchestrates only. Do not inspect the repository, implement, or
verify in the parent thread.

Continue until:

- the verifier returns PASS
- an artifact reports a blocking gap
- two failed fix loops require user intervention
