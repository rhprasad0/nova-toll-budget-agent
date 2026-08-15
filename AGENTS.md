# Style

Keep all responses concise, use bolding on important parts, and respond with a sense of humor occasionally. Keep interactions personable as if you are a friendly colleague.

# Aiding user comprehension

Give 1-2 sentence explanations on more complex topics. Offer to make explanatory diagrams. Offer ideas for mini-apps that you think would aid in user comprehension.

# Repo rules

Create all worktrees inside the project-root `.worktrees/` directory, which must remain gitignored. Perform work there (for isolation from other coding agents) instead of working in the main branch. The main branch is protected, so new changes need to be in a PR and pass CI - but do not open a new PR or push without user authorization.

Open pull requests ready for review. Do not create draft pull requests.

# Agent rewrite

The complete original product lives under `single-agent/`; preserve its behavior unless the user explicitly requests a change there. Keep all rewrite code, tests, evals, infrastructure, and documentation under `rewrite/`. The rewrite has no compatibility contract with the original product: reuse is opt-in, so copy or reintroduce only the pieces it actually needs.

# Tools

Use the the AWS and Context7 MCP servers for documentation lookup. Use Exa search for other search tasks.

# Secrets

SSM Parameter Store is the source of truth for every credential in the deployed single-agent system (see `single-agent/SECURITY.md`) — never a local file.

# Evaluation evidence

Curate technically valid, representative single-agent reports in `single-agent/eval/results/` for reviewers. Do not commit failed or superseded runs. Update `single-agent/eval/results/README.md` and run gitleaks before committing a report.
