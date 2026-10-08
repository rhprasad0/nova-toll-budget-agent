# Billing cost dashboard

`/cost-dashboard` reads the public, version 1 `/costs.json` snapshot. The scheduled
publisher shares the report publisher's archive, but has its own Lambda and
execution role. It has no database or model permissions.

Development runs at **08:00 and 12:00 UTC** and combines its own AWS account's billing with
OpenAI organization-wide costs. OpenAI includes all environments, not just development.
Immediately after collecting AWS, development publishes
`https://dev.tollchat.ai/assets/costs-aws.json` before requesting OpenAI. This
independent version 1 feed uses scope `aws-development` and marks OpenAI
`not_configured`. Production runs at **09:00 and 13:00 UTC** and combines its own
AWS account, the validated AWS feed, and OpenAI organization costs.
Each account's cost publisher reads its account-local SSM SecureString
`/nova-toll/openai_billing_api_key` in `us-east-1`; it needs an OpenAI organization
admin key with cost-read access. For development, provision this in account
**903859731897**, using **SecureString** and **alias/aws/ssm**. Keep its value out
of chat, local files, Terraform, and application credentials. Only the cost role
receives parameter read and scoped decryption permission; delivery and planning
roles cannot read the key. Production consumes only development's AWS feed and
collects OpenAI directly once. Do not enable
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
and changes only its sanitized attempt status. This applies independently to
the AWS feed and each dashboard. A failed AWS feed write still allows a development
dashboard write. Production requires a successful AWS feed attempt, matching
requested dates, exact reconciliation, and publication and retrieval timestamps
no older than 48 hours. Development OpenAI failures can therefore retain its
dashboard total while production continues refreshing from the AWS feed.
Legacy development snapshots with
scope `aws-development` remain readable. When retained after a failed refresh,
they migrate to `aws-development+openai-organization` with OpenAI unavailable;
AWS values and the original publication time are preserved. With no prior snapshot, available
source subtotals remain visible. A publication older than 48 hours is marked
stale. Browser refresh errors retain the displayed valid data. No credentials,
account/resource/project IDs, raw provider errors, or chat content are published.

The shared HTTPS reader makes at most three attempts for HTTP 408, 429, 500, 502,
503, and 504, connection failures, and timeouts. Delays are 2 then 5 seconds; a
valid `Retry-After` overrides the delay, capped at 30 seconds. Every request has a
20-second timeout. Before a request or backoff, the reader reserves 60 seconds of
Lambda time for publication. Authentication errors, redirects, malformed responses,
and reconciliation failures are not retried. AWS SDK retries remain unchanged.

CloudWatch monitors terminal refresh failures and Lambda errors, with separate
development dashboard and AWS feed publication metrics. Success is logged only
after a successful snapshot write; writing retained data with a failed attempt
does not count. Freshness alarms evaluate `FILL(success, 0)` over 48 hourly
periods and require all 48 to lack success, treating missing data as breaching.
This handles sparse daily publications ([AWS metric math](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/using-metric-math.html)).
All billing alarms use the account's foundation alert topic, including development.
Request logs contain only source, attempt, exception type, and HTTP status;
terminal publication logs contain the snapshot, stage, and exception type.

## Authorized rollout

Push, PR creation, and deployment require the repository's usual authorization.
There is no database migration or application-agent change in this release.

1. Review and apply the account-local foundation IAM additions in
   `infra/costs-delivery.tf` through the existing foundation procedure before the
   application plan. They grant the existing planning/delivery roles access to
   the fixed cost resources, metric filters, and alarms, without granting access
   to the billing secret. Review the development publisher's exact
   `assets/costs-aws.json` S3 read/write and prefix listing permissions; production
   receives no access to that development bucket.
