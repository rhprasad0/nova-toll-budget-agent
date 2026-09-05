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

The GPT-6 Astra parent normally orchestrates. When a subagent stalls, it may
inspect the repository, diagnose failures, run focused checks, and take over
bounded exploration or implementation under the intervention rules below.
Keep subagents on their existing models and reasoning efforts in `.codex/agents/`.

```text
intent → explorer → pre-checker → builder → review 1
review 1 → PASS | FAIL → builder → review 2
review 2 → PASS | CRITICAL → builder → critical recheck
critical recheck → PASS | CRITICAL → builder
PASS → human review
```

1. Create or reuse an isolated project-root `.worktrees/` path. Keep `.graph/`
   inside that worktree gitignored and free of secrets.
2. Update `.graph/STATE.md`, then spawn `explorer` with `fork_turns: "none"`,
   the intent, and the absolute worktree path. The synchronous `SubagentStart`
   hook supplies the child’s native UUID; wait for the child to report that UUID
   before it uses tools, then register it with the hook CLI and send an explicit
   registration acknowledgement. Run `python3 <active-checkout>/.codex/hooks/graph-write-guard.py register <agent-id> <role> <absolute-worktree>` for that registration. The collaboration task name is never an ID.
   Preserve this same registration across follow-ups, repairs, and review turns.
   Wait for `explore.md`.
3. If exploration has a blocking gap, update `STATE.md` and try to resolve it
   from available evidence. Ask the user only when missing intent, information,
   or authority prevents progress.
4. Update `STATE.md`, then spawn `pre_checker` with `fork_turns: "none"`,
   `explore.md`, and the worktree. Repeat the UUID report, CLI registration,
   and acknowledgement before the child’s first tool call. Builder starts only
   after a non-blocking `checklist.md`. Return blocking checklist gaps to the
   original explorer and rerun a new pre-checker after repair.
5. Update `STATE.md`, then spawn one `builder` with `fork_turns: "none"`, the
   worktree, `explore.md`, and `checklist.md`. Register and acknowledge its hook
   UUID before tools; retain the original assignment for any follow-up or
   repair. It implements and writes `change.md`.
6. For review 1, update `STATE.md`, then spawn a fresh `checker` and a fresh
   `security_reviewer`, both with `fork_turns: "none"`, and identify the review
   stage in each task before waiting for either result. They review the same
   builder output concurrently. Register and acknowledge the checker UUID before
   tools and retain its assignment through review follow-ups. Checker reads the
   worktree and artifacts, writes `verdict.md`, and never edits application code.
   Security reviewer remains read-only, outside this guard, and reports its
   result to the parent without writing a graph artifact. The Astra parent is
   also outside the guard.
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
   run a critical recheck with a fresh checker and security reviewer over the
   complete repaired diff. The review-2 critical-only failure threshold still
   applies. Return any critical finding to the original builder and repeat the
   recheck; never restart the graph or escalate because of a retry count. Stop
   only if repair needs user input or authority.
10. On PASS, update `STATE.md`, then summarize files, checks, remaining risk,
    and non-blocking notes for human review.

Before every spawn or handoff, and on every blocker, FAIL, or PASS, rewrite
`STATE.md` to match the current node and next legal edge. Keep its exactly five
lines—Intent, Worktree, Current node, Next legal edge (including the review
round or critical recheck), Blocked by. Never run parallel writers or
allow subagents to spawn subagents; checker alone writes `verdict.md`, security
reviewer writes no artifact, and checker plus security review are the only
concurrent subagent work. The parent may inspect evidence while a subagent runs.

## Orchestrator intervention

Intervene when a subagent repeats a failed approach without new evidence,
loops through the same review finding, reports an impasse, or cannot explain
what its ongoing work will resolve. Elapsed time alone is not a failure:
check whether a long-running command is making useful progress.

1. Request the current finding, blocker, running command, and next concrete
   result. Inspect the current artifacts and relevant code or output yourself;
   do not keep sending status requests while the task remains stuck.
2. Give a specific correction, a smaller subtask, or evidence that resolves the
   blocker. If this does not restore progress, interrupt the subagent and take
   over the bounded diagnosis, exploration, or implementation needed to unblock
   it. Do not wait for another identical failure or ask the user to debug a
   problem you can resolve within the authorized scope.
3. Before taking over, confirm the subagent and any commands it started have
   stopped, with no pending writes. Pause any other active review lane before
   changing its inputs. Update `STATE.md` to name the parent intervention at the
   current node and the next legal edge. Preserve existing edits and work only
   in the assigned worktree; never allow overlapping writers.
4. Record evidence and changes in the artifact for the current work:
   `explore.md` for exploration or `change.md` for implementation. Resume the
   original subagent with a concrete handoff when useful; replace it with a
   fresh agent of the same role and configured model if its context is no
   longer useful. References above to the original agent then mean its replacement.
5. Preserve the gates: a pre-checker must produce a non-blocking checklist before
   implementation. If intervention changes the scope or invalidates that
   checklist, update exploration and obtain a new pre-check before building.
   The parent never writes `checklist.md` or `verdict.md`, substitutes its own
   checks for independent review, or declares its own repair approved. Send
   every implementation repair through fresh checker and security-review lanes
   at the current review stage (review 1 if review has not started). Do not reset
   the review round, weaken acceptance criteria, or
   bypass security, data-safety, or authorization boundaries to make progress.

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
