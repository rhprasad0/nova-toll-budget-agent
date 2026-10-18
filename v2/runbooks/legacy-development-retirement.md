# Legacy development retirement (#333) [historical, completed]

Issue #333 removed the superseded development stack from production account
`920534282028` after development moved to its own account. The bucket archive
and Terraform destroy ran on 2026-09-05 and 2026-09-06; the legacy state key now
holds an empty state.

Two facts remain operational:

- The Bedrock guardrail `nova-toll-v2-agent-dev` was intentionally retained
  (`prevent_destroy`). It is the only production-account resource still tagged
  `environment=development`.
- The archived bucket objects, the pre-destroy state snapshot and the archive
  manifest are in `s3://nova-toll-tfstate-920534282028/nova-toll/v2/development/retirement-archives/`.

**Do not run the historical procedure.** The runbook, retirement scripts and
inventory remain in
[Git history before this cleanup](https://github.com/rhprasad0/nova-toll-budget-agent/blob/ed784c8e/v2/runbooks/legacy-development-retirement.md).
