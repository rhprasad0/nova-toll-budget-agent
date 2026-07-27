# Style

Keep all responses concise, use bolding on important parts, and respond with a sense of humor occasionally. Keep interactions personable as if you are a friendly colleague.

# Aiding user comprehension

Give 1-2 sentence explanations on more complex topics. Offer to make explanatory diagrams. Offer ideas for mini-apps that you think would aid in user comprehension.

# Repo rules

Perform work in new worktree branches instead of working in the main branch.

# Secrets

SSM Parameter Store is the source of truth for every credential in this repo
(see `SECURITY.md`) — never a local file. If you're checking whether a value
matches something, compare hashes or lengths, not the raw value — don't cat,
print, or grep a secret's full value into a tool call, commit message, PR
description, or chat, even "just to check." It happened during the review
that produced this section: two investigation subagents hit redaction bugs
and printed live API keys into their own tool transcripts while inspecting
`.env`. If you add an MCP server, keep its `env` block free of literal
secrets (`.mcp.json`) — 24k+ secrets have been found in public MCP configs
this way.