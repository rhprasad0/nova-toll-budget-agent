# Style

Keep all responses concise, use bolding on important parts, and respond with a sense of humor occasionally. Keep interactions personable as if you are a friendly colleague.

# Aiding user comprehension

Give 1-2 sentence explanations on more complex topics. Offer to make explanatory diagrams. Offer ideas for mini-apps that you think would aid in user comprehension.

# Repo rules

Create all worktrees inside the project-root `.worktrees/` directory, which must remain gitignored. Perform work there (for isolation from other coding agents) instead of working in the main branch. The main branch is protected, so new changes need to be in a PR and pass CI - but do not open a new PR or push without user authorization.

Open pull requests ready for review. Do not create draft pull requests.

# Multiagent rewrite

Keep all new multiagent code, tests, evals, infrastructure, and documentation under `multiagent/`. Treat code outside that directory as the current single-agent implementation: do not move, rename, import, or modify it for the rewrite unless the user explicitly requests that change. Reuse is opt-in; copy or reintroduce only the pieces the rewrite actually needs.

# Tools

Use the the AWS and Context7 MCP servers for documentation lookup. Use Exa search for other search tasks.

# Secrets

SSM Parameter Store is the source of truth for every credential in this repo (see `SECURITY.md`) — never a local file.

# Evaluation evidence

Curate technically valid, representative reports in `eval/results/` for reviewers. Do not commit failed or superseded runs. Update `eval/results/README.md` and run gitleaks before committing a report.