2. Deliver development through the existing saved-plan release gates. Wait for
   its scheduled run (or invoke the fixed cost Lambda during the authorized rollout).
   Verify `/cost-dashboard`, a direct route refresh, `/costs.json`, and
   `/assets/costs-aws.json` through public read-backs. Validate
   the real snapshot with `v2/lambdas/publisher/costs.py:validate_snapshot`, checking
   `development`, `aws-development+openai-organization`, a successful attempt,
   a new publication, current requested dates, and AWS service/environment
   reconciliations. Validate the AWS feed separately for scope `aws-development`,
   OpenAI `not_configured`, a successful attempt, current dates, a new publication,
   and AWS reconciliation. Require the Lambda response payload status to succeed, not
   just the invocation. Compare AWS daily amounts against the same account-filtered
   Cost Explorer request and OpenAI against the unfiltered organization Costs API
   for the same dates. Reconcile exact daily and month-to-date decimals and check
   browser labels, totals, and chart/table agreement. Separately confirm the next
   scheduled **08:00 and 12:00 UTC** refreshes; a manual invocation does not prove
   scheduling. Confirm all development billing alarms have actions enabled and
   target the foundation alert topic.
   Confirm the topic has a confirmed subscription. If its configured email
   subscription was restored, confirm AWS's email request before relying on alerts.
3. After development's AWS feed is valid, check production prerequisites
   **before preparing the production release**: account-local foundation
   permissions, the fixed SecureString's metadata and effective cost-role
   SSM/KMS access, a successful bounded account-filtered AWS billing request,
   valid OpenAI organization cost-read access, and development's successful AWS
   feed for the exact requested interval. Use authorized identities and
   sanitized results; parameter existence alone does not prove provider access.
   Stop on missing or denied access, incorrect account, failed development
   publication, or mismatched dates. Then use the protected saved-plan workflow
   and wait for or invoke the fixed production cost Lambda. Validate the public
   production snapshot and compare each source:
   production AWS against Cost Explorer, development AWS against the public AWS
   feed, and OpenAI against the unfiltered organization costs endpoint for
   the snapshot's exact UTC dates. Sum decimal strings, including credits;
   compare unrounded daily and month-to-date totals. Confirm the scheduled
   **09:00 and 13:00 UTC** publications and production alarm actions separately.
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

## Controlled inference benchmark

The inference section reads `/assets/costs-benchmark.json`, a manually refreshed
aggregate independent of `/costs.json`. It measures real Luna 6 calls with frozen
tool results: actor low, TollChat medium, and judges xhigh. These settings apply
only inside the benchmark process; application and eval defaults are unchanged.
The 12 existing cases run three times, sequentially, with a $2 total ceiling.
This cost-only sample does not establish evaluation reliability or public-chat
costs. The existing scored-evaluation calibration gates are unchanged.

From a clean, committed worktree's `v2/` directory, refresh with a new private
output directory:

```sh
AWS_PROFILE=nova-toll-dev uv run python -m eval.cost_benchmark \
  --output eval/private/costs-YYYYMMDD-HHMMSS
```

The command reads the application credential from development SSM directly into
memory. It needs no database access. It retains detailed usage and conversations
only under ignored `eval/private/`, then replaces the public aggregate and its
release byte pin after all 36 attempts have complete usage. A budget stop, missing
usage, or interrupted run retains the previous public aggregate. Review and ship
the updated aggregate and pin through the usual PR and release process.

Agent spend across all attempts, including measured failed calls, is divided by
completed assistant turns. A truncated or interrupted response is not a completed
turn; a completed refusal or unavailable answer is. Each role's conversation
average uses all attempted conversations. Cached reads and writes are separated
from uncached input; reasoning is already included in output. Pricing uses the
recorded standard rates and per-call long-context adjustments. The sample includes
its actual cache usage; it does not model a production traffic mix. Infrastructure
and tool execution are excluded, and these estimates are never added to billing.

See the [experiment journal](../eval/EXPERIMENT_JOURNAL.md) for measured results
and limitations. Public-chat attribution and issue #542 probe integration,
latency navigation, forecasting, and analytics remain follow-up work.

## Local checks

From `v2/`, run `uv run pytest lambdas/publisher/tests/test_costs.py
tests/test_cost_dashboard_release.py tests/test_cost_dashboard_release_gates.py`.
The checks include retries, outage isolation, retained data, sanitized logs,
publication-write failures, and exact feed and alarm boundaries.
The release test uses a credential-free
Terraform mock plan when the pinned provider is initialized locally. Build the
shared archive with `scripts/build_publisher_zip.sh` before its archive check.
Run `node tests/cost_dashboard_browser.cjs` with Playwright available to check
the deterministic fixtures, mobile layout, keyboard access, routes, and failure
states. No captured billing snapshots are test inputs.
Run `uv run pytest tests/test_cost_benchmark.py` for the credential-free benchmark
accounting, budget, and model-setting checks.
