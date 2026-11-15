# AgentCore deployment

The [billing cost dashboard runbook](runbooks/cost-dashboard.md) covers its
account scopes, failure behavior, and development-first rollout checks.

Trusted development planning runs automatically in PR and merge-queue CI. Its
reusable plan validates the event-derived candidate and runs a read-only
Terraform plan in the reviewer-free `development-plan` environment; it never
applies Terraform. Development application delivery does not run on merge. It
delivers the tip of `main` nightly at 08:17 UTC, or on demand with
`gh workflow run v2-development-delivery.yml --ref main`. It uses exact CI
admission, one saved plan, fixed development migrations, application apply, and
readiness gates. Workflow-level concurrency runs one delivery at a time; a newer
pending run replaces an older pending one. GitHub disables schedules in a public
repository after 60 days without activity; re-enable the workflow if that happens.

The PR plan keeps Terraform and its checker on trusted `main`. It stages the
candidate's `public-report-routes.js` as data only after checking its digest
against the candidate manifest and binding that manifest to the commit and run.
The development validator permits the exact legacy report-routing code to be
replaced by the reviewed relative redirects on the fixed development function;
it still rejects the old code as a proposed value and all production identities.
Changes to the trusted workflow or validator take effect only after they reach
`main`. A PR containing such a repair cannot activate its own privileged checker;
rerunning the unchanged trusted baseline will still fail and grants no bypass of
the required check.

The `development-plan` environment remains reviewer-free with its custom
`refs/pull/*/merge`, `gh-readonly-queue/main/*`, and `main` branch policies.
The `development` environment remains reviewer-free with its `main` branch
policy. Production and `production-foundation-dns` remain reviewer-protected.

The secret-bearing manual
`.github/workflows/v2-development-connectivity-verification.yml` and
`.github/workflows/v2-development-migrations.yml` workflows remain
`workflow_dispatch`-only and require this exact job-level predicate:
`github.ref == 'refs/heads/main' && github.actor_id == '91573985' && github.triggering_actor == github.actor`.
Only reruns initiated by that original actor may reach the
development environment credentials. This owner-ID gate is separate from the
reviewer-free `development` environment and does not change the nightly
delivery path. Its credentialed deploy job requires
this exact predicate:
`vars.DEVELOPMENT_DELIVERY_ENABLED == 'true' && github.triggering_actor == github.actor`,
without restricting scheduled or dispatched `main` runs by owner ID.

To stop development delivery, first delete that repository variable (or set it to
literal `false`) with
`gh variable delete DEVELOPMENT_DELIVERY_ENABLED --repo rhprasad0/nova-toll-budget-agent`
and confirm a later delivery run is skipped without an OIDC request. Only then
disable the development route or rotate its Tailscale OAuth clients, stored in
the `development` environment: `TS_DEVELOPMENT_OAUTH_CLIENT_ID`/`_SECRET`
(scope `auth_keys`, tag `tag:ci-development`, used by the Tailscale action) and
`TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID`/`_SECRET` (only `devices:core:read`,
`devices:routes:read` and `devices:routes`, used by the route helper). Neither
step touches production.

## Delivery contract and production baseline

