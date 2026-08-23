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
profile. Review every action before applying that exact file:

```sh
cd infra
AWS_PROFILE=nova-toll terraform init
AWS_PROFILE=nova-toll terraform plan \
  -var loader_package_path=build/loader.zip \
  -var agentcore_package_path=build/agentcore.zip \
  -var chat_proxy_package_path=build/chat-proxy.zip \
  -out=build/release.tfplan
AWS_PROFILE=nova-toll terraform show build/release.tfplan
AWS_PROFILE=nova-toll terraform apply build/release.tfplan
```

Terraform uploads both application packages to versioned S3 keys and pins the
resulting object version IDs in Lambda and AgentCore. Do not apply an unsaved
or unreviewed plan.

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
events followed by an answer and disclaimer. Public or cross-origin requests
to the chat route must fail.

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
  --reserved-concurrent-executions 1
```

Database and shared polling/storage infrastructure are not part of application
rollback.
