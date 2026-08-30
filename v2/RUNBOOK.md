# AgentCore deployment

Deployments are manual. CI builds and tests the application but never runs a
Terraform plan or apply.

## Delivery contract and production baseline

PRs use disposable PostGIS migration validation only; they never access or
mutate deployed databases or schemas. `main` continues to run validation only.
Published releases are manual, reviewed deployments from `main`; schema-changing
work is not deployable until approved deployed-migration automation exists.
Current releases are schema-neutral.

The current production baseline is AWS account `920534282028` in `us-east-1`:

- Foundation state: `s3://nova-toll-tfstate-920534282028/nova-toll/terraform.tfstate`.
- Application state: `s3://nova-toll-tfstate-920534282028/nova-toll/v2/terraform.tfstate`.
- PostgreSQL: `nova-toll-db` / `nova_toll`; reporting Glue database:
  `tollchat_agent_reports`; session table: `tollchat-v2-anonymous-sessions`.
- Public domains: `tollchat.ai` and `www.tollchat.ai`; fixed dependencies include
  `nova-toll-rds`, `nova-toll-private-a`, `nova-toll-private-c`,
  `nova-toll-agentcore-endpoint`, and `nova-toll-eventbridge-endpoint`.
- Default application tags are `project = nova-toll-budget-agent`, `version = v2`,
  and `environment = production`. Shared foundation resources add
  `environment = production` and `shared_with = development`.
- Release artifacts overwrite `s3://nova-toll-agentcore-920534282028/runtime/v2/agentcore.zip`
  and `s3://nova-toll-agentcore-920534282028/lambda/v2/chat-proxy.zip`; retained
  S3 object versions are the rollback source.
- Stable release targets are the `live` alias of `tollchat-v2-chat-proxy` and
  the `preview` endpoint of AgentCore runtime `nova_toll_v2`.

Before release apply, require the foundation plan to be zero-change. Review every
action in the saved candidate application plan against intended reviewed release
changes. Stop on any unexplained action or any replacement.

## Build and review

From `v2/`:

```sh
uv sync --locked
uv run pytest
npm ci --prefix lambdas/chat_proxy
npm test --prefix lambdas/chat_proxy
./scripts/build_loader_zip.sh
./scripts/build_publisher_zip.sh
./scripts/build_agentcore_zips.sh
(cd infra/build && sha256sum --check AGENTCORE_SHA256SUMS)
```

Create a saved plan with the reviewed packages and the explicit production
profile. Load the Cloudflare token from SSM only into the Terraform process
environment, then review every action before applying that exact file:

Enter `v2/infra` and initialize the explicit production application state for every release:

```sh
cd infra
export CLOUDFLARE_API_TOKEN="$(AWS_PROFILE=nova-toll aws --region us-east-1 \
  ssm get-parameter --name /nova-toll/cloudflare-api-token --with-decryption \
  --query Parameter.Value --output text)"
AWS_PROFILE=nova-toll aws --region us-east-1 lambda put-function-concurrency \
  --function-name tollchat-v2-chat-proxy \
  --reserved-concurrent-executions 5
AWS_PROFILE=nova-toll terraform init -backend-config=backend.production.hcl
```

Before applying, set `RELEASE_EVIDENCE` to a unique per-release path (for
example, `build/release-evidence-20260829T120000Z.txt`). The file must be
retained with that release; capture never overwrites an existing record.