PRs use disposable PostGIS migration validation only; the checks are
credential-free and never access or mutate deployed databases or schemas. The
nightly delivery path is separate from the explicit manual development
migration workflow, which may be dispatched from `refs/heads/main` for the
fixed development target and accepts no arbitrary target or migration-path
inputs. See the [protected development migration workflow](#protected-development-migration-workflow-305-slice-3)
for its foundation, bootstrap, identity, and evidence gates. Production uses
the reviewer-protected reusable delivery job from `main`. After the separately
reviewed blue-green bootstrap, it stores a gated preparation plan in the private
versioned state bucket's `plans/` prefix and verifies its immutable
version/checksum, state binding, and 24-hour age before fixed migrations,
re-assumed deploy apply, and candidate validation. Terminal evidence is sanitized.
Candidate validation includes the fixed Greenway public-session canary:
it requires one exact current-price call, a correlated successful result, a
grounded amount, the required disclaimer, and completion within 60 seconds.
Only its bounded, candidate-bound record reaches delivery evidence; raw stream
and provider data stay private. Production then waits for separate
`production-cutover` approval while the active slot serves ordinary traffic.
Fresh validation gates a new routing-only plan before promotion. Post-cutover
observation attempts one restoration after two consecutive probe failures.
See the [blue-green delivery procedure](runbooks/blue-green-deployments.md).
Configuration alone does not prove bootstrap or activation has completed.
Production schema changes use the protected fixed-target migration component
below. The one-time baseline adoption is complete. Application release
artifacts alone do not authorize or execute schema changes.

Admission compares the tip of `main` with the last successful delivery run
(push runs from before nightly delivery count). If the tip is that commit, or
everything since is Markdown not pinned in
`infra/development-release-manifest.json`, the run is admitted but not built or
deployed. The only Markdown that reaches a package or the release bundle is the
pinned agent SOP, so such a run changes nothing that runs. A skipped run ends
after admission and leaves no release evidence. Production admission uses the
earliest successful delivery run of the exact release commit and needs its
evidence. It rejects a commit that was never delivered, so before publishing a
release, dispatch a delivery on that `main` tip or tag a commit a nightly run
delivered. If a delivery fails and nothing merges, the next night retries the
same commit and fails at the retained release artifact. Re-run the failed run's
jobs instead. Never use "Re-run all jobs" on a successful delivery: its build
fails at the retained artifact, the run turns to failure, and that commit can
neither deliver nor release until a new commit merges.

### Protected development migration workflow (#305 slice 3)

This workflow is a post-merge, protected development operation. Only migration
files whose backward-compatible status was reviewed by a human at merge may run
automatically, and only against the fixed development database. The builder and
CI checks do not assume the migration role, fetch an IAM token, connect to RDS,
apply Terraform, bootstrap PostgreSQL, or dispatch a workflow.

After human review and merge, the protected delivery job uses a clean checkout
of protected `origin/main` and follows this exact order:

1. Verify the release artifact, checkout `HEAD`, `GITHUB_SHA`, manifest commit,
   migration inventory, registry, baseline, and canonical SQL bytes are exactly
   equal before any delivery or migration credentials are available.
2. Create one private saved Terraform plan and run the existing JSON
   address/action gate. Do not apply or re-plan before migration; retain the
   exact plan across the credential switch.
3. After the RDS instance is available and the protected private route/
   transport proof passes, assume only
   `nova-toll-v2-development-migrations-dev` and run the fixed runner. Expected
   `after` versions come from the verified release manifest. Keep the reviewed
   administrator URL, password, and any IAM token in process memory only; never
   write them to a file, argument, state, plan, log, summary, or artifact.

   When a canonical schema version advances, add its contiguous migration
   chain and append the matching immutable record to
   `v2/db/migration-baselines.json`. Existing manifest records must never be
   rewritten or deleted; this metadata change does not authorize a live action.

4. Re-assume `nova-toll-v2-development-delivery` and apply the same saved plan
   only after migration succeeds. The job uses the native
   `v2-development-apply` queue shared with the manual migration workflow.

5. While still holding that queue, verify the three application Lambda hashes
   and the proxy's published `live` alias, CloudFront readiness, and the exact
   AgentCore `preview` live/target version from private post-apply state. The
   bounded helper then checks manifest-backed HTTPS static bytes, generated
   development robots policy, API configuration, invalid-origin rejection, and
   a small agent exchange in two isolated sessions. Reset/replay verifies
   revocation without matching model prose; both sessions are cleaned up.

The explicit GitHub `development-release` record starts after exact CI admission
and before build. Its final status covers build through readiness/smoke; native
`development` environment records used for OIDC are not end-to-end proof. Failed,
cancelled, skipped, disabled, or stale attempts cannot produce release success.
A failed-deploy rerun reuses the same run/SHA's verified immutable build and
record, with the current attempt identified in its status link. The credentialed
deploy job admits that rerun only when `github.triggering_actor == github.actor`;
a different writer's rerun skips before development credentials. Status-publication
failure is a failed workflow, not successful evidence. The summary contains only
commit/run/attempt, artifact ID/digest, schema versions, job outcomes and the
fixed public URL. State, plans, AWS responses, credentials, cookies and chat
content are never published. The helper has a 15-minute deadline; failure does
not roll back an applied release or expand migration authority.

PR validation uses fake AWS/HTTP responses only. A visible post-merge live
demonstration still requires separate human authorization.

The fixed manual recovery workflow remains available for an explicitly approved
post-merge bootstrap or migration rehearsal after the reviewed foundation plan
and fresh development bootstrap gates.
Dispatch
   `.github/workflows/v2-development-migrations.yml` only from `refs/heads/main`;
the job also requires GitHub actor ID `91573985` and
`github.triggering_actor == github.actor`:

   ```sh
   gh workflow run v2-development-migrations.yml \
     --repo rhprasad0/nova-toll-budget-agent --ref main
   ```

   The job joins only `tag:ci-development`, validates the fixed site-1 route,
   keeps the verified RDS DNS name in `PGHOST`, uses only the derived 4via6
   address in `PGHOSTADDR`, and authenticates only as
   `schema_migrator_development`. It accepts no database, user, host, port,
   migration-path, role, or production target input. Keep
   `DEVELOPMENT_DELIVERY_ENABLED` absent or `false` during manual recovery.

When the fresh bootstrap is current, the successful migration result must have
canonical `after` versions equal to the verified release manifest with
`applied=[]` (a non-current before state may contain only registered migration
paths and must finish at those same manifest-bound versions). Runner history evidence
uses exactly `commit=<40 lowercase hex>;run=<UUID>`; the workflow summary and
artifact add only the commit, GitHub run identifiers, account, fixed role,
database/user, before/after versions, applied paths, route/transport booleans,
and `status=ok`. They never contain a token, password, endpoint, host/port URL,
OAuth value, raw command output, error text, Terraform state, or plan. Preserve
the sanitized evidence with the reviewed foundation/bootstrap records. Any
failure stops for human review; do not retry an uncertain write or run a generic
migration command.

### Protected production migration component (issue 304, slice 4)

`.github/workflows/v2-production-migrations.yml` is a main-only reusable
component invoked by `.github/workflows/v2-production-plan.yml` during its
`prepare-production` and `promote-production` phases. It accepts only the
verified release admission, rechecks the durable claim and active caller,
verifies the exact candidate bundle before OIDC or private-network access, and
runs the fixed `nova-toll-db` / `nova_toll` production profile. The wrapper
requires private IPv4/Tailscale connectivity, pinned `verify-full` TLS, IAM
database authentication, encrypted available RDS metadata, seven-day backup
retention, and a timezone-aware `LatestRestorableTime` no more than 30 minutes
old and never in the future. This is admission evidence, not a recovery
rehearsal. The configured delivery sequence binds this component to the exact
saved-plan apply and permits only the registered migration set; it does not
authorize generic or manual production migrations. These workflow definitions
describe the configured path, not proof of activation or a successful deployed
migration.

The current production baseline is AWS account `920534282028` in `us-east-1`:

- Foundation state: `s3://nova-toll-tfstate-920534282028/nova-toll/terraform.tfstate`.
- Application state: `s3://nova-toll-tfstate-920534282028/nova-toll/v2/terraform.tfstate`.
- PostgreSQL: `nova-toll-db` / `nova_toll`; reporting Glue database:
  `tollchat_agent_reports`; session table: `tollchat-v2-anonymous-sessions`.
- Public domains: `tollchat.ai` and `www.tollchat.ai`; fixed dependencies include
  `nova-toll-rds`, `nova-toll-private-a`, `nova-toll-private-c`,
  `nova-toll-agentcore-endpoint`, and `nova-toll-eventbridge-endpoint`.
- Default application tags are `project = nova-toll-budget-agent`, `version = v2`,
  and `environment = production`. Production foundation resources use
  `environment = shared`; any `shared_with = development` tag is descriptive
  only and grants no development-account access.
- Blue-green descriptors pin immutable, versioned artifacts under
  `releases/<release-id>/` in `nova-toll-agentcore-920534282028`, plus each
  retained slot's configuration and frontend asset prefix.
- Blue and green retain published Lambda versions and pinned AgentCore endpoints.
  Active-slot selection controls public/private routing; the previous slot
  remains available for recovery.
- Development is owned by AWS account `903859731897` (`nova-toll-development`)
  with its own foundation and application state backends. It consumes only a
  reviewed non-secret foundation handoff from that account; it has no AWS read
  path into production account `920534282028`.

Before release apply, require the foundation plan to be zero-change. Review every
action in the saved candidate application plan against intended reviewed release
changes. Stop on any unexplained action or any replacement.

## Production baseline adoption (issue 304, slice 1) [completed]

The one-time adoption of the existing `nova_toll` database recorded its verified
schemas as the migration baseline before production migrations 033 onward ran
through the protected component. Do not rerun it.
`v2/scripts/adopt_production_baseline.py` remains because the migration runner
imports its fixed targets and the PostGIS ACL guard below. Its original
procedure is in
[Git history before this cleanup](https://github.com/rhprasad0/nova-toll-budget-agent/blob/ed784c8e/v2/RUNBOOK.md#production-baseline-adoption-issue-304-slice-1).

## RDS PostGIS type ACL exception (issue 304)

The adoption preflight accepts one observed platform state: `postgis` in
`oracle`, owned by `rdsadmin`, at version `3.5.6`, with one direct extension
dependency for each of `oracle.geometry` and `oracle.geography`. Both types
must be owned by `rdsadmin` and have exactly two non-grantable `USAGE` rows:
`rdsadmin` to `rdsadmin`, and `rdsadmin` to `PUBLIC`. Any other owner,
extension identity, dependency, grantor, grantee, privilege, or grant option
rejects adoption. Record that exact state in the fresh read-only evidence
packet before the normal fixed-target adoption; keep the private route,
in-memory managed secret, and `verify-full` TLS.

`PUBLIC` type `USAGE`, combined with an already-held database `TEMPORARY`
privilege, can permit temporary type-dependent objects. It does not grant
schema `USAGE` or `CREATE`, table `SELECT`/DML, function `EXECUTE`, persistent
Oracle creation, or data access. A disposable true-superuser PostGIS test
proves SQL shape, guards, atomicity, rollback, and idempotence only; it does
not prove RDS authority. On a failed or uncertain commit, stop and collect new
read-only evidence before any follow-up; do not reset, bootstrap, or migrate.

## Environment-tag inventory and release safety

The active cost-allocation key is the lowercase `environment`. Its only values
are `development`, `production`, and `shared`. Production foundation resources
use `shared`; any existing `shared_with=development` tag is descriptive only
and grants no development-account access. Do not attempt Cost Explorer
activation.

Before and after a release, inventory every Resource Groups Tagging API page
and retain only its sanitized page/resource/value counts. The foundation plan
must stay zero-change for an application release; never apply it from one. Save and inspect
each saved application plan as JSON, review every non-no-op action and sanitized
before/after semantic delta, then apply only that exact reviewed plan.
Keep ignored package builds and hash-identified saved plans until independent
review passes; never retain state, tokens, or raw plan JSON.

## Account-local foundation handoff

For endpoint consolidation and replacement of managed NAT with the existing
routers, use the [router NAT procedure](runbooks/router-nat.md). This is a
reviewed foundation operation, separate from application and database delivery.

The foundation and application roots have independent state. The guarded
production planner reads the current foundation output into a temporary tfvars
file, validates its approved non-secret shape, passes it only to the matching
v2 plan, and removes that file. This is a planner-owned production handoff, not
a local release path or a development-state discovery mechanism.

Cloudflare DNS reads and writes (zone lookup, ACM certificate-validation
records, and apex/www records) are production-only in `v2/infra/site.tf`.
`enable_public_dns = false` remains the production apex switch, while the
development path has no Cloudflare data or resource instances.

## Build and review

`.github/scripts/verify.sh loader` runs the tests and builds every package, as CI
does. After changing a pinned file, refresh the release pins from `v2/` and
review the diff:

```sh
python3 scripts/update_release_manifest.py
```

To refresh the package digests as well, pass a `sha256sum` listing of the zips
in `infra/build/` that the manifest's `packages` names.

For current blue-green releases, delivery creates the private, versioned recovery
record used by the protected `v2-production-recovery.yml` workflow. Retain the
original numeric `claim_id`, exact `record_version`, and reviewed
`expected_state_sha256`. Follow the [blue-green recovery procedure](runbooks/blue-green-deployments.md).

Historical `usage.json` is retained as a managed, data-bearing site object.
This release stops new writes and does not purge that snapshot or its logs; a
separately approved retirement procedure is required before either is removed.

The former first agent-route measurement release instructions are retained only
in the reviewed historical checkout for that release. They are not an
activation path for this source cleanup: no deployment claim follows from
removing the producer, and the retained measurement bucket, catalog, and
historical objects remain pending a separately approved retirement procedure.

## Guarded production release and related procedures

Use only the procedure that owns the intended operation:

- [Blue-green delivery and application recovery](runbooks/blue-green-deployments.md)
  covers development and production releases, cutover and recovery.
- [Timed-check Scheduler bootstrap and verification (#345)](runbooks/timed-checks-scheduler.md)
  is retained for its bounded bootstrap, Cloudflare/DNS, and recovery contracts.
- The [MCP server runbook](runbooks/mcp-server.md) covers its administrator-applied
  resources, code deploys, and Muse connection (development only).
- The [protected development migration workflow](#protected-development-migration-workflow-305-slice-3)
  is the post-merge development schema path.
- [#331 release bring-up](runbooks/development-release.md) is a historical stub.
  The other completed account-split procedures (#327, #330, #332, #333) are in
  Git history.

Public report publication remains non-operative.
An AWS-only identity cannot write Cloudflare DNS.

### Guarded production release

Before publishing a release, complete the
[manual release schema preflight](manual-releases/README.md#2-check-schemas-before-publishing).
Compare candidate/development schema evidence, the production wrapper's expected
versions, and the reviewed production migration cap. Verify the installed
production versions and each migration's role prerequisites. Development success
alone is insufficient. The cap is `PRODUCTION_MAX_MIGRATION_NUMBER` in
`scripts/run_development_migrations.py`; the versions it reaches are the ones
`scripts/run_production_migrations_workflow.sh` expects.
Migration 033 requires the separately provisioned production `eval_writer` role;
034 updates 24 route labels and aliases without changing route connections.
Migration 035 advances the Oracle version without changing production data or ACLs;
its catalog-reader grants are restricted to development.

The only production path is the guarded published-release flow. A verified
development candidate/bundle reaches a stable published `vX.Y.Z` event, whose
listener has no AWS credentials. Admission records one durable claim. The
planner validates the exact candidate bundle and revalidates mutable release
evidence before planner OIDC credentials, then creates one encrypted,
versioned, checksummed candidate/state-bound saved plan valid for 24 hours.

Reviewer approval of the protected `production` job occurs after that plan is
saved and before the reusable job can access environment secrets or credentials.
That job again revalidates admission/candidate and the exact saved plan/state
before migration credentials and fixed migration, re-assumes the deploy role,
then repeats exact plan/state validation before applying that same plan to the
inactive slot. Candidate checks cover readiness, the bounded canary, guardrail
rejection, trace redaction, sessions, assets, and actual release identity.

The candidate remains running while ordinary traffic stays on the active slot.
A separate `production-cutover` approval is required before promotion. After
approval, the protected job revalidates the prepared record and unchanged state,
runs fresh candidate checks, and gates a new routing-only plan. It does not
rerun migrations or reapply preparation. The existing `production` environment
may also require approval for the resumed job. Both phases require
`PRODUCTION_BLUE_GREEN_BOOTSTRAPPED == 'true'`.

After promotion, five probes run one minute apart. Two consecutive failures
trigger one recovery attempt; deployment and recovery outcomes are reported
separately. A failed guard stops every later stage it protects; it never
authorizes a direct, arbitrary, stale, or caller-selected plan/apply. Terminal
evidence remains sanitized. Follow the [blue-green runbook](runbooks/blue-green-deployments.md)
for candidate testing, approval, observation, and protected recovery.

## Public report launch (production only)

The report publisher depends on the CloudFront distribution and `robots.txt`,
so enabling publication in the complete saved plan happens only after the edge
rewrite has deployed. Wait for the distribution, enqueue one watchdog run, and
verify the complete manifest before testing public URLs. Run this section only
after the production guarded release; never run it while the development
backend is selected. Development public report publication remains deferred.

```sh
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT/v2/infra"
test "$(AWS_PROFILE=nova-toll-prod aws sts get-caller-identity --query Account --output text)" = "920534282028"
AWS_PROFILE=nova-toll-prod terraform init -reconfigure -input=false -backend-config=backend.production.hcl
PUBLISHER_FUNCTION="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_lambda_function.publisher | awk -F' = ' '$1 ~ /^    function_name/ {gsub(/"/, "", $2); print $2; exit}')"
PUBLISHER_LOG_GROUP="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_cloudwatch_log_group.publisher | awk -F' = ' '$1 ~ /^    name/ {gsub(/"/, "", $2); print $2; exit}')"
SITE_DISTRIBUTION="$(AWS_PROFILE=nova-toll-prod terraform output -json public_site | jq -er '.distribution_id | select(type == "string")')"
SITE_URL="$(AWS_PROFILE=nova-toll-prod terraform output -json public_site | jq -er '.url | select(type == "string")')"
SITE_BUCKET="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color \
  aws_s3_bucket.site | awk -F' = ' '$1 ~ /^    bucket/ {gsub(/"/, "", $2); print $2; exit}')"
test "$PUBLISHER_FUNCTION" = "toll-v2-report-publisher"
test "$PUBLISHER_LOG_GROUP" = "/aws/lambda/toll-v2-report-publisher"
test "$SITE_BUCKET" = "tollchat-site-920534282028"
test -n "$SITE_DISTRIBUTION"
[[ "$SITE_DISTRIBUTION" =~ ^[A-Z0-9]+$ ]]
test "$SITE_URL" = "https://tollchat.ai"
AWS_PROFILE=nova-toll-prod aws --region us-east-1 cloudfront wait distribution-deployed \
  --id "$SITE_DISTRIBUTION"
REPORT_INVOKE="$(mktemp)"
REPORT_MANIFEST_I95="$(mktemp)"; REPORT_MANIFEST_I66="$(mktemp)"
trap 'rm -f -- "$REPORT_INVOKE" "$REPORT_MANIFEST_I95" "$REPORT_MANIFEST_I66"' EXIT
REPORT_SMOKE_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
REPORT_STARTED_MS="$(date +%s%3N)"
report_smoke_succeeded() {
  local smoke_pattern='V2_REPORT_SMOKE_OK '"$REPORT_SMOKE_ID"' (published|unchanged) ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?Z) [a-f0-9]{64}[[:space:]]*$'
  while IFS=$'\t' read -r event_time event_message; do
    if [[ "$event_time" =~ ^[0-9]+$ ]] && (( event_time >= REPORT_STARTED_MS )) && \
      [[ "$event_message" =~ $smoke_pattern ]] && \
      date -u -d "${BASH_REMATCH[2]}" +%s >/dev/null 2>&1; then
      return 0
    fi
  done <<< "$1"
  return 1
}
report_manifest_is_valid() {
  jq -e --arg facility "$1" --argjson routes "$2" '.schema_version == "3.0.0" and .facility == $facility and .route_count == $routes and (.week_end | type == "string" and length > 0) and (.result_sha256 | test("^[a-f0-9]{64}$"))' "$3"
}
AWS_PROFILE=nova-toll-prod aws --region us-east-1 lambda invoke \
  --function-name "$PUBLISHER_FUNCTION" --invocation-type Event \
  --cli-binary-format raw-in-base64-out \
  --payload "$(jq -nc --arg smoke_id "$REPORT_SMOKE_ID" '{trigger:"watchdog",smoke_id:$smoke_id}')" \
  "$REPORT_INVOKE" | jq -e '.StatusCode == 202'
REPORT_RESULT=""
for attempt in $(seq 1 90); do
  REPORT_RESULT="$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 logs filter-log-events \
    --log-group-name "$PUBLISHER_LOG_GROUP" --start-time "$REPORT_STARTED_MS" \
    --filter-pattern "\"V2_REPORT_SMOKE_OK $REPORT_SMOKE_ID\"" \
    --query 'events[].[timestamp,message]' --output text || true)"
  if report_smoke_succeeded "$REPORT_RESULT"; then
    break
  fi
  sleep 10
done
report_smoke_succeeded "$REPORT_RESULT"
AWS_PROFILE=nova-toll-prod aws --region us-east-1 s3api get-object \
  --bucket "$SITE_BUCKET" --key tolls/i95-i495/manifest.json \
  "$REPORT_MANIFEST_I95" >/dev/null
AWS_PROFILE=nova-toll-prod aws --region us-east-1 s3api get-object \
  --bucket "$SITE_BUCKET" --key tolls/i66/manifest.json \
  "$REPORT_MANIFEST_I66" >/dev/null
report_manifest_is_valid i95_i495 246 "$REPORT_MANIFEST_I95"
report_manifest_is_valid i66 16 "$REPORT_MANIFEST_I66"
unset REPORT_RESULT REPORT_SMOKE_ID REPORT_STARTED_MS PUBLISHER_LOG_GROUP
```

The sitemap contains 262 route reports and two facility indexes. Check every
canonical report and JSON sibling with bounded concurrency, then check the
indexes, homepage discovery links, retired-route responses, both hostnames,
crawler policy, representative agent families, and API isolation:

Detailed entrance/exit URLs are retired. Verified replacements return 301 to the
matching area report on the same host; other URLs in that retired namespace return 410. After
deployment and these checks, resubmit the sitemap and start Search Console
validation for the forbidden URLs. Redirected and removed URLs can remain
excluded; indexing of the current reports is Google's decision.

```sh
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT/v2/infra"
test "$(AWS_PROFILE=nova-toll-prod aws sts get-caller-identity --query Account --output text)" = "920534282028"
AWS_PROFILE=nova-toll-prod terraform init -reconfigure -input=false -backend-config=backend.production.hcl
PUBLISHER_FUNCTION="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_lambda_function.publisher | awk -F' = ' '$1 ~ /^    function_name/ {gsub(/"/, "", $2); print $2; exit}')"
PUBLISHER_LOG_GROUP="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_cloudwatch_log_group.publisher | awk -F' = ' '$1 ~ /^    name/ {gsub(/"/, "", $2); print $2; exit}')"
SITE_DISTRIBUTION="$(AWS_PROFILE=nova-toll-prod terraform output -json public_site | jq -er '.distribution_id | select(type == "string")')"
SITE_URL="$(AWS_PROFILE=nova-toll-prod terraform output -json public_site | jq -er '.url | select(type == "string")')"
SITE_BUCKET="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color \
  aws_s3_bucket.site | awk -F' = ' '$1 ~ /^    bucket/ {gsub(/"/, "", $2); print $2; exit}')"
test "$PUBLISHER_FUNCTION" = "toll-v2-report-publisher"
test "$PUBLISHER_LOG_GROUP" = "/aws/lambda/toll-v2-report-publisher"
test "$SITE_BUCKET" = "tollchat-site-920534282028"
test -n "$SITE_DISTRIBUTION"
[[ "$SITE_DISTRIBUTION" =~ ^[A-Z0-9]+$ ]]
test "$SITE_URL" = "https://tollchat.ai"
REPORT_URLS="$(mktemp)"
SITEMAP_URLS="$(mktemp)"
REPORT_PAGE="$(mktemp)"
trap 'rm -f -- "$REPORT_PAGE" "$REPORT_URLS" "$SITEMAP_URLS"' EXIT
curl --fail-with-body --silent --show-error "$SITE_URL/sitemap.xml" \
  | python3 -c 'import sys, xml.etree.ElementTree as ET; root = ET.parse(sys.stdin).getroot(); assert root.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset"; urls = [node.text for node in root.findall("{*}url/{*}loc")]; assert len(urls) == len(set(urls)) == 264; assert all(url.startswith("https://tollchat.ai/tolls/") and url.endswith("/") for url in urls); print("\n".join(urls))' >"$SITEMAP_URLS"
for facility in i95-i495 i66; do
  index_url="$SITE_URL/tolls/$facility/"
  grep -Fx "$index_url" "$SITEMAP_URLS"
  curl --fail-with-body --silent --show-error "$index_url" >"$REPORT_PAGE"
  grep -F '<link rel="canonical" href="'"$index_url"'">' "$REPORT_PAGE" >/dev/null
  if grep -qi 'noindex\|<script' "$REPORT_PAGE"; then exit 1; fi
  curl --fail-with-body --silent --show-error "https://www.tollchat.ai/tolls/$facility/" \
    | grep -F '<link rel="canonical" href="'"$index_url"'">' >/dev/null
  curl --fail-with-body --silent --show-error "$SITE_URL/" \
    | grep -F 'href="'"$index_url"'"' >/dev/null
done
curl --fail-with-body --silent --show-error "$SITE_URL/" \
  | grep -F '<link rel="canonical" href="https://tollchat.ai/">' >/dev/null
for legacy in /tolls /tolls/; do
  test "$(curl --silent --show-error --output /dev/null --dump-header "$REPORT_PAGE" \
    --write-out '%{http_code}' "$SITE_URL$legacy")" -eq 301
  grep -iFx $'location: /#toll-reports\r' "$REPORT_PAGE"
done
LEGACY_REPORT="$SITE_URL/tolls/i95-i495/woodburn-gallows-road-merrifield-northbound/tysons-route-7-leesburg-pike-northbound/"
test "$(curl --silent --show-error --output /dev/null --dump-header "$REPORT_PAGE" \
  --write-out '%{http_code}' "$LEGACY_REPORT")" -eq 301
grep -iFx $'location: /tolls/i95-i495/northbound/woodburn-to-tysons/\r' "$REPORT_PAGE"
curl --fail-with-body --silent --show-error --location "$LEGACY_REPORT" \
  | grep -F '<link rel="canonical" href="https://tollchat.ai/tolls/i95-i495/northbound/woodburn-to-tysons/">' >/dev/null
test "$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  "$SITE_URL/tolls/i95-i495/arlington-pentagon-pentagon-city-southbound/quantico-joplin-road-southbound/")" -eq 410
grep -vFx -e "$SITE_URL/tolls/i95-i495/" -e "$SITE_URL/tolls/i66/" \
  "$SITEMAP_URLS" >"$REPORT_URLS"
test "$(wc -l <"$REPORT_URLS")" -eq 262
xargs -P 8 -n 1 sh -c '
  set -eu
  html="$1"
  page="$(mktemp)"
  headers="$(mktemp)"
  trap "rm -f -- \"$page\" \"$headers\"" EXIT
  curl --fail --silent --show-error --dump-header "$headers" "$html" >"$page"
  grep -qi "^content-type: text/html" "$headers"
  if grep -qi "^x-robots-tag:.*noindex" "$headers" \
    || grep -qi "noindex\|<script" "$page"; then exit 1; fi
  grep -F "<link rel=\"canonical\" href=\"$html\">" "$page" >/dev/null
  grep -F "<table>" "$page" >/dev/null
  grep -F "USD" "$page" >/dev/null
  grep -F "America/New_York" "$page" >/dev/null
  curl --fail --silent --show-error --dump-header "$headers" \
    "${html}report.json" >"$page"
  grep -qi "^content-type: application/json" "$headers"
  python3 -c "import json, sys; json.load(sys.stdin)" <"$page"
' _ <"$REPORT_URLS"

REPORT_URL="$SITE_URL/tolls/i95-i495/northbound/dumfries-to-tysons/"
I66_REPORT_URL="$(grep '/tolls/i66/' "$REPORT_URLS" | head -n 1)"
test -n "$I66_REPORT_URL"
curl --fail-with-body --silent --show-error "$REPORT_URL" >"$REPORT_PAGE"
grep -F '<link rel="canonical" href="'"$REPORT_URL"'">' "$REPORT_PAGE"
grep -F '<table>' "$REPORT_PAGE"
if grep -qi 'noindex\|<script' "$REPORT_PAGE"; then exit 1; fi
curl --fail-with-body --silent --show-error "$I66_REPORT_URL" >"$REPORT_PAGE"
grep -F '<table>' "$REPORT_PAGE"
curl --fail-with-body --silent --show-error "$SITE_URL/robots.txt" \
  | grep -F "Sitemap: $SITE_URL/sitemap.xml"
for agent in OAI-SearchBot ChatGPT-User Googlebot Claude-SearchBot Claude-User \
  PerplexityBot bingbot Amzn-SearchBot Applebot DuckAssistBot; do
  for path in /robots.txt /sitemap.xml "${REPORT_URL#"$SITE_URL"}" \
    "${I66_REPORT_URL#"$SITE_URL"}"; do
    curl --fail-with-body --silent --show-error --user-agent "$agent" \
      "$SITE_URL$path" >/dev/null
  done
done
curl --fail-with-body --silent --show-error "$SITE_URL/api/config" >/dev/null
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "$SITE_URL/api/chat")" -eq 404
rm -f -- "$REPORT_PAGE" "$REPORT_URLS" "$SITEMAP_URLS"
trap - EXIT
unset REPORT_PAGE REPORT_URL I66_REPORT_URL REPORT_URLS SITEMAP_URLS SITE_URL LEGACY_REPORT
```

Terraform uploads both application packages to versioned S3 keys and pins the
resulting object version IDs in Lambda and AgentCore. Do not apply an unsaved
or unreviewed plan. The public Function URL targets the published `live` alias,
which keeps one provisioned execution environment warm. The function-level
reserved concurrency remains the five-request safety ceiling.

## Smoke test

Read `terraform output -json private_preview`, connect through Tailscale, and
use its `origin` and `url` values:

```sh
curl --fail-with-body "$URL/api/config" \
  -H "Origin: $ORIGIN" \
  -H 'Sec-Fetch-Site: same-origin'

curl --fail-with-body --no-buffer "$URL/api/chat" \
  -H "Origin: $ORIGIN" \
  -H 'Sec-Fetch-Site: same-origin' \
  -H 'Content-Type: application/json' \
  --data '{"message":"What is the current I-95 toll?"}'
```

The config request must succeed and chat must stream approved tool-status
and `text` events followed by an answer and disclaimer. Each `text` event is
the guardrail-approved text so far for the current assistant message, replacing
the previous provisional answer. Cross-origin requests to the private chat
route must fail.

After an authorized development release, verify streaming in the browser through
CloudFront with both the current-price and annual-commute starter prompts. The
Working indicator must appear on submission, text must appear before completion
for a sufficiently long answer, and the final answer must include the disclaimer.
Record submission-to-feedback, submission-to-first-approved-text, and total
completion times in the release notes; short answers can finish in one batch.
Confirm errors and blocked responses replace any provisional text.

After the private check passes, verify the public edge and warm alias:

```sh
curl --fail-with-body https://tollchat.ai/
curl --fail-with-body https://tollchat.ai/api/config
AWS_PROFILE=nova-toll-prod aws --region us-east-1 lambda get-provisioned-concurrency-config \
  --function-name tollchat-v2-chat-proxy --qualifier live
```

The concurrency status and allocation must be `READY` and `1`. Submit a smoke
message only after the session-cookie reset path succeeds. There is no current
public usage counter or opt-out cookie. Confirm CloudWatch records the request
under `ProvisionedConcurrencyInvocations`, without an on-demand Lambda
initialization. The public Function URL must reject direct unsigned invocation.

## Rollback

For a report-rendering regression, keep the CloudFront rewrite active, deploy
corrected publisher code with a bumped publication format version, and invoke a
watchdog run to replace the complete generation. If report source content is
unsafe, stop new report writes with EventBridge Scheduler. First read and review
the exact schedule (including its group when it is not `default`), then preserve
only its required update fields in a reviewed temporary input. Do not pass the
raw `get-schedule` response back to AWS because it contains read-only fields.

```sh
(
set -euo pipefail
SCHEDULE_SOURCE="$(mktemp)"; SCHEDULE_UPDATE="$(mktemp)"
trap 'rm -f -- "$SCHEDULE_SOURCE" "$SCHEDULE_UPDATE"' EXIT
SCHEDULE_STATE="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_scheduler_schedule.publisher)"
SCHEDULE_NAME="$(printf '%s\n' "$SCHEDULE_STATE" | awk -F' = ' '$1 ~ /^    name/ {gsub(/"/, "", $2); print $2; exit}')"
SCHEDULE_GROUP="$(printf '%s\n' "$SCHEDULE_STATE" | awk -F' = ' '$1 ~ /^    group_name/ {gsub(/"/, "", $2); print $2; exit}')"
case "$SCHEDULE_NAME:$SCHEDULE_GROUP" in :*|*:|*:None|*:null) exit 1 ;; esac
AWS_PROFILE=nova-toll-prod aws --region us-east-1 scheduler get-schedule --name "$SCHEDULE_NAME" --group-name "$SCHEDULE_GROUP" >"$SCHEDULE_SOURCE"
jq -e '{ScheduleExpression, ScheduleExpressionTimezone, FlexibleTimeWindow, Target} | select(.ScheduleExpression and .FlexibleTimeWindow and .Target and .Target.Arn and .Target.RoleArn)' "$SCHEDULE_SOURCE" >"$SCHEDULE_UPDATE"
# Review $SCHEDULE_UPDATE in an approved secure viewer; it retains input, retry policy, and DLQ.
AWS_PROFILE=nova-toll-prod aws --region us-east-1 scheduler update-schedule --name "$SCHEDULE_NAME" --group-name "$SCHEDULE_GROUP" --state DISABLED --schedule-expression "$(jq -er .ScheduleExpression "$SCHEDULE_UPDATE")" --schedule-expression-timezone "$(jq -er .ScheduleExpressionTimezone "$SCHEDULE_UPDATE")" --flexible-time-window "$(jq -c .FlexibleTimeWindow "$SCHEDULE_UPDATE")" --target "$(jq -c .Target "$SCHEDULE_UPDATE")"
)
```

Resume with the same complete selected-state procedure, freshly retrieving and
reviewing its fields before mutation:

```sh
(
set -euo pipefail
SCHEDULE_SOURCE="$(mktemp)"; SCHEDULE_UPDATE="$(mktemp)"
trap 'rm -f -- "$SCHEDULE_SOURCE" "$SCHEDULE_UPDATE"' EXIT
SCHEDULE_STATE="$(AWS_PROFILE=nova-toll-prod terraform state show -no-color aws_scheduler_schedule.publisher)"
SCHEDULE_NAME="$(printf '%s\n' "$SCHEDULE_STATE" | awk -F' = ' '$1 ~ /^    name/ {gsub(/"/, "", $2); print $2; exit}')"
SCHEDULE_GROUP="$(printf '%s\n' "$SCHEDULE_STATE" | awk -F' = ' '$1 ~ /^    group_name/ {gsub(/"/, "", $2); print $2; exit}')"
case "$SCHEDULE_NAME:$SCHEDULE_GROUP" in :*|*:|*:None|*:null) exit 1 ;; esac
AWS_PROFILE=nova-toll-prod aws --region us-east-1 scheduler get-schedule --name "$SCHEDULE_NAME" --group-name "$SCHEDULE_GROUP" >"$SCHEDULE_SOURCE"
jq -e '{ScheduleExpression, ScheduleExpressionTimezone, FlexibleTimeWindow, Target} | select(.ScheduleExpression and .FlexibleTimeWindow and .Target and .Target.Arn and .Target.RoleArn)' "$SCHEDULE_SOURCE" >"$SCHEDULE_UPDATE"
# Review $SCHEDULE_UPDATE in an approved secure viewer before enabling.
AWS_PROFILE=nova-toll-prod aws --region us-east-1 scheduler update-schedule --name "$SCHEDULE_NAME" --group-name "$SCHEDULE_GROUP" --state ENABLED --schedule-expression "$(jq -er .ScheduleExpression "$SCHEDULE_UPDATE")" --schedule-expression-timezone "$(jq -er .ScheduleExpressionTimezone "$SCHEDULE_UPDATE")" --flexible-time-window "$(jq -c .FlexibleTimeWindow "$SCHEDULE_UPDATE")" --target "$(jq -c .Target "$SCHEDULE_UPDATE")"
)
```

Disabling publication does not withdraw existing report objects. The site
bucket is not versioned. A public takedown therefore requires separate approval
to delete the exact `tolls/i95-i495/` and `tolls/i66/` prefixes and `sitemap.xml`, followed by a
targeted CloudFront invalidation. Do not perform that destructive rollback as
part of an ordinary application rollback.

### Blue-green validation failure and recovery

A failed candidate validation blocks promotion and leaves ordinary traffic on
the active slot. After cutover, two consecutive observation failures trigger one
automatic saved-plan routing restoration attempt; a recovered release still
reports deployment failure. After the observation window, cancellation, or runner
loss, dispatch `v2-production-recovery.yml` from `main` with the original
`claim_id`, exact `record_version`, and reviewed `expected_state_sha256`.
Review and approve its protected `production` job. Follow the
[blue-green recovery procedure](runbooks/blue-green-deployments.md).
Recovery restores application routing, not databases or shared infrastructure.

Deterministic builds restore the exact package bytes; bucket versioning retains
the earlier runtime and proxy objects for 30 days. Historical usage aggregate,
snapshot, and publisher logs remain retained across rollback; no current writer
or public usage proof is restored by this procedure.

If the application cannot safely serve traffic while rollback is prepared, stop
and obtain separate incident authorization. Do not mutate concurrency outside a
reviewed saved Terraform plan.

Database and shared polling/storage infrastructure are not part of application
rollback.

## Production release checks

Production planning admits the exact successful development artifact and records
one durable release claim. Protected human approval, exact saved-plan and state
verification, fixed-target migration checks, and canary checks remain required.
Private holdout evaluation is no longer a production admission requirement; the
former environment and qualification workflows are retired. A replacement approach
will be designed separately.

New saved-plan records use schema version 2 and omit holdout qualification fields.
Version 1 plans are rejected. Retained
recovery archives remain available through the protected recovery procedure.

The Terraform configuration retires the holdout reader/reviewer roles while
preserving the encrypted, versioned evidence bucket and deletion protections.
Existing cloud evidence and unused GitHub evaluation environments remain retained.
