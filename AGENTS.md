# Purpose

TollChat.ai is a Strands/AgentCore reference implementation demonstrating practical agent development and deployment without unnecessary ceremony. It is not intended to operate as a live service for end users.

# Style

Keep all responses concise, use bolding on important parts, and respond with a sense of humor occasionally. Keep interactions personable as if you are a friendly colleague.

# Aiding user comprehension

Give 1-2 sentence explanations on more complex topics. Offer to make explanatory diagrams. Offer ideas for mini-apps that you think would aid in user comprehension.

# Repo rules

Create all worktrees inside the project-root `.worktrees/` directory, which must remain gitignored. Perform work there (for isolation from other coding agents) instead of working in the main branch. The main branch is protected, so new changes need to be in a PR and pass CI - but do not open a new PR or push without user authorization.

Open pull requests ready for review. Do not create draft pull requests.

# Repository boundaries

Keep application code, tests, evals, and application infrastructure under
`v2/`. Shared polling, storage, database, network, and security foundations live
under `infra/` and retain their existing Terraform backend.

# Tools

Use the the AWS and Context7 MCP servers for documentation lookup. Use Exa search for other search tasks.

# Optional subagent workflow

Use `code_explorer` → `implementer` → `verifier` only when the user explicitly requests this workflow; ordinary tasks must not infer it. The parent assigns an isolated `.worktrees/` path, forwards the explorer brief and path to the implementer, then forwards any verifier findings to the implementer and re-verifies the resulting diff.

# Secrets

SSM Parameter Store is the source of truth for deployed credentials (see
`SECURITY.md`) — never a local file.