```sh
(
  set -eu
  : "${RELEASE_EVIDENCE:?set a unique release-evidence path}"
  test ! -e "$RELEASE_EVIDENCE"
  LAMBDA_LIVE_FUNCTION_VERSION="$(AWS_PROFILE=nova-toll aws --region us-east-1 lambda get-alias \
    --function-name tollchat-v2-chat-proxy --name live --query FunctionVersion --output text)"
  AGENTCORE_RUNTIME_ID="$(AWS_PROFILE=nova-toll aws --region us-east-1 bedrock-agentcore-control list-agent-runtimes \
    --query "agentRuntimes[?agentRuntimeName=='nova_toll_v2'].agentRuntimeId | [0]" --output text)"
  AGENTCORE_ENDPOINT_LIVE_VERSION="$(AWS_PROFILE=nova-toll aws --region us-east-1 bedrock-agentcore-control get-agent-runtime-endpoint \
    --agent-runtime-id "$AGENTCORE_RUNTIME_ID" --endpoint-name preview --query liveVersion --output text)"
  case "$LAMBDA_LIVE_FUNCTION_VERSION" in ""|None|*[!0-9]*) exit 1 ;; esac
  case "$AGENTCORE_RUNTIME_ID" in ""|None|[!A-Za-z0-9]*|*[!A-Za-z0-9_-]*) exit 1 ;; esac
  case "$AGENTCORE_ENDPOINT_LIVE_VERSION" in ""|None|*[!0-9]*) exit 1 ;; esac
  printf 'lambda_live_function_version=%s\nagentcore_runtime_id=%s\nagentcore_endpoint_live_version=%s\n' \
    "$LAMBDA_LIVE_FUNCTION_VERSION" "$AGENTCORE_RUNTIME_ID" "$AGENTCORE_ENDPOINT_LIVE_VERSION" >"$RELEASE_EVIDENCE"
)
```

For the first usage-counter release only, stage the public disclosure and
hidden placeholder directly in the encrypted site bucket before deploying the
proxy package. Do not use Terraform resource targets for this step: the site
objects' KMS and CloudFront dependencies also pull the proxy and runtime into a
targeted plan.

```sh
SITE_BUCKET="$(AWS_PROFILE=nova-toll terraform state show -no-color \
  aws_s3_bucket.site | awk -F' = ' '$1 ~ /^    bucket/ {gsub(/"/, "", $2); print $2; exit}')"
SITE_KMS_ARN="$(AWS_PROFILE=nova-toll aws --region us-east-1 kms describe-key \
  --key-id alias/tollchat-v2-site --query KeyMetadata.Arn --output text)"
EMPTY_USAGE="$(mktemp)"
printf '{}\n' >"$EMPTY_USAGE"
AWS_PROFILE=nova-toll aws --region us-east-1 s3api put-object \
  --bucket "$SITE_BUCKET" --key index.html --body ../agent/dev_chat.html \
  --content-type 'text/html; charset=utf-8' --cache-control no-cache \
  --server-side-encryption aws:kms --ssekms-key-id "$SITE_KMS_ARN"
AWS_PROFILE=nova-toll aws --region us-east-1 s3api put-object \
  --bucket "$SITE_BUCKET" --key faq.html --body ../agent/faq.html \
  --content-type 'text/html; charset=utf-8' --cache-control no-cache \
  --server-side-encryption aws:kms --ssekms-key-id "$SITE_KMS_ARN"
AWS_PROFILE=nova-toll aws --region us-east-1 s3api put-object \
  --bucket "$SITE_BUCKET" --key privacy.txt --body ../agent/privacy.txt \
  --content-type 'text/plain; charset=utf-8' --cache-control no-cache \
  --server-side-encryption aws:kms --ssekms-key-id "$SITE_KMS_ARN"
AWS_PROFILE=nova-toll aws --region us-east-1 s3api put-object \
  --bucket "$SITE_BUCKET" --key usage.json --body "$EMPTY_USAGE" \
  --content-type 'application/json; charset=utf-8' --cache-control no-cache \
  --server-side-encryption aws:kms --ssekms-key-id "$SITE_KMS_ARN"
rm -f -- "$EMPTY_USAGE"
unset EMPTY_USAGE SITE_BUCKET SITE_KMS_ARN
curl --fail-with-body https://tollchat.ai/privacy.txt
curl --fail-with-body https://tollchat.ai/faq.html
```

