# Security

TollChat runs inside private AWS networking. The public CloudFront and WAF edge
reaches an IAM-authenticated Lambda URL; the proxy reaches the private AgentCore
endpoint, and runtime database access uses narrowly scoped RDS IAM roles.

SSM Parameter Store is the source of truth for feed, OpenAI, Cloudflare, and
Tailscale credentials. Secrets must never be written to repository files,
Terraform variables, plans, logs, or build artifacts.

Shared production controls live in [`infra/`](infra/); application-specific
controls live in [`v2/infra/`](v2/infra/). Both use encrypted remote Terraform
state and least-privilege IAM policies. Report suspected credential exposure or
unauthorized access privately to the repository owner.
