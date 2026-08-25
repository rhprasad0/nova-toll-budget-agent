# Style

Keep all responses concise, use bolding on important parts, and respond with a sense of humor occasionally. Keep interactions personable as if you are a friendly colleague.

# Aiding user comprehension

Give 1-2 sentence explanations on more complex topics. Offer to make explanatory diagrams. Offer ideas for mini-apps that you think would aid in user comprehension.

# Repo rules

Create all worktrees inside the project-root `.worktrees/` directory, which must remain gitignored. Perform work there (for isolation from other coding agents) instead of working in the main branch. The main branch is protected, so new changes need to be in a PR and pass CI - but do not open a new PR or push without user authorization.

Open pull requests ready for review. Do not create draft pull requests.

Before opening a PR, complete both database migration checks below. Do not
treat the disposable check as a substitute for applying migrations to RDS.

1. Apply every migration newly added or still unapplied on the branch from its
   declared prior version in a disposable database, and verify the migrated
   schema matches the canonical bootstrap.
2. Using the `nova-toll` AWS profile, read the deployed schema versions from
   the live `nova-toll-db` RDS database, apply every pending repository
   migration in dependency order, and verify the deployed versions match the
   branch. Do not open the PR until the live migrations succeed.

# Repository boundaries

Keep application code, tests, evals, and application infrastructure under
`v2/`. Shared polling, storage, database, network, and security foundations live
under `infra/` and retain their existing Terraform backend.

# Tools

Use the the AWS and Context7 MCP servers for documentation lookup. Use Exa search for other search tasks.

# Secrets

SSM Parameter Store is the source of truth for deployed credentials (see
`SECURITY.md`) — never a local file.

# Evaluation evidence

Curate technically valid, representative reports in `v2/eval/results/` for
reviewers. Do not commit failed or superseded runs. Update the results index and
run gitleaks before committing a report.