For the first agent-route measurement release, publish and verify the updated
privacy notice before creating the release plan that enables WAF logging. This
is intentionally a separate operation: a Terraform dependency can order S3 and
WAF API calls, but it cannot prove the notice was already visible through the
deployed CloudFront surface.

```sh
SITE_BUCKET="$(AWS_PROFILE=nova-toll terraform state show -no-color \
  aws_s3_bucket.site | awk -F' = ' '$1 ~ /^    bucket/ {gsub(/"/, "", $2); print $2; exit}')"
SITE_KMS_ARN="$(AWS_PROFILE=nova-toll aws --region us-east-1 kms describe-key \
  --key-id alias/tollchat-v2-site --query KeyMetadata.Arn --output text)"
AWS_PROFILE=nova-toll aws --region us-east-1 s3api put-object \
  --bucket "$SITE_BUCKET" --key privacy.txt --body ../agent/privacy.txt \
  --content-type 'text/plain; charset=utf-8' --cache-control no-cache \
  --server-side-encryption aws:kms --ssekms-key-id "$SITE_KMS_ARN"
curl --fail-with-body --silent --show-error https://tollchat.ai/privacy.txt \
  | grep -F 'TollChat keeps filtered raw route-report access logs and Athena query results for seven days.'
unset SITE_BUCKET SITE_KMS_ARN
```

After those one-time prerequisites, create and apply the complete saved release
plan. Later releases start here after initialization:

```sh
AWS_PROFILE=nova-toll terraform plan \
  -var loader_package_path=build/loader.zip \
  -var publisher_package_path=build/publisher.zip \
  -var agentcore_package_path=build/agentcore.zip \
  -var chat_proxy_package_path=build/chat-proxy.zip \
  -out=build/release.tfplan
AWS_PROFILE=nova-toll terraform show build/release.tfplan
AWS_PROFILE=nova-toll terraform apply build/release.tfplan
AWS_PROFILE=nova-toll aws --region us-east-1 iam get-role-policy \
  --role-name nova-toll-v2-chat-proxy \
  --policy-name nova-toll-v2-chat-proxy \
  --query PolicyDocument --output json | grep -F 'dynamodb:TransactWriteItems'
unset CLOUDFLARE_API_TOKEN
```

## Development environment

Development has its own application state and names but reads the shared
network, RDS, raw-data, and alert foundations. Its only shared-foundation
writes are development-keyed artifact objects and the RDS security-group ingress
rule. It uses
`dev.tollchat.ai`, `nova_toll_development`, development database roles, shorter
logs, non-paging alarms, and no provisioned proxy concurrency. Bootstrap its
AWS-side dependencies separately before planning; this configuration never
creates PostgreSQL roles or schemas.

### One-time development database bootstrap

Before development infrastructure uses the database, an approved administrator
must run the reviewed one-time bootstrap. Store no credential locally: replace
`/approved/administrator/connection` with the approved SecureString parameter
name, load it only into this process, then remove it when finished.

```sh
if ! NOVA_TOLL_ADMIN_URL="$(AWS_PROFILE=nova-toll aws --region us-east-1 \
  ssm get-parameter --name /approved/administrator/connection --with-decryption \
  --query Parameter.Value --output text)"; then
  echo 'could not retrieve the approved administrator connection' >&2
  exit 1
fi
: "${NOVA_TOLL_ADMIN_URL:?administrator connection was empty}"
export NOVA_TOLL_ADMIN_URL
if ! python3 v2/scripts/bootstrap_development_database.py; then
  unset NOVA_TOLL_ADMIN_URL
  exit 1
fi
unset NOVA_TOLL_ADMIN_URL
```

The connection value must be a PostgreSQL administrator URL for the shared
instance. The command fails closed unless its explicit connection target,
`nova_toll`, `rds_iam`, and all six safe production roles already exist and the
development database/roles do not. It creates only `nova_toll_development` plus
the fixed `_development` roles.

