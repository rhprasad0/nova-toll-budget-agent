# Billing cost dashboard

`/cost-dashboard` reads the public, version 1 `/costs.json` snapshot. The scheduled
publisher shares the report publisher's archive, but has its own Lambda and
execution role. It has no database or model permissions.

Development runs at **08:17 and 12:17 UTC** and combines its own AWS account's billing with
OpenAI organization-wide costs. OpenAI includes all environments, not just development.
Immediately after collecting AWS, development publishes
`https://dev.tollchat.ai/assets/costs-aws.json` before requesting OpenAI. This
independent version 1 feed uses scope `aws-development` and marks OpenAI
`not_configured`. Production runs at **09:17 and 13:17 UTC** and combines its own
AWS account, the validated AWS feed, and OpenAI organization costs.
Each account's cost publisher reads its account-local SSM SecureString
`/nova-toll/openai_billing_api_key` in `us-east-1`; it needs an OpenAI organization
admin key with cost-read access. For development, provision this in account
**903859731897**, using **SecureString** and **alias/aws/ssm**. Keep its value out
of chat, local files, Terraform, and application credentials. Only the cost role
receives parameter read and scoped decryption permission; delivery and planning
roles cannot read the key. Production consumes only development's AWS feed and
collects OpenAI directly once. Do not enable Cost Explorer.

Keep both schedules off the hour: OpenAI's costs endpoint has returned HTTP 429
to on-the-hour refreshes. See the [experiment journal](../eval/journal/2026-10-12.md)
for the evidence.

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
Request failure logs include source, attempt, exception type, and HTTP status.
OpenAI failures also include allowlisted error codes/types, validated request IDs,
request-limit/remaining/reset headers, `Retry-After`, and a response-body category.
Error-body inspection is limited to 16 KiB and skips reads that would consume the
publication reserve. Unknown or unsafe fields use fixed markers; raw bodies,
provider messages, credentials, and organization/project identifiers are never
logged. These diagnostics remain in private CloudWatch logs, outside public snapshots.
Retry logs record the selected delay after the time-budget check; stop logs
distinguish permanent failures, exhausted attempts, and insufficient time.
Compare the server's `Retry-After` with the selected delay when diagnosing 429s;
the existing 30-second delay cap remains in effect. Use the error code to separate
throttling from quota/spend failures and retain the request ID for provider support.
A successful manual refresh does not explain an earlier scheduled failure.
Terminal publication logs contain the snapshot, stage, and exception type.

## Verify after a billing change

Billing resources and public routes are shared and become active during release
preparation, before chat promotion; chat checks and chat recovery neither prove
nor undo billing publication. After delivering a billing change:

1. Wait for or invoke the fixed cost Lambda, and require a **new successful
   attempt and publication** in the response payload, not retained data.
2. Read back `/cost-dashboard`, `/costs.json` and (development)
   `/assets/costs-aws.json`, and validate each with
   `v2/lambdas/publisher/costs.py:validate_snapshot`.
3. Reconcile exact daily and month-to-date decimals: AWS against the same
   account-filtered Cost Explorer request, OpenAI against the unfiltered
   organization Costs API, and (production) development AWS against the feed.
4. Confirm the next scheduled refreshes separately, and that billing alarms have
   actions enabled on the foundation alert topic with a confirmed subscription.

Production prerequisites (foundation permissions, the SecureString's cost-role
SSM/KMS access, a bounded AWS billing request, OpenAI cost-read access, and a
valid development feed for the same interval) must pass before preparing a
production release that changes billing.

## Controlled inference benchmark

The inference section reads `/assets/costs-benchmark.json`, a frozen
aggregate independent of `/costs.json`. It measures real Luna 6 calls with frozen
tool results: actor low, TollChat medium, and judges xhigh. These settings apply
only inside the benchmark process; application and eval defaults are unchanged.
The 12 existing cases run three times, sequentially, with a $2 total ceiling.
This cost-only sample does not establish evaluation reliability or public-chat
costs. The existing scored-evaluation calibration gates are unchanged.

The aggregate is frozen at its release byte pin in
`v2/scripts/cost_dashboard_release.py`. The `eval.cost_benchmark` runner was
retired because its fixed case selection needs an unavailable annual-interpretation
case, which the active training split no longer has; recover it from Git history
if a refresh is ever needed.

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
