# Purpose

TollChat.ai is a Strands/AgentCore reference implementation for practical agent
development and deployment. It is not a live end-user service.

# Style

Keep responses concise. Bold the important parts. Be a friendly colleague; humor
is fine when it does not hide the answer.

On complex topics: 1–2 sentences, then offer a diagram or a small comprehension
app if it would actually help.

# Layout

- Application, tests, evals, and app infra: `v2/`
- Shared polling, storage, database, network, security: `infra/` (existing Terraform backend stays)
- Agent isolation: project-root `.worktrees/` (must stay gitignored)
- Graph handoffs: `.graph/` inside the assigned worktree (must stay gitignored;
  never store secrets)

# Memory vs graph

AgentMemory holds durable project knowledge across sessions.

It is not the scheduler. Do not recall “similar” runs to decide the current
node. Current-run truth lives in the assigned worktree's `.graph/` files. Recall
AgentMemory only for background (architecture, past decisions, known pitfalls).

# When to use the graph

Use `code_explorer` → `implementer` → `verifier` only when the change is
**non-trivial**. A change is non-trivial when its scope or risk warrants
independent exploration and verification, for example when it:

- touches more than one area (`v2/` + `infra/`, agent loop + tools, schema + app)
- changes a high-risk runtime path, eval strategy, or deployment shape
- requires repo-wide discovery or independent verification to establish correctness
- is explicitly requested by the user

Skip the graph for questions, docs-only edits, mechanical changes, and localized
low-risk fixes. The parent handles those directly.

# Graph

Parent orchestrates only. Parent does not explore the repo in depth, implement,
or self-verify.

```
intent → explorer → implementer → verifier → PASS | FAIL→implementer | human
```

Legal edges:

1. Explorer writes `.graph/explore.md`. Implementer does not start without it.
2. Implementer writes code in the assigned worktree and `.graph/change.md`.
3. Verifier starts in a **fresh thread**, reads the worktree + artifacts, writes
   `.graph/verdict.md`. Verifier does not edit application code.
4. FAIL → the original implementer with `verdict.md` as the spec. At most two
   fix loops, then stop for the user.
5. PASS is the only path to “done.”
6. No parallel writers. Fan-out explorers or verifiers only.
7. No subagents of subagents.

## Parent checklist

1. Create or reuse an isolated path under `.worktrees/` and record it in the
   worktree's `.graph/STATE.md`.
2. Spawn `code_explorer` with the intent and worktree path. Wait.
3. If `explore.md` has blocking gaps, stop and ask the user.
4. Spawn `implementer` with explore.md + worktree. One writer.
5. Spawn `verifier` fresh. Do not reuse the implementer thread.
6. On FAIL, return `verdict.md` to the original implementer. Re-verify in a
   fresh verifier thread.
7. On PASS, summarize files, checks run, and leftover risk.

## Artifacts

All artifact paths below are relative to the assigned worktree.

`.graph/STATE.md` — five lines only: Intent, Worktree, Current node, Next legal
edge, Blocked by.

`.graph/explore.md` — question, owners/entrypoints, current behavior, files in
scope, assumptions, falsifiers, out of scope, gaps.

`.graph/change.md` — intent, files touched, assumptions accepted, commands run,
how to verify, what was not done.

`.graph/verdict.md` — PASS or FAIL, what was checked, evidence, broken
assumptions, required fix if FAIL. “Looks good” is not a verdict.

# Repo rules

- Do all code and content changes in `.worktrees/`, not on `main`.
- `main` is protected. Changes ship through a PR that passes CI.
- Do not open a PR or push without user authorization.
- When authorized to open a PR: open it ready for review, never as draft.

# Tools

- AWS and Context7 MCP: documentation lookup
- Exa: other search

# Secrets and delivery

- Deployed credentials live in SSM Parameter Store (`SECURITY.md`). Never a
  local secrets file.
- PRs may use disposable migration validation only.
- Never mutate deployed databases or schemas.
- Never expose production deployment credentials.
- Schema-changing work is not deployable until approved deployed-migration
  automation exists.
