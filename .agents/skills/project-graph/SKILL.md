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
intent → explorer → pre-checker → builder → checker + security_reviewer → PASS | FAIL→builder | human
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
6. After every builder pass, update `STATE.md`, then spawn a fresh `checker`
   and a fresh `security_reviewer`, both with `fork_turns: "none"`, before
   waiting for either result. They review the same builder output concurrently.
   Checker reads the worktree and artifacts, writes `verdict.md`, and never
   edits application code. Security reviewer remains read-only and reports its
   result to the parent without writing a graph artifact.
7. Wait for both lanes. PASS requires checker PASS and no actionable security
   findings. If either lane fails, update `STATE.md` and return evidence from
   every failing lane, and no evidence from passing lanes, to the original
   builder. After repair, repeat step 6 for both lanes. The initial failure
   opens a repair loop; on each failed post-repair review, increment only that
   lane's failed-fix-loop count. A pass in either lane never resets or consumes
   either count. This applies to checker-only, security-only, and joint
   failures; either previously passing lane may fail after a repair. Stop for
   human intervention immediately when checker or security reaches two failed
   post-repair reviews; do not start another repair.
8. On PASS, update `STATE.md`, then summarize files, checks, and remaining risk.

Before every spawn or handoff, and on every blocker, FAIL, or PASS, rewrite
`STATE.md` to match the current node and next legal edge. Keep its exactly five
lines—Intent, Worktree, Current node, Next legal edge (including separate
checker and security failed-fix-loop counts), Blocked by. Never run parallel
writers or allow subagents to spawn subagents; checker alone writes
`verdict.md`, security reviewer writes no artifact, and their two post-builder
review lanes are the only concurrent work.

The pre-checker and final checker must require a ponytail review before
completion: the pre-checker reviews the explored design and draft checklist;
the checker reviews the implementation diff. Look for unnecessary abstractions,
dependencies, configurability, operational machinery, and code replaced by the
standard library or platform. A finding is blocking when a materially simpler
design satisfies the intent; name its location, what to remove, and the
replacement. Complexity required by the user, an existing contract, security,
or data safety is exempt. Each checker records its findings or `Lean already`.

## Artifacts

All paths are relative to the assigned worktree:

- `.graph/STATE.md`: exactly five lines—Intent, Worktree, Current node, Next
  legal edge, Blocked by.
- `.graph/explore.md`: question, owners/entrypoints, current behavior, files in
  scope, assumptions, falsifiers, out of scope, gaps.
- `.graph/checklist.md`: preconditions, numbered acceptance requirements,
  required commands and pass conditions, risk-focused checks, ponytail findings,
  blocking gaps.
- `.graph/change.md`: intent, files touched, assumptions accepted, commands
  run, how to verify, what was not done.
- `.graph/verdict.md`: PASS or FAIL, checks and evidence, broken assumptions,
  ponytail findings, and the required fix on FAIL. “Looks good” is not a verdict.

## Current-run truth

Use only the assigned worktree's `.graph/` artifacts to schedule the current
run. AgentMemory may supply background architecture, decisions, and pitfalls,
but never determines the current node.

Continue until:

- checker returns PASS and security reviewer reports no actionable findings
- a blocking gap requires human input after the prescribed explorer return
- checker or security reviewer reaches two failed post-repair reviews, which
  requires user intervention
