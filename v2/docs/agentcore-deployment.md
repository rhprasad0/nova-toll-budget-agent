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

```sh
cd infra
export CLOUDFLARE_API_TOKEN="$(AWS_PROFILE=nova-toll aws --region us-east-1 \
  ssm get-parameter --name /nova-toll/cloudflare-api-token --with-decryption \
  --query Parameter.Value --output text)"
AWS_PROFILE=nova-toll aws --region us-east-1 lambda put-function-concurrency \
  --function-name tollchat-v2-chat-proxy \
  --reserved-concurrent-executions 5
AWS_PROFILE=nova-toll terraform init
AWS_PROFILE=nova-toll terraform plan \
  -var loader_package_path=build/loader.zip \
  -var agentcore_package_path=build/agentcore.zip \
  -var chat_proxy_package_path=build/chat-proxy.zip \
  -target=aws_s3_object.index \
  -target=aws_s3_object.faq \
  -target=aws_s3_object.privacy \
  -target=aws_s3_object.usage \
  -out=build/usage-disclosure.tfplan
AWS_PROFILE=nova-toll terraform show build/usage-disclosure.tfplan
AWS_PROFILE=nova-toll terraform apply build/usage-disclosure.tfplan
curl --fail-with-body https://tollchat.ai/privacy.txt
curl --fail-with-body https://tollchat.ai/faq.html
AWS_PROFILE=nova-toll terraform plan \
  -var loader_package_path=build/loader.zip \
  -var agentcore_package_path=build/agentcore.zip \
  -var chat_proxy_package_path=build/chat-proxy.zip \
  -out=build/release.tfplan
AWS_PROFILE=nova-toll terraform show build/release.tfplan
AWS_PROFILE=nova-toll terraform apply build/release.tfplan
unset CLOUDFLARE_API_TOKEN
```

The one-time targeted plan is required for the first usage-counter release so
the disclosure and hidden placeholder reach the public site before collection
can start. Confirm the updated privacy and FAQ text is live before creating the
full release plan. Later releases skip that targeted plan.

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
chat from a new browser session and confirm CloudWatch records it under
`ProvisionedConcurrencyInvocations`, without an on-demand Lambda initialization.
The public Function URL must reject direct unsigned invocation.

## Rollback

Check out the last accepted release revision, rebuild it, verify its recorded
SHA-256 manifest, and repeat the saved-plan workflow. Deterministic builds
restore the exact package bytes; bucket versioning retains the earlier runtime
and proxy objects for 30 days. Review the rollback plan to confirm it changes
only the two packages, the AgentCore runtime version/endpoint, and dependent
deployment metadata.

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
