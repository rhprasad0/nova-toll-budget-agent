---
name: project-graph
description: Run this repository's explorer, researcher, pre-checker, builder, and checker graph for a non-trivial change.
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

The GPT-5.6 Sol parent normally orchestrates. When a subagent stalls, it may
inspect the repository, diagnose failures, run focused checks, and take over
bounded exploration or implementation under the intervention rules below.
Keep subagent safeguards and tool settings in `.codex/agents/`; Root selects
model and reasoning effort explicitly from the profile table below.

Authority is explicit: Root writes and owns `.graph/contract.md`,
`.graph/acceptance.md`, and `.graph/STATE.md`. The Root contract records the
risk class, selected child profile, authoritative scope, and acceptance rules;
the acceptance artifact records Root's rationale and disposition. The intent,
Root contract, and `.graph/explore.md` define approved scope, and the numbered
requirements in `.graph/checklist.md` define acceptance. `.graph/research.md`
is supporting evidence only and cannot widen or override those artifacts. A
research conflict with an authoritative artifact blocks pre-checking and must
return to the explorer.

Root model and reasoning effort remain user/host-selected and are never pinned
in repository config or this graph. Root chooses exactly one deterministic
child profile for every spawn and passes `model`, `reasoning_effort`, and
`fork_turns: "none"` explicitly. The standard profile is:

| role | model | effort |
| --- | --- | --- |
| Explorer | `gpt-5.6-luna` | `high` |
| Researcher | `gpt-5.6-luna` | `high` |
| Pre-checker | `gpt-5.6-terra` | `high` |
| Builder | `gpt-5.6-luna` | `xhigh` |
| Checker | `gpt-5.6-luna` | `high` |
| Security | `gpt-5.6-luna` | `high` |

The `production-high` profile is:

| role | model | effort |
| --- | --- | --- |
| Explorer | `gpt-5.6-luna` | `max` |
| Researcher | `gpt-5.6-luna` | `max` |
| Pre-checker | `gpt-5.6-terra` | `high` |
| Builder | `gpt-5.6-terra` | `high` |
| Checker | `gpt-5.6-terra` | `high` |
| Security | `gpt-5.6-sol` | `high` |

The current host contract accepts `max` for Luna in this workflow. If the
active spawn surface hides or rejects an explicit override, Root records a
host-capability block; it never silently substitutes a role-file or Root
default.

```text
intent → explorer → researcher → pre-checker → builder → review 1
review 1 → PASS | FAIL → builder → review 2
review 2 → Root repair | Root accept | Root block
Root repair → builder → same review stage
Root accept/PASS → human review
```

1. Create or reuse an isolated project-root `.worktrees/` path. Keep `.graph/`
   inside that worktree gitignored and free of secrets. Root first writes or
   refreshes `.graph/contract.md`, `.graph/acceptance.md`, and the five-line
   `.graph/STATE.md`, selecting either `standard` or `production-high`.
2. Update `.graph/STATE.md`, then spawn `explorer` with the selected profile's
   explicit `model`, `reasoning_effort`, and `fork_turns: "none"`, the intent,
   `.graph/contract.md`, and absolute worktree path. The synchronous `SubagentStart`
   hook supplies the child's native UUID; wait for the child to report it,
   register it with the hook CLI, and send an explicit registration
   acknowledgement before tools. Run `python3 <active-checkout>/.codex/hooks/graph-write-guard.py register <agent-id> <role> <absolute-worktree>` for that registration. The collaboration task name is never an ID. Preserve this registration across follow-ups and repairs. Wait for `explore.md`.
3. If exploration has a blocking gap, update `STATE.md` and try to resolve it
   from available evidence. Ask the user only when missing intent, information,
   or authority prevents progress.
