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

Use `explorer` → `pre_checker` → `builder` → `checker` only when the change is
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
intent → explorer → pre-checker → builder → checker → PASS | FAIL→builder | human
```

Legal edges:

1. Explorer writes `.graph/explore.md`. Pre-checker does not start without it.
2. Pre-checker writes `.graph/checklist.md`. If it has blocking gaps, return to
   the original explorer; builder starts only after a non-blocking checklist.
3. Builder writes code in the assigned worktree and `.graph/change.md` after
   reading `explore.md` and `checklist.md`.
4. Checker starts with `fork_turns: "none"`, reads the worktree + artifacts,
   writes `.graph/verdict.md`, and does not edit application code.
5. FAIL → the original builder with `verdict.md` as the spec. At most two
   fix loops, then stop for the user.
6. PASS is the only path to “done.”
7. No parallel writers. Fan-out explorers, pre-checkers, or checkers only.
8. No subagents of subagents.
9. Before every spawn or handoff, and on every blocker, FAIL, or PASS, rewrite
   `.graph/STATE.md` to match the current node and next legal edge.

## Parent checklist

1. Create or reuse an isolated path under `.worktrees/` and record it in the
   worktree's `.graph/STATE.md`.
2. Update `STATE.md`, then spawn `explorer` with `fork_turns: "none"`, the
   intent, and absolute worktree path. Wait.
3. If `explore.md` has blocking gaps, update `STATE.md`, stop, and ask the user.
4. Update `STATE.md`, then spawn `pre_checker` with `fork_turns: "none"`,
   explore.md, and worktree. If its checklist has blocking gaps, return the
   worktree-local gaps to the original explorer thread, then spawn a new
   `pre_checker` with `fork_turns: "none"` after repair.
5. Update `STATE.md`, then spawn `builder` with `fork_turns: "none"`,
   explore.md, checklist.md, and worktree. One writer.
6. Update `STATE.md`, then spawn `checker` with `fork_turns: "none"`. Do not
   reuse the builder thread.
7. On FAIL, update `STATE.md` and return `.graph/verdict.md` to the original
   builder thread. After every builder repair, re-check with a new checker
   using `fork_turns: "none"`; stop for the user after two failed fix loops.
8. On PASS, update `STATE.md`, then summarize files, checks run, and leftover
   risk.

## Artifacts

All artifact paths below are relative to the assigned worktree.

`.graph/STATE.md` — five lines only: Intent, Worktree, Current node, Next legal
edge, Blocked by.

`.graph/explore.md` — question, owners/entrypoints, current behavior, files in
scope, assumptions, falsifiers, out of scope, gaps.

`.graph/checklist.md` — preconditions, numbered acceptance requirements,
required commands and pass conditions, risk-focused checks, blocking gaps.

`.graph/change.md` — intent, files touched, assumptions accepted, commands run,
how to verify, what was not done.

`.graph/verdict.md` — PASS or FAIL, what was checked, evidence, broken
assumptions, required fix if FAIL. “Looks good” is not a verdict.

# Repo rules

- Do all code and content changes in `.worktrees/`, not on `main`.
- `main` is protected. Changes ship through a PR that passes CI.
- Do not open a PR or push without user authorization.
- When authorized to open a PR: open it ready for review, never as draft.
- Do not request additional Codex GitHub reviews (`@codex review` or
  `@codex security review`) unless the user explicitly asks. Address existing
  feedback, then use required CI and human approvals as merge gates.

# Tools

- AWS and Context7 MCP: documentation lookup
- Exa: other search

# Secrets and delivery

- Deployed credentials live in SSM Parameter Store (`SECURITY.md`). Never a
  local secrets file.
- PRs use disposable migration validation only: never mutate deployed databases or schemas, and never expose production deployment credentials.
- Schema-changing work is not deployable until approved deployed-migration
  automation exists.
