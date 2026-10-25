# MCP server for Muse (development only)

`https://mcp.tollchat.ai/mcp` is an authless MCP server for Muse, Meta's personal
agent. It has one tool, `find_toll_ramps`, and serves its connect guide at `/` and
its privacy notice at `/privacy`. The code is in
[`v2/lambdas/mcp_server/`](../lambdas/mcp_server/), and the resources are in
[`v2/infra/mcp.tf`](../infra/mcp.tf). It runs only in the development account
(`903859731897`) against the development database.

**An administrator applies every MCP resource change and deploys the code.**
Release delivery only reads the MCP resources: the plan and delivery roles can
refresh them ([`infra/mcp-delivery.tf`](../../infra/mcp-delivery.tf)) but not
change them, so their plans must see the resources as no-ops. Terraform creates
the Lambda from the shared placeholder package and ignores its code afterwards.

## Local development

Rust comes from `v2/lambdas/mcp_server/rust-toolchain.toml`. From that directory:

```bash
./e2e.sh                       # PostGIS + DynamoDB Local; SearchText is stubbed
cargo run                      # http://127.0.0.1:8080, real AWS, needs the env below
```

`cargo run` reads `LOOKUP_TABLE`, `DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_CA_BUNDLE_PATH`, `DB_USER` and `PRICING_DB_USER`, the same variables the
Lambda gets from `mcp.tf`.

## Build

```bash
v2/scripts/build_mcp_server_zip.sh   # writes v2/lambdas/mcp_server/target/lambda/mcp-server.zip
```

The build runs `cargo build` inside a digest-pinned Amazon Linux 2023 image, the
OS `provided.al2023` runs, so only Docker is needed and the binary is
reproducible. It adds the pinned RDS CA bundle.

## Plan variables

Every MCP plan below runs from a clean checkout of `main`, with development
administrator credentials, using the same inputs as the trusted plan:

```bash
W="$(mktemp -d)"
terraform -chdir=infra init -input=false -lockfile=readonly -backend-config=backend.development.hcl
terraform -chdir=infra output -json foundation | jq '{foundation: .}' >"$W/foundation.tfvars.json"
terraform -chdir=v2/infra init -input=false -lockfile=readonly -backend-config=backend.development.hcl
terraform -chdir=v2/infra output -json release_state >"$W/release-state.json"
python3 v2/scripts/blue_green.py inputs --previous "$W/release-state.json" >"$W/release-slots.tfvars.json"
VARS=(-var-file=development.tfvars -var-file="$W/foundation.tfvars.json" -var-file="$W/release-slots.tfvars.json")
MCP_TARGETS=(
  -target='aws_cloudwatch_log_group.mcp_server[0]'
  -target='aws_iam_role.mcp_server[0]'
  -target='aws_iam_role_policy_attachment.mcp_server_vpc[0]'
  -target='aws_iam_role_policy.mcp_server[0]'
  -target='aws_dynamodb_table.mcp_lookups[0]'
  -target='aws_security_group.mcp_server[0]'
  -target='aws_vpc_security_group_ingress_rule.rds_from_mcp_server[0]'
  -target='aws_vpc_security_group_egress_rule.mcp_server_to_rds[0]'
  -target='aws_vpc_security_group_egress_rule.mcp_server_https[0]'
  -target='aws_lambda_function.mcp_server[0]'
  -target='aws_apigatewayv2_api.mcp[0]'
  -target='aws_apigatewayv2_integration.mcp[0]'
  -target='aws_apigatewayv2_route.mcp'
  -target='aws_apigatewayv2_stage.mcp[0]'
  -target='aws_lambda_permission.mcp[0]'
  -target='aws_acm_certificate.mcp[0]'
  -target='aws_apigatewayv2_domain_name.mcp[0]'
  -target='aws_apigatewayv2_api_mapping.mcp[0]'
)
```

Review every saved plan and apply that exact file.

## Bootstrap (once)

The trusted PR plan runs **main's** `v2/infra`, so it cannot see a PR's new MCP
resources. Merge first, then apply from `main`:

1. **Merge** the PR once its checks pass. Its development delivery then stops at
   `phase_boundary` before applying anything, because the MCP resources do not
   exist yet. Until step 7, every delivery and every trusted PR plan fails the
   same way, so **merge nothing else until then**.