4. Update `STATE.md`, then spawn the mandatory sequential `researcher` with the
   selected profile's explicit `model`, `reasoning_effort`, and
   `fork_turns: "none"`, the intent, `.graph/contract.md`, `explore.md`, and worktree.
   Repeat the UUID report, CLI registration, and acknowledgement before tools.
   Researcher must complete `research.md` before pre-checking or building;
   there is no skip edge. Researcher must test and use Context7, the AWS
   documentation MCP, and Exa for bounded in-scope lookups. If a required
   server reports an auth blocker, report only its name and a sanitized blocker,
   never include tokens or raw error/query payloads in the parent handoff or
   `research.md`, update `STATE.md` `Blocked by`, pause for authentication, and
   resume the same registered researcher after confirmation. Do not silently
   fall back or claim completion. Treat non-auth outages as explicit research
   gaps under the existing blocker rules.
5. Update `STATE.md`, then spawn `pre_checker` with the selected profile's
   explicit `model`, `reasoning_effort`, and `fork_turns: "none"`,
   `.graph/contract.md`, `explore.md`, `research.md`, and the worktree. Repeat the UUID report, CLI
   registration, and acknowledgement before tools. Builder
   starts only after a non-blocking `checklist.md`. Allow one pre-check repair
   cycle per graph run: on the first blocking checklist, record `pre-check repair
   1/1` in `STATE.md`, return the gaps to the original explorer, rerun the
   original researcher on the repaired `explore.md`, and then run one fresh
   pre-checker. If that fresh pre-checker reports any blocking gap, update
   `STATE.md` `Blocked by` with the remaining gap and stop for user direction;
   never spawn a third pre-checker.
6. Update `STATE.md`, then spawn one `builder` with the selected profile's
   explicit `model`, `reasoning_effort`, and `fork_turns: "none"`, the worktree,
   `.graph/contract.md`, `explore.md`, `research.md`, and `checklist.md`. Register and
   acknowledge its hook UUID before tools; retain the original assignment for
   any follow-up or repair. Builder is the sole source writer for scoped files
   and may write only `.graph/change.md` among graph artifacts; it cannot write
   Root authority or another child's evidence artifact.
7. For review 1, update `STATE.md`, then spawn a fresh `checker` and a fresh
   `security_reviewer`, each with its selected profile's explicit `model`,
   `reasoning_effort`, and `fork_turns: "none"`, and identify the review stage
   in each task before waiting for either result. They review the same builder
   output concurrently. Pass `.graph/contract.md` to both reviewers, register and acknowledge both native UUIDs before tools
   and retain each assignment through follow-ups. Checker writes only
   `.graph/verdict.md`; Security writes only the durable
   `.graph/security-verdict.md`. Both are source-read-only, Security is guarded
   by native-ID/worktree registration, and its verdict is evidence—not deploy
   authority. The Root parent is outside the guard and never implements source.
8. Review 1 keeps the full existing gate: PASS requires checker PASS, no
   actionable Security findings, and complete/readable required review
   artifacts. If either lane fails, update `STATE.md`. A
   checker-found conflict between research and the authoritative intent,
   `explore.md`, or `checklist.md` is a planning failure: pause the builder,
   return that conflict to the original explorer, rerun the original researcher,
   and run a fresh pre-checker subject to the one-cycle limit in step 5. After a
   non-blocking checklist, return any other failing-lane evidence to the original
   builder; otherwise return every failing-lane finding directly to that builder.
   Never include evidence from a passing lane. Do not restart exploration or
   pre-checking for implementation or security findings. After repair, rerun
   review at the same stage with fresh checker and security reviewer lanes as in
   step 7.
9. Review 2 is a Root disposition gate. A completed review advances only when
   Root explicitly chooses `repair`, `accept`, or `block` and records the choice
   plus rationale in `.graph/acceptance.md`. `repair` returns to the original
   Builder; `block` stops for user or authority input. Root may choose `accept`
   only for noncritical findings after every required artifact and evidence item
   is complete. Critical findings, missing required artifacts, incomplete
   required evidence, and any failed instrumentation status force `repair` or
   `block`; they cannot be accepted or represented as PASS. Security's durable
   verdict must be present and readable before acceptance.
