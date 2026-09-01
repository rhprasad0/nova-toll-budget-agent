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
