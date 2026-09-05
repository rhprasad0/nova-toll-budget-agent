# Purpose

TollChat.ai is a Strands/AgentCore reference implementation for practical agent
development and deployment. It is not a live end-user service.

Prefer the smallest design that clearly demonstrates the intended pattern.
Optimize for readability and teachability, not hypothetical scale or enterprise
flexibility. Do not add abstractions, configurability, or operational machinery
unless the user, an existing contract, security, or data safety requires it.

# Style

Keep responses concise. Bold the important parts. Be a friendly colleague; humor
is fine when it does not hide the answer.

On complex topics: 1–2 sentences, then offer a diagram or a small comprehension
app if it would actually help.

# Layout

- Application, tests, evals, and app infra: `v2/`
- Shared polling, storage, database, network, security: `infra/` (existing Terraform backend stays)
- Agent isolation: project-root `.worktrees/` (must stay gitignored)

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

# Project graph hook

The project graph uses a synchronous, fail-closed Codex hook for the guarded
`explorer`, `pre_checker`, `builder`, and `checker` roles. A child must report
the native `SubagentStart` UUID to the parent, wait for the parent to register
that UUID to its assigned worktree, and wait for the registration acknowledgement
before using tools. The parent and `security_reviewer` are outside this guard.

Before graph work, ensure this source is present in the active trusted checkout,
open `/hooks`, and trust both the `SubagentStart` and `PreToolUse` project-hook
entries. Restart Codex or start a new child after activation so the hooks load.
The parent needs write access to the shared
`.worktrees/.graph-assignments/` registry; when a workspace-write worktree
limits that access, grant only that registry directory. The parent may use
`--dangerously-bypass-hook-trust` only for the approved disposable runtime
smoke test. See the [Codex hook documentation](https://learn.chatgpt.com/docs/hooks.md).
This is a best-effort accidental-edit boundary, not a shell sandbox: later shell
commands, scripts, redirects, and `git -C` destinations are outside its parser
and remain covered by the declared sandbox and permissions boundary.

# Coding agents

Use GPT-6 Astra (`gpt-6-astra`) for the parent coding agent. Keep project-graph
nodes and specialist reviewers on their existing models, reasoning efforts, and
instructions in `.codex/agents/`.

TollChat's application agent stays on `gpt-5.6-luna`. Leave its model and prompt
unchanged unless the user explicitly requests an application-agent change.

# Secrets and delivery

- Deployed credentials live in SSM Parameter Store (`SECURITY.md`). Never a
  local secrets file.
- PRs use disposable migration validation only: never mutate deployed databases or schemas, and never expose production deployment credentials.
- Only the reviewed, explicitly authorized Oracle migration
  `v2/db/migrations/030_upgrade_oracle_1_13_1_to_1_14_0.sql` may be applied to
  a deployed database, and only by following its bounded procedure in
  `v2/RUNBOOK.md`. Generic or future manual migrations are not authorized;
  other schema-changing work remains blocked pending approved deployment
  automation.

# Eval graph

Use [.agents/skills/eval-graph/SKILL.md](.agents/skills/eval-graph/SKILL.md)
for `$eval-graph`, eval loops, pinning a case, fixture runs, and pass^k gates.
The eval root is `v2/eval/`; preserve the existing harness and corpus.
Astra medium orchestrates; case_miner, eval_runner, eval_reviewer, and
eval_fixer use Luna medium and the existing native-ID/worktree registry.
Keep one writer; grade.sh and compare.sh own the metric. The critic never
patches, and gate never starts a fixer. Require sealed runtime access for
runner inputs; the worktree hook does not isolate reads. Humans control
correctness, sealed held-out execution, case acceptance, and merge.
Do not start trials merely by installing or editing the graph.
