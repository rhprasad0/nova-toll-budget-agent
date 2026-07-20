# nova-toll-budget-agent

This repo has an isolated `agentmemory` MCP server wired up (see `.mcp.json`) —
a project-fenced continuity/memory daemon dedicated to this repo, separate
from the global `self-hosted-honcho` memory server. Prefer `agentmemory` for
memory operations in this project.
