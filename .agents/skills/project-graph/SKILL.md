---
name: project-graph
description: Run this repository's explorer, pre-checker, builder, and checker graph for a non-trivial change.
---

# Project Graph

Treat the text following `$project-graph` as the intent.

Use this graph when a change is non-trivial because it:

- touches more than one area, such as application and infrastructure
- changes a high-risk runtime path, evaluation strategy, or deployment shape
- requires repo-wide discovery or independent verification
- is explicitly requested by the user

Skip the graph for questions, docs-only edits, mechanical changes, and localized
low-risk fixes.

## Workflow

The parent orchestrates only. Do not inspect the repository, implement, or
verify in the parent thread.

```text
intent → explorer → pre-checker → builder → checker → PASS | FAIL→builder | human
```

1. Create or reuse an isolated project-root `.worktrees/` path. Keep `.graph/`
   inside that worktree gitignored and free of secrets.
2. Update `.graph/STATE.md`, then spawn `explorer` with `fork_turns: "none"`,
   the intent, and the absolute worktree path. Wait for `explore.md`.
3. If exploration has a blocking gap, update `STATE.md`, stop, and ask the user.
4. Update `STATE.md`, then spawn `pre_checker` with `fork_turns: "none"`,
   `explore.md`, and the worktree. Builder starts only after a non-blocking
   `checklist.md`. Return blocking checklist gaps to the original explorer and
   rerun a new pre-checker after repair.
5. Update `STATE.md`, then spawn one `builder` with `fork_turns: "none"`, the
   worktree, `explore.md`, and `checklist.md`. It implements and writes
   `change.md`.
6. Update `STATE.md`, then spawn a new `checker` with `fork_turns: "none"`.
   It reads the worktree and artifacts, writes `verdict.md`, and never edits
   application code.
7. On FAIL, update `STATE.md` and return `verdict.md` to the original builder.
   After repair, run a new checker. Stop for the user after two failed fix loops.
8. On PASS, update `STATE.md`, then summarize files, checks, and remaining risk.

Before every spawn or handoff, and on every blocker, FAIL, or PASS, rewrite
`STATE.md` to match the current node and next legal edge. Never run parallel
writers or allow subagents to spawn subagents. Explorers, pre-checkers, and
checkers may fan out.

## Artifacts

All paths are relative to the assigned worktree:

- `.graph/STATE.md`: exactly five lines—Intent, Worktree, Current node, Next
  legal edge, Blocked by.
- `.graph/explore.md`: question, owners/entrypoints, current behavior, files in
  scope, assumptions, falsifiers, out of scope, gaps.
- `.graph/checklist.md`: preconditions, numbered acceptance requirements,
  required commands and pass conditions, risk-focused checks, blocking gaps.
- `.graph/change.md`: intent, files touched, assumptions accepted, commands
  run, how to verify, what was not done.
- `.graph/verdict.md`: PASS or FAIL, checks and evidence, broken assumptions,
  and the required fix on FAIL. “Looks good” is not a verdict.

## Current-run truth

Use only the assigned worktree's `.graph/` artifacts to schedule the current
run. AgentMemory may supply background architecture, decisions, and pitfalls,
but never determines the current node.

Continue until:

- the checker returns PASS
- a blocking gap requires human input after the prescribed explorer return
- two failed fix loops require user intervention