2. **Foundation:** apply `infra/` for development. This adds the read-only MCP
   policies to the plan and delivery roles, and the counter table to the
   DynamoDB gateway endpoint policy.
3. **Certificate:** `terraform -chdir=v2/infra plan -input=false "${VARS[@]}"
   -target='aws_acm_certificate.mcp[0]' -out="$W/certificate.tfplan"`. After the
   apply, read the validation record with
   `aws acm describe-certificate --certificate-arn ARN --query 'Certificate.DomainValidationOptions[0].ResourceRecord'`,
   add it to Cloudflare as a DNS-only CNAME, and wait until the certificate is
   `ISSUED`.
4. **Everything else:** `terraform -chdir=v2/infra plan -input=false "${VARS[@]}"
   "${MCP_TARGETS[@]}" -out="$W/mcp.tfplan"`. It must only create resources,
   all in account `903859731897`, apart from the existing certificate.
5. **Code:** deploy it as described in [Deploy code](#deploy-code), including the
   sync.
6. **Sync everything:** run the same plan with `-refresh-only`. Expect drift only
   in computed fields: the security group's `egress` (now listing its two rules),
   the certificate's `renewal_eligibility` and `in_use_by`, and the stage's
   `deployment_id`. Apply it. A second `-refresh-only` plan must show no drift.
7. **Release:** re-run the merge's failed delivery jobs (as the original actor),
   then re-run any open PR's `trusted-development-plan`. Both must pass with the
   MCP resources as no-ops.
8. **Go live:** add a DNS-only Cloudflare CNAME from `mcp` to the domain's
   regional target (`aws apigatewayv2 get-domain-name --domain-name mcp.tollchat.ai
   --query 'DomainNameConfigurations[0].ApiGatewayDomainName'`). This is the
   public on-switch; delete it to take the server offline.

## Deploy code

```bash
v2/scripts/build_mcp_server_zip.sh
aws --region us-east-1 lambda update-function-code \
  --function-name tollchat-v2-mcp-server-dev \
  --zip-file fileb://v2/lambdas/mcp_server/target/lambda/mcp-server.zip --query CodeSha256
aws --region us-east-1 lambda wait function-updated --function-name tollchat-v2-mcp-server-dev
```

New code changes the function's computed fields, and release delivery rejects
that drift as `incomplete_or_drift`. **Sync right away:** save a
`-refresh-only` plan with `-target='aws_lambda_function.mcp_server[0]'`, check
that it reports drift only in `code_sha256`, `last_modified` and
`source_code_size`, and apply that exact file. The certificate's managed
renewals need the same sync for `aws_acm_certificate.mcp[0]`.

## Change MCP resources

Follow the bootstrap order: merge the reviewed change, and its delivery stops at
`phase_boundary`. Apply a plan targeting only the changed MCP addresses from
`main`, run the step 6 sync (route and integration changes move the stage's
`deployment_id`), then re-run the failed delivery jobs. Merge nothing else in
between.

## Verify

- `curl -s https://mcp.tollchat.ai/` returns the connect guide. Its `curl`
  examples should all return 200.
- A burst of more than five requests a second gets some 429s (stage throttle).
- Logs, kept 7 days, hold only the tool, status and duration:
  `aws logs tail /aws/lambda/tollchat-v2-mcp-server-dev --since 1h`.
- The daily counter is item `day = floor(epoch / 86400)` in
  `tollchat-v2-mcp-lookups-dev`; at 1,000 lookups the tool returns
  `daily_lookup_limit` until 00:00 UTC.

## Connect Muse

**Muse Code** (`~/.config/muse/settings.json`):

```json
{
  "schema_version": 1,
  "mcp_servers": {
    "tollchat": { "transport": "streamable_http", "url": "https://mcp.tollchat.ai/mcp", "mode": "optional" }
  }
}
```

**Muse app:** it has no MCP URL field. Ask it to build a Custom Connector:

> Create a custom connector for TollChat, a Northern Virginia toll-ramp finder.
> Its documentation is at https://mcp.tollchat.ai/ and its privacy notice is at
> https://mcp.tollchat.ai/privacy. Follow the documentation exactly, then save it
> as a reusable skill.
