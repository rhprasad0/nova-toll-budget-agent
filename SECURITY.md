# Security

TollChat runs inside private AWS networking. The public CloudFront and WAF edge
reaches an IAM-authenticated Lambda URL; the proxy reaches the private AgentCore
endpoint, and runtime database access uses narrowly scoped RDS IAM roles.

SSM Parameter Store is the source of truth for feed, OpenAI, OpenWeb Ninja,
Cloudflare, and Tailscale credentials. Secrets must never be written to repository files,
Terraform variables, plans, logs, or build artifacts.

Two credentials are kept outside SSM, as plain files on the factory's thin client
(see [`v2/plans/FACTORY-SPEC.md`](v2/plans/FACTORY-SPEC.md)): the private key of its
IAM Roles Anywhere certificate, which is what unlocks SSM, and a fine-grained GitHub
token for this repository with no Workflows permission. The certificate works only
for the development `tollchat-factory` role and expires within a year; revoke it by
disabling the `tollchat-factory` trust anchor.

Shared production controls live in [`infra/`](infra/); application-specific
controls live in [`v2/infra/`](v2/infra/). Both use encrypted remote Terraform
state and least-privilege IAM policies. Report suspected credential exposure or
unauthorized access privately to the repository owner.