```sh
cd v2/infra
AWS_PROFILE=nova-toll terraform init -backend-config=backend.development.hcl
AWS_PROFILE=nova-toll terraform plan -var-file=development.tfvars \
  -var loader_package_path=build/loader.zip \
  -var publisher_package_path=build/publisher.zip \
  -var agentcore_package_path=build/agentcore.zip \
  -var chat_proxy_package_path=build/chat-proxy.zip
```

### Development infrastructure review

Build and record all four reviewed package digests before planning:

```sh
cd v2
./scripts/build_loader_zip.sh
./scripts/build_publisher_zip.sh
./scripts/build_agentcore_zips.sh
(cd infra/build && sha256sum loader.zip publisher.zip agentcore.zip chat-proxy.zip \
  > DEVELOPMENT_SHA256SUMS && sha256sum --check DEVELOPMENT_SHA256SUMS)
```

Check direct regional and global quota headroom; stop if either result cannot
cover the reviewed plan:

```sh
AWS_PROFILE=nova-toll aws --region us-east-1 service-quotas get-service-quota \
  --service-code cloudfront --quota-code L-0EA8095F
AWS_PROFILE=nova-toll aws --region us-east-1 service-quotas get-service-quota \
  --service-code lambda --quota-code L-B99A9384
AWS_PROFILE=nova-toll aws --region us-east-1 service-quotas get-service-quota \
  --service-code elasticloadbalancing --quota-code L-53DA6B97
AWS_PROFILE=nova-toll aws --region us-east-1 service-quotas get-service-quota \
  --service-code iam --quota-code L-FE177D64
```

Load the Cloudflare token only into this shell. First save and review a
production zero-change plan; do not continue unless it reports no changes.
Then create and review the DNS-disabled development plan. It must contain only
creates—no update, replacement, or destroy—and is the only development plan
eligible to apply.

```sh
cd v2/infra
export CLOUDFLARE_API_TOKEN="$(AWS_PROFILE=nova-toll aws --region us-east-1 \
  ssm get-parameter --name /nova-toll/cloudflare-api-token --with-decryption \
  --query Parameter.Value --output text)"
AWS_PROFILE=nova-toll terraform init -backend-config=backend.production.hcl
AWS_PROFILE=nova-toll terraform plan \
  -var loader_package_path=build/loader.zip \
  -var publisher_package_path=build/publisher.zip \
  -var agentcore_package_path=build/agentcore.zip \
  -var chat_proxy_package_path=build/chat-proxy.zip \
  -out=build/production-zero-change.tfplan
AWS_PROFILE=nova-toll terraform show build/production-zero-change.tfplan
AWS_PROFILE=nova-toll terraform init -reconfigure -backend-config=backend.development.hcl
AWS_PROFILE=nova-toll terraform plan -var-file=development.tfvars \
  -var loader_package_path=build/loader.zip \
  -var publisher_package_path=build/publisher.zip \
  -var agentcore_package_path=build/agentcore.zip \
  -var chat_proxy_package_path=build/chat-proxy.zip \
  -out=build/development-create.tfplan
AWS_PROFILE=nova-toll terraform show build/development-create.tfplan
AWS_PROFILE=nova-toll terraform show -json build/development-create.tfplan | \
  jq -e '[.resource_changes[] | select(.change.actions != ["no-op"]) | .change.actions] | all(. == ["create"])'
```

After CloudFront, WAF, IAM-only origins, and non-paging alarms are ready, make
a separate saved plan with only `-var=enable_public_dns=true`. Review that it
adds only `cloudflare_dns_record.apex[0]` before applying that exact plan.

```sh
AWS_PROFILE=nova-toll terraform plan -var-file=development.tfvars \
  -var=enable_public_dns=true \
  -var loader_package_path=build/loader.zip \
  -var publisher_package_path=build/publisher.zip \
  -var agentcore_package_path=build/agentcore.zip \
  -var chat_proxy_package_path=build/chat-proxy.zip \
  -out=build/development-dns.tfplan
AWS_PROFILE=nova-toll terraform show build/development-dns.tfplan
unset CLOUDFLARE_API_TOKEN
```

