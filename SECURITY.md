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
for the development `tollchat-factory` role and expires within a year. The key of
the CA that signs it stays on the owner's workstation; it can issue a new factory
certificate, so it is more powerful than the certificate's own key. To revoke the certificate, set
`enabled = false` on the trust anchor in `infra/factory.tf` and apply; credentials
already issued last up to an hour.

The Managed Agents factory (see [`v2/plans/FACTORY-PLAN.md`](v2/plans/FACTORY-PLAN.md))
keeps two more credentials outside SSM. The private key of the `tollchat-factory`
GitHub App is a secret of the `factory` GitHub environment, which only `main` may
deploy from; the App may write contents, issues and pull requests in this
repository only, and has no Workflows permission. The installation tokens minted
from it last an hour and are held in a Claude Managed Agents vault, which swaps a
placeholder for the token at the sandbox's network edge. GitHub Actions holds no
Anthropic key: it exchanges its own identity token for a short-lived one. To revoke
the App, delete its private key in the App's settings, or uninstall it.

Shared production controls live in [`infra/`](infra/); application-specific
controls live in [`v2/infra/`](v2/infra/). Both use encrypted remote Terraform
state and least-privilege IAM policies. Report suspected credential exposure or
unauthorized access privately to the repository owner.
