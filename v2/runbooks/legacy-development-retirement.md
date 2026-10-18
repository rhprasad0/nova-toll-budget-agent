# Legacy development retirement (#333) [historical, completed]

Issue #333 removed the superseded development stack from production account
`920534282028` after development moved to its own account. The bucket archive
and Terraform destroy ran on 2026-09-05 and 2026-09-06; the legacy state key now
holds an empty state.

These facts remain operational:

- The Bedrock guardrail `nova-toll-v2-agent-dev` and its guardrail version were
  intentionally retained (`prevent_destroy`/`skip_destroy`). On 2026-10-18 the
  guardrail was the only production-account resource still tagged
  `environment=development`.
- The old ACM validation record was intentionally left in Cloudflare.
- The archived bucket objects, the pre-destroy state snapshot and the archive
  manifest are in `s3://nova-toll-tfstate-920534282028/nova-toll/v2/development/retirement-archives/`.

The final step, dropping `nova_toll_development` and its `_development` roles
from production `nova-toll-db`, is not visible through AWS APIs, so the
2026-10-18 check could not confirm it; the retirement tooling was removed by
decision on that date.

**Do not run the historical procedure.** The runbook, retirement scripts and
inventory remain in
[Git history before this cleanup](https://github.com/rhprasad0/nova-toll-budget-agent/blob/ed784c8e/v2/runbooks/legacy-development-retirement.md).