The proxy Lambda explicitly depends on its inline policy, so the complete plan
applies transaction permission before publishing the new Lambda version.

## Public report launch

The report publisher depends on the CloudFront distribution and `robots.txt`,
so enabling publication in the complete saved plan happens only after the edge
rewrite has deployed. Wait for the distribution, enqueue one watchdog run, and
verify the complete manifest before testing public URLs:

```sh
SITE_DISTRIBUTION="$(AWS_PROFILE=nova-toll terraform output -json public_site | jq -r .distribution_id)"
SITE_BUCKET="$(AWS_PROFILE=nova-toll terraform state show -no-color \
  aws_s3_bucket.site | awk -F' = ' '$1 ~ /^    bucket/ {gsub(/"/, "", $2); print $2; exit}')"
AWS_PROFILE=nova-toll aws --region us-east-1 cloudfront wait distribution-deployed \
  --id "$SITE_DISTRIBUTION"
REPORT_INVOKE="$(mktemp)"
AWS_PROFILE=nova-toll aws --region us-east-1 lambda invoke \
  --function-name toll-v2-report-publisher --invocation-type Event \
  --cli-binary-format raw-in-base64-out --payload '{"trigger":"watchdog"}' \
  "$REPORT_INVOKE"
REPORT_MANIFEST="$(mktemp)"
for attempt in $(seq 1 90); do
  if AWS_PROFILE=nova-toll aws --region us-east-1 s3api get-object \
    --bucket "$SITE_BUCKET" --key tolls/i95-i495/manifest.json \
    "$REPORT_MANIFEST" >/dev/null 2>&1 && \
    jq -e '.publication_format_version == "1.0.0" and .route_count == 685' \
      "$REPORT_MANIFEST" >/dev/null; then
    break
  fi
  sleep 10
done
jq -e '.publication_format_version == "1.0.0" and .route_count == 685' \
  "$REPORT_MANIFEST"
rm -f -- "$REPORT_INVOKE" "$REPORT_MANIFEST"
unset REPORT_INVOKE REPORT_MANIFEST SITE_BUCKET SITE_DISTRIBUTION
```

Check every canonical report and JSON sibling with bounded concurrency, then
deep-check both hostnames, the crawler policy, representative agent families,
and API isolation:

```sh
REPORT_URLS="$(mktemp)"
curl --fail-with-body --silent --show-error https://tollchat.ai/sitemap.xml \
  | grep -o '<loc>[^<]*</loc>' | sed 's#</\?loc>##g' >"$REPORT_URLS"
test "$(wc -l <"$REPORT_URLS")" -eq 685
xargs -P 8 -n 1 sh -c '
  html="$1"
  curl --fail --silent --show-error --head "$html" \
    | grep -qi "^content-type: text/html"
  curl --fail --silent --show-error --head "${html}report.json" \
    | grep -qi "^content-type: application/json"
' _ <"$REPORT_URLS"

REPORT_URL="https://tollchat.ai/tolls/i95-i495/dumfries-dumfries-road-route-234-northbound/tysons-westpark-drive-tysons-corner-northbound/"
REPORT_PAGE="$(mktemp)"
curl --fail-with-body --silent --show-error "$REPORT_URL" >"$REPORT_PAGE"
grep -F '<link rel="canonical" href="'"$REPORT_URL"'">' "$REPORT_PAGE"
grep -F '<link rel="alternate" type="application/json" href="report.json">' "$REPORT_PAGE"
! grep -qi 'noindex\|<script' "$REPORT_PAGE"
curl --fail-with-body --silent --show-error \
  "${REPORT_URL/tollchat.ai/www.tollchat.ai}" >/dev/null
for host in tollchat.ai www.tollchat.ai; do
  curl --fail-with-body --silent --show-error "https://$host/robots.txt" \
    | grep -F 'Sitemap: https://tollchat.ai/sitemap.xml'
done
for agent in OAI-SearchBot Googlebot Claude-SearchBot PerplexityBot bingbot \
  Amzn-SearchBot Applebot DuckAssistBot; do
  curl --fail-with-body --silent --show-error --user-agent "$agent" \
    "$REPORT_URL" >/dev/null
done
curl --fail-with-body --silent --show-error https://tollchat.ai/api/config >/dev/null
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://tollchat.ai/api/chat)" -eq 404
rm -f -- "$REPORT_PAGE" "$REPORT_URLS"
unset REPORT_PAGE REPORT_URL REPORT_URLS
```

