# Billing cost dashboard

`/cost-dashboard` reads the public, version 1 `/costs.json` snapshot. The daily
publisher shares the report publisher's archive, but has its own Lambda and
execution role. It has no database or model permissions.

Development runs at 08:00 UTC and combines its own AWS account's billing with
OpenAI organization-wide costs. OpenAI includes all environments, not just development.
Production runs at 09:00 UTC and combines its own AWS account, the validated
`https://dev.tollchat.ai/costs.json` aggregate, and OpenAI organization costs.
Each account's cost publisher reads its account-local SSM SecureString
`/nova-toll/openai_billing_api_key` in `us-east-1`; it needs an OpenAI organization
admin key with cost-read access. For development, provision this in account
**903859731897**, using **SecureString** and **alias/aws/ssm**. Keep its value out
of chat, local files, Terraform, and application credentials. Only the cost role
receives parameter read and scoped decryption permission; delivery and planning
roles cannot read the key. Production consumes only the AWS component of
development's snapshot and collects OpenAI directly once. Do not enable
Cost Explorer as part of this release.

The requested interval is the union of month-to-date and the last 30 completed
UTC days, ending before today. AWS uses account-filtered `UnblendedCost`; OpenAI
uses unfiltered organization costs. Signed decimal strings preserve adjustments
and sub-cent charges. AWS-hosted inference is counted inside AWS once. AWS
environment allocation uses the `environment` cost allocation tag with values
`production`, `development`, or `shared`; missing and other values remain
Unallocated. If that billing tag is inactive, totals still include those charges.
Unrecognized AWS service labels are combined into Other AWS services.

These are provisional billing observations. Requested coverage, source retrieval,
and publication timestamps are separate; neither provider supplies a finalized
through date here. An empty provider bucket is zero; an omitted day or non-USD
amount makes that source unavailable. Production shows a combined total only
when all three sources reconcile for the same periods and USD. Development
requires its AWS and OpenAI sources to reconcile for matching periods and USD.

A failed attempt preserves the previous valid snapshot and its publication time,
and changes only its sanitized attempt status. Legacy development snapshots with
scope `aws-development` remain readable. When retained after a failed refresh,
they migrate to `aws-development+openai-organization` with OpenAI unavailable;
AWS values and the original publication time are preserved. With no prior snapshot, available
source subtotals remain visible. A publication older than 48 hours is marked
stale. Browser refresh errors retain the displayed valid data. No credentials,
account/resource/project IDs, raw provider errors, or chat content are published.

## Authorized rollout

Push, PR creation, and deployment require the repository's usual authorization.
There is no database migration or application-agent change in this release.

1. Review and apply the account-local foundation IAM additions in
   `infra/costs-delivery.tf` through the existing foundation procedure before the
   application plan. They grant the existing planning/delivery roles access to
   the fixed cost resources, without granting access to the billing secret.
2. Deliver development through the existing saved-plan release gates. Wait for
   its daily run (or invoke the fixed cost Lambda during the authorized rollout).
   Verify `/cost-dashboard`, a direct route refresh, and `/costs.json`. Validate
   the real snapshot with `publisher/costs.py:validate_snapshot`, checking
   `development`, `aws-development+openai-organization`, a successful attempt,
   a new publication, current requested dates, and AWS service/environment
   reconciliations. Require the Lambda response payload status to succeed, not
   just the invocation. Compare AWS daily amounts against the same account-filtered
   Cost Explorer request and OpenAI against the unfiltered organization Costs API
   for the same dates. Reconcile exact daily and month-to-date decimals and check
   browser labels, totals, and chart/table agreement. Separately confirm the next
   scheduled 08:00 UTC refresh; a manual invocation does not prove scheduling.
3. After development's aggregate is valid, check production prerequisites
   **before preparing the production release**: account-local foundation
   permissions, the fixed SecureString's metadata and effective cost-role
   SSM/KMS access, a successful bounded account-filtered AWS billing request,
   valid OpenAI organization cost-read access, and development's successful
   snapshot for the exact requested interval. Use authorized identities and
   sanitized results; parameter existence alone does not prove provider access.
   Stop on missing or denied access, incorrect account, failed development
   publication, or mismatched dates. Then use the protected saved-plan workflow
   and wait for or invoke the fixed production cost Lambda. Validate the public
   production snapshot and compare each source:
   production AWS against Cost Explorer, development AWS against the dev public
   aggregate, and OpenAI against the unfiltered organization costs endpoint for
   the snapshot's exact UTC dates. Sum decimal strings, including credits;
   compare unrounded daily and month-to-date totals.
4. Verify both deployment labels, Cost navigation, public route refreshes, and
   the publication/attempt timestamps. A failed source must leave the combined
   total unavailable on a first run, or preserve the last valid publication on
   later runs. Do not interpret a preserved snapshot as a successful refresh.

Billing resources and public routes are shared and become active during release
preparation, before chat promotion. Existing chat candidate checks do not prove
billing publication works. The first real production publication check is
post-exposure verification unless a separately authorized rehearsal proves it
before preparation. Lambda invocation success is insufficient: require a new
successful snapshot attempt and publication, not retained data. Chat routing
recovery does not undo billing resources or snapshots; retain valid data and
correct billing failures through the reviewed release path.

Inference collection and remaining issue #543 requirements stay open. Issue
#542 probe integration, latency navigation, forecasting, and analytics are follow-up
work.

## Local checks

From `v2/`, run `uv run pytest lambdas/publisher/tests/test_costs.py
tests/test_cost_dashboard_release.py`. The release test uses a credential-free
Terraform mock plan when the pinned provider is initialized locally. Build the
shared archive with `scripts/build_publisher_zip.sh` before its archive check.
Run `node tests/cost_dashboard_browser.cjs` with Playwright available to check
the deterministic fixtures, mobile layout, keyboard access, routes, and failure
states. No captured billing snapshots are test inputs.
