### Development foundation handoff (#330; no application release) [historical, superseded]

Issue #330 described an initial development foundation bootstrap in two stages:
review a private copied Terraform root and binary plan, then apply that exact
plan and migrate its local state to the account-local encrypted backend after
separate approval. It kept application release and route activation in the
follow-on work for #331 and #332; #333 owns legacy cleanup and replacement.
Route activation required a non-overlapping VPC and an environment-specific ACL identity.

The procedure kept the production Budget recipient in temporary private inputs,
the approved private plan, and encrypted state. It required exact resource and
account checks, retained failure evidence privately, and stopped on ambiguous
apply or migration results.

**Do not run the historical procedure.** Use the
[current #327/#333 replacement handoff](development-foundation-replacement.md).
The original shell procedure remains in
[Git history before this cleanup](https://github.com/rhprasad0/nova-toll-budget-agent/blob/e2b7d4b5514ce3f0228d2556ab197f0c1c38ec1a/v2/runbooks/development-foundation-330-archive.md).