10. Review 2 and every critical recheck fail for a critical issue—an exploitable
    security vulnerability, potential data or secret loss or exposure, or
    inability to perform the requested core function—or for either graph-
    integrity exception: missing failure-boundary instrumentation evidence as
    specified below, or a conflict between research and an authoritative
    artifact. Return those findings to the original Builder or planning-repair
    edge as applicable. After implementation repair, run a fresh checker and
    security reviewer over the complete repaired diff at the same stage. Repeat
    until PASS or until repair needs user input or authority.
11. On Root acceptance/PASS, update `STATE.md` and summarize files, checks,
    remaining risk, and non-blocking notes for human review. Human review and
    every existing production, credential, migration, and deployment gate still
    apply; graph acceptance never authorizes production mutation.

Before every spawn or handoff, and on every blocker, FAIL, PASS, or Root
disposition, rewrite `STATE.md` to match the current node and next legal edge.
Keep its exactly five lines—Intent, Worktree, Current node, Next legal edge
(including the review round or critical recheck), Blocked by. Never run parallel
writers or allow subagents to spawn subagents; Root alone writes `contract.md`,
`acceptance.md`, and `STATE.md`; each child writes only its owned artifact;
checker and Security are the only concurrent review lanes. The parent may
inspect evidence while a subagent runs.

At every checker stage, derive changed executable paths from the final diff and
require observable, record-once-and-propagated failure evidence at each relevant
entrypoint, I/O, tool, or phase boundary. Missing instrumentation evidence or a
failure-boundary violation is blocking in review 1, review 2, and every critical
recheck; this is the explicit exception to the review-2 critical-only threshold,
which remains unchanged for unrelated findings.

The hook's leading literal assigned-worktree `cd` check is best-effort Bash
enforcement, not a complete shell sandbox: redirects and compound commands are
not fully inspectable. Keep role prompts and the path-specific `apply_patch`
guard as the boundary; do not add a graph runner, shell parser, dependency, or
other machinery to claim stronger enforcement.

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

- `.graph/contract.md`: Root-owned risk class, selected child profile,
  authoritative scope, and acceptance rules. Children may read but never write.
- `.graph/acceptance.md`: Root-owned disposition record with rationale and
  repair, accept, or block status. Acceptance cannot override critical findings
  or incomplete required evidence.
- `.graph/STATE.md`: exactly five lines—Intent, Worktree, Current node, Next
  legal edge, Blocked by.
- `.graph/explore.md`: question, owners/entrypoints, current behavior, files in
  scope, assumptions, falsifiers, out of scope, gaps.
- `.graph/research.md`: question, evidence and sources, relevant contracts,
  failure-boundary findings, recommendation, gaps.
- `.graph/checklist.md`: preconditions, numbered acceptance requirements,
  required commands and pass conditions, risk-focused checks, ponytail findings,
  blocking gaps.
- `.graph/change.md`: intent, files touched, assumptions accepted, commands
  run, instrumentation evidence/status for every changed executable path and
  relevant boundary, how to verify, what was not done.
- `.graph/verdict.md`: review round, PASS or FAIL, checks and evidence, broken
  assumptions, instrumentation evidence/status for every changed executable
  path and relevant boundary, ponytail findings, critical status, non-blocking
  human-review notes, and the required fix on FAIL. “Looks good” is not a
  verdict.
- `.graph/security-verdict.md`: Security's durable source-read-only review
  evidence, written only by the registered Security role; it is not deployment
  authority.

## Current-run truth

Use only the assigned worktree's `.graph/` artifacts to schedule the current
run. AgentMemory may supply background architecture, decisions, and pitfalls,
but never determines the current node.

Continue until:

- review 1 passes, or review 2 and any focused rechecks have no critical issues
- a blocking gap requires user input or authority
