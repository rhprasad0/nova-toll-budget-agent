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
intent → explorer → pre-checker → builder → review 1
review 1 → PASS | FAIL → builder → review 2
review 2 → PASS | CRITICAL → builder → focused recheck
PASS → human review
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
6. For review 1, update `STATE.md`, then spawn a fresh `checker` and a fresh
   `security_reviewer`, both with `fork_turns: "none"`, before waiting for
   either result. They review the same builder output concurrently. Checker
   reads the worktree and artifacts, writes `verdict.md`, and never edits
   application code. Security reviewer remains read-only and reports its result
   to the parent without writing a graph artifact.
7. Review 1 keeps the full existing gate: PASS requires checker PASS and no
   actionable security findings. If either lane fails, update `STATE.md` and
   return evidence from every failing lane, and no evidence from passing lanes,
   to the original builder. Do not restart exploration or pre-checking. After
   repair, run review 2 with fresh checker and security reviewer lanes as in
   step 6.
8. Review 2 fails only for a critical issue: an exploitable security
   vulnerability, potential data or secret loss or exposure, or inability to
   perform the requested core function. Record every other finding as a
   non-blocking note for human review and pass the graph.
9. Return critical review-2 findings to the original builder. After repair,
   spawn a fresh reviewer only for each lane that reported a critical issue,
   scoped to confirming that issue is fixed. Repeat this builder and focused
   recheck loop while the critical issue remains; never restart the graph or
   escalate because of a retry count. Stop only if repair needs user input or
   authority.
10. On PASS, update `STATE.md`, then summarize files, checks, remaining risk,
    and non-blocking notes for human review.

Before every spawn or handoff, and on every blocker, FAIL, or PASS, rewrite
`STATE.md` to match the current node and next legal edge. Keep its exactly five
lines—Intent, Worktree, Current node, Next legal edge (including the review
round or focused recheck lanes), Blocked by. Never run parallel writers or
allow subagents to spawn subagents; checker alone writes `verdict.md`, security
reviewer writes no artifact, and checker plus security review are the only
concurrent work.

The pre-checker and review-1 checker must require a ponytail review before
completion: the pre-checker reviews the explored design and draft checklist;
the checker reviews the implementation diff. Look for unnecessary abstractions,
dependencies, configurability, operational machinery, and code replaced by the
standard library or platform. A finding is blocking when a materially simpler
design satisfies the intent; name its location, what to remove, and the
replacement. Complexity required by the user, an existing contract, security,
or data safety is exempt. Each checker records its findings or `Lean already`.

Temporary downtime is acceptable because this reference project has no users.
Pre-checking and both review rounds must not block or require high availability,
zero-downtime deployment, staged rollout, or rollback machinery solely to avoid
an outage unless the intent explicitly requires it. This does not relax
security, data safety, credential handling, or migration authorization.

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
- `.graph/verdict.md`: review round, PASS or FAIL, checks and evidence, broken
  assumptions, ponytail findings, critical status, non-blocking human-review
  notes, and the required fix on FAIL. “Looks good” is not a verdict.

## Current-run truth

Use only the assigned worktree's `.graph/` artifacts to schedule the current
run. AgentMemory may supply background architecture, decisions, and pitfalls,
but never determines the current node.

Continue until:

- review 1 passes, or review 2 and any focused rechecks have no critical issues
- a blocking gap requires user input or authority