## Agent-route measurement launch

Confirm Cloudflare remains DNS-only, generate uniquely recognizable HTML and
JSON requests, invoke the rollup, and inspect only the sanitized saved view.
The WAF logging destination can take several minutes to deliver its first file.

```sh
REPORT_URL="https://tollchat.ai/tolls/i95-i495/dumfries-dumfries-road-route-234-northbound/tysons-westpark-drive-tysons-corner-northbound/"
AWS_PROFILE=nova-toll aws --region us-east-1 wafv2 get-logging-configuration \
  --resource-arn "$(AWS_PROFILE=nova-toll terraform output -raw agent_report_web_acl_arn)"
curl --fail-with-body --silent --show-error --user-agent 'ChatGPT-User Task6Smoke' \
  "$REPORT_URL" >/dev/null
curl --fail-with-body --silent --show-error --user-agent 'ChatGPT-User Task6Smoke' \
  "${REPORT_URL}report.json" >/dev/null
curl --fail-with-body --silent --show-error --head "$REPORT_URL" >/dev/null
AWS_PROFILE=nova-toll aws --region us-east-1 lambda invoke \
  --function-name tollchat-v2-agent-usage-rollup --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/agent-usage-rollup.json
jq -e '.completed_dates | length == 3' /tmp/agent-usage-rollup.json
rm -f /tmp/agent-usage-rollup.json
unset REPORT_URL
```

Open the `tollchat-v2-public-chat` protection pack's **AI Traffic Analysis**
tab for the native 14-day view. In Athena, select the
`tollchat-agent-reports` workgroup and run the Terraform-managed top-routes or
recent-request-times named query. Never export the raw WAF table.

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
events followed by an answer and disclaimer. Cross-origin requests to the
private chat route must fail.

After the private check passes, verify the public edge and warm alias:

```sh
curl --fail-with-body https://tollchat.ai/
curl --fail-with-body https://tollchat.ai/api/config
AWS_PROFILE=nova-toll aws --region us-east-1 lambda get-provisioned-concurrency-config \
  --function-name tollchat-v2-chat-proxy --qualifier live
```

The concurrency status and allocation must be `READY` and `1`. Submit a first
chat only after opting that browser out. First save the consistent aggregate
returned by this command:

```sh
AWS_PROFILE=nova-toll aws --region us-east-1 dynamodb get-item \
  --table-name tollchat-v2-anonymous-sessions \
  --key '{"credential_hash":{"S":"usage#all"}}' \
  --projection-expression 'engaged_sessions, completed_responses' \
  --consistent-read
```

In the public browser's developer console, set and check the owner opt-out,
then click **New chat** to reset the session before submitting the smoke message:

```js
document.cookie = "tollchat_usage_optout=1; Domain=tollchat.ai; Path=/; Max-Age=31536000; Secure; SameSite=Strict";
document.cookie.includes("tollchat_usage_optout=1");
```

The check must return `true`. Rerun the consistent DynamoDB read after the
response completes; the aggregate must be unchanged. Confirm CloudWatch records
the request under `ProvisionedConcurrencyInvocations`, without an on-demand
Lambda initialization. The public Function URL must reject direct unsigned
invocation.

## Rollback

For a report-rendering regression, keep the CloudFront rewrite active, deploy
corrected publisher code with a bumped publication format version, and invoke a
watchdog run to replace the complete generation. If report source content is
unsafe, stop new report writes first:

