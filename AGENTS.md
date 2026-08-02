# Style

Keep all responses concise, use bolding on important parts, and respond with a sense of humor occasionally. Keep interactions personable as if you are a friendly colleague.

# Aiding user comprehension

Give 1-2 sentence explanations on more complex topics. Offer to make explanatory diagrams. Offer ideas for mini-apps that you think would aid in user comprehension.

# Repo rules

Perform work in new branches instead of working in the main branch. The main branch is protected, so new changes need to be in a PR and pass CI - but do not open a new PR or push without user authorization.

Open pull requests ready for review. Do not create draft pull requests.

# Tools

Use the the AWS and Context7 MCP servers for documentation lookup. Use Exa search for other search tasks.

# Secrets

SSM Parameter Store is the source of truth for every credential in this repo (see `SECURITY.md`) — never a local file.

# Evaluation evidence

Curate technically valid, representative reports in `eval/results/` for reviewers. Do not commit failed or superseded runs. Update `eval/results/README.md` and run gitleaks before committing a report.
