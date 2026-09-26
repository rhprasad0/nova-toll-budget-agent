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

- Preserve `v2/eval/EXPERIMENT_JOURNAL.md`: it is important permanent experiment
  history. Do not delete, truncate, replace, or remove it during cleanup without
  Ryan's explicit approval; append new results and dated corrections.
- Keep `v2/eval/EXPERIMENT_JOURNAL.md` readable for people outside the project.
  Give each experiment a few concise, plain-language sentences covering its
  purpose, relevant versions, aggregate result, limitations, cost when relevant,
  and decision; retain useful figures and tables as-is. Cut repeated process
  narration, raw identifiers, and AI-sounding filler unless needed to verify a
  claim.
  Preserve material findings and chronology when condensing old entries.
- Do not add per-run documentation, review packets, full transcripts, event logs,
  raw reports, or copied run archives to commits or PRs unless Ryan explicitly
  requests publishing those artifacts.
- Keep granular experiment output in ignored `v2/eval/private/` or the existing
  private workflow artifact store. Keep only executable eval inputs, focused test
  fixtures, and evidence required by an existing release contract in source
  control. Prefer small synthetic regressions over dependencies on full runs.
- Keep READMEs and runbooks focused on current usage; link to the experiment
  journal instead of repeating experiment history. A temporary review-page
  request does not imply permission to commit the page or its underlying data.
- Do all code and content changes in `.worktrees/`, not on `main`.
- `main` is protected. Changes ship through a PR that passes CI.
- Run only tests that are relevant to the task at hand.
- Do not open a PR or push without user authorization.
- When authorized to open a PR: open it ready for review, never as draft.
- Do not request additional Codex GitHub reviews (`@codex review` or
  `@codex security review`) unless the user explicitly asks. Address existing
  feedback, then use required CI and human approvals as merge gates.

# Tools

- AWS and Context7 MCP: documentation lookup
- Exa: other search

# Coding agents

For a pre-release review, ask Codex to use `pre_release_reviewer`, defined in
`.codex/agents/pre_release_reviewer.toml`. Example: "Use pre_release_reviewer to
review candidate <SHA> against deployed production <SHA>, and recommend checks
that would catch production failures before rollout." Supply release/plan evidence
when available. The agent reviews and recommends; it does not deploy or act as an
automatic CI gate. Start a new Codex session in the checkout containing the agent.
This reviewer uses `gpt-6-astra` with `high` reasoning effort.

The Root model and reasoning effort remain selected by the host/user; do not pin
them in repository config.

TollChat's application agent stays on `gpt-6-luna`. Leave its model and prompt
unchanged unless the user explicitly requests an application-agent change.

# Secrets and delivery

- Deployed credentials live in SSM Parameter Store (`SECURITY.md`). Never a
  local secrets file.
- PRs use disposable migration validation only: the checks are credential-free,
  never mutate deployed databases or schemas, and never expose production
  deployment credentials.
- After merge, only human-reviewed backward-compatible development migrations
  may run through the protected exact-release delivery sequence: verify the
  artifact and checkout, create and gate one saved private plan, migrate under
  the fixed development role, re-assume the delivery role, and apply that exact
  plan. This is the protected `development` migration workflow. The fixed
  manual workflow remains main-only from `refs/heads/main` for approved recovery; both paths use the
  fixed development database, role, registered migration set, and sanitized
  evidence. Neither accepts arbitrary target or migration inputs.
- For production, the reviewed protected fixed-target
  `v2-production-migrations.yml` workflow may apply the registered migration set
  only through its bounded release, provenance, identity, private-connectivity,
  and database gates; it accepts no arbitrary target, SQL, or migration input.
  The reviewed Oracle migration
  `v2/db/migrations/030_upgrade_oracle_1_13_1_to_1_14_0.sql` remains the only
  manually authorized production migration and only by its bounded procedure in
  `v2/RUNBOOK.md`. Generic or future manual migrations are not authorized.