```sh
AWS_PROFILE=nova-toll aws --region us-east-1 events disable-rule \
  --name toll-v2-committed-i95-loads
AWS_PROFILE=nova-toll aws --region us-east-1 events disable-rule \
  --name toll-v2-report-watchdog
```

Disabling publication does not withdraw existing report objects. The site
bucket is not versioned. A public takedown therefore requires separate approval
to delete the exact `tolls/i95-i495/` prefix and `sitemap.xml`, followed by a
targeted CloudFront invalidation. Do not perform that destructive rollback as
part of an ordinary application rollback.

Disable daily publication before preparing a rollback:

```sh
AWS_PROFILE=nova-toll aws --region us-east-1 events disable-rule \
  --name tollchat-v2-usage-publisher
```

For immediate recovery, set `RELEASE_EVIDENCE` to the original failed release's
pre-apply evidence file. Do not rerun capture. Restore its targets before
running the Terraform rollback; this deliberately creates temporary drift that
the saved-plan deployment below must reconcile:

```sh
(
  set -eu
  : "${RELEASE_EVIDENCE:?set the original failed release evidence path}"
  test "$(wc -l <"$RELEASE_EVIDENCE")" -eq 3
  grep -qx 'lambda_live_function_version=[0-9][0-9]*' "$RELEASE_EVIDENCE"
  grep -qx 'agentcore_runtime_id=[A-Za-z0-9][A-Za-z0-9_-]*' "$RELEASE_EVIDENCE"
  grep -qx 'agentcore_endpoint_live_version=[0-9][0-9]*' "$RELEASE_EVIDENCE"
  LAMBDA_LIVE_FUNCTION_VERSION="$(sed -n 's/^lambda_live_function_version=//p' "$RELEASE_EVIDENCE")"
  AGENTCORE_RUNTIME_ID="$(sed -n 's/^agentcore_runtime_id=//p' "$RELEASE_EVIDENCE")"
  AGENTCORE_ENDPOINT_LIVE_VERSION="$(sed -n 's/^agentcore_endpoint_live_version=//p' "$RELEASE_EVIDENCE")"
  AWS_PROFILE=nova-toll aws --region us-east-1 lambda update-alias \
    --function-name tollchat-v2-chat-proxy --name live \
    --function-version "$LAMBDA_LIVE_FUNCTION_VERSION"
  AWS_PROFILE=nova-toll aws --region us-east-1 bedrock-agentcore-control update-agent-runtime-endpoint \
    --agent-runtime-id "$AGENTCORE_RUNTIME_ID" --endpoint-name preview \
    --agent-runtime-version "$AGENTCORE_ENDPOINT_LIVE_VERSION"
)
```

After the immediate rollback smoke test passes, check out the last accepted
release revision, rebuild it, verify its recorded SHA-256 manifest, and repeat
the saved-plan deployment workflow without recapturing evidence. Restore the old
proxy and public site together so the code and disclosure remain consistent.
The apply must reconcile the Lambda alias and AgentCore endpoint with Terraform
state; rerun the reviewed plan afterward and require it to report no changes.

Deterministic builds restore the exact package bytes; bucket versioning retains
the earlier runtime and proxy objects for 30 days. When rolling back to a
pre-metrics revision, expect the plan to remove the usage publisher, schedule,
alarms, placeholder, and metrics-era public/legal assets. Retain the DynamoDB
`usage#all` aggregate; it is operational history and is not managed as a
Terraform item.

If the application cannot safely serve traffic while rollback is prepared,
set reserved concurrency for `tollchat-v2-chat-proxy` to zero. Terraform ignores
this emergency override so the rollback apply remains fail-closed. After the
rollback smoke test succeeds, explicitly restore the reviewed concurrency:

```sh
AWS_PROFILE=nova-toll aws --region us-east-1 lambda put-function-concurrency \
  --function-name tollchat-v2-chat-proxy \
  --reserved-concurrent-executions 5
```

Database and shared polling/storage infrastructure are not part of application
rollback.
