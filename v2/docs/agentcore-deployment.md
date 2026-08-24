# AgentCore deployment

Deployments are manual. CI builds and tests the application but never runs a
Terraform plan or apply.

## Build and review

From `v2/`:

```sh
uv sync --locked
uv run pytest
npm ci --prefix lambdas/chat_proxy
npm test --prefix lambdas/chat_proxy
./scripts/build_loader_zip.sh
./scripts/build_agentcore_zips.sh
(cd infra/build && sha256sum --check AGENTCORE_SHA256SUMS)
```

Create a saved plan with the reviewed packages and the explicit production
profile. Load the Cloudflare token from SSM only into the Terraform process
environment, then review every action before applying that exact file:

Before the first usage-counter release, update and verify the retained v1
DynamoDB endpoint policy. This must finish before any v2 proxy code containing
transactional counters is deployed:

```sh
mkdir -p ../v1/infra/build
(
  cd ../v1/infra
  AWS_PROFILE=nova-toll terraform init
  AWS_PROFILE=nova-toll terraform plan \
    -target=aws_vpc_endpoint.dynamodb \
    -out=build/usage-permissions.tfplan
  AWS_PROFILE=nova-toll terraform show build/usage-permissions.tfplan
  AWS_PROFILE=nova-toll terraform apply build/usage-permissions.tfplan
  AWS_PROFILE=nova-toll terraform state show aws_vpc_endpoint.dynamodb \
    | grep -F 'dynamodb:TransactWriteItems'
)
```

Then enter `v2/infra` and initialize the v2 state for every release:

```sh
cd infra
export CLOUDFLARE_API_TOKEN="$(AWS_PROFILE=nova-toll aws --region us-east-1 \
  ssm get-parameter --name /nova-toll/cloudflare-api-token --with-decryption \
  --query Parameter.Value --output text)"
AWS_PROFILE=nova-toll aws --region us-east-1 lambda put-function-concurrency \
  --function-name tollchat-v2-chat-proxy \
  --reserved-concurrent-executions 5
AWS_PROFILE=nova-toll terraform init
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

After those one-time prerequisites, create and apply the complete saved release
plan. Later releases start here after initialization:

```sh
AWS_PROFILE=nova-toll terraform plan \
  -var loader_package_path=build/loader.zip \
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

The one-time v1 permission plan and direct disclosure upload are required for
the first usage-counter release. Confirm the v1 transaction permission and the
public privacy and FAQ text before creating the full release plan. The proxy
Lambda explicitly depends on its inline policy, so the complete plan applies
the v2 transaction permission before publishing the new Lambda version. Verify
that live policy after apply. Later releases skip the v1 targeted plan and
direct disclosure upload.

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

Disable daily publication before preparing a rollback:

```sh
AWS_PROFILE=nova-toll aws --region us-east-1 events disable-rule \
  --name tollchat-v2-usage-publisher
```

Check out the last accepted release revision, rebuild it, verify its recorded
SHA-256 manifest, and repeat the saved-plan workflow. Restore the old proxy and
public site together so the code and disclosure remain consistent.
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
