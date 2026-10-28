# MCP server for Muse (development only)

`https://mcp.tollchat.ai/mcp` is an authless MCP server for Muse, Meta's personal
agent. It has three tools, `find_toll_ramps`, `estimate_annual_tolls` and `estimate_salary`, and serves its connect guide at `/` and
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
./e2e.sh                       # throwaway PostGIS (real oracle catalog) and DynamoDB Local
cargo run                      # http://127.0.0.1:8080, real AWS, needs the env below
```

`cargo run` reads `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_CA_BUNDLE_PATH`, `DB_USER`,
`PRICING_DB_USER` and `LOOKUP_TABLE`, the same variables the Lambda gets from `mcp.tf`.

The server signs RDS IAM tokens locally. On its first `estimate_salary` call it
reads the OpenWeb Ninja key from the SSM SecureString
`/nova-toll/openwebninja-api` (so `cargo run` also needs `ssm:GetParameter` on
it), then calls `https://api.openwebninja.com`. Its security group therefore
allows egress to RDS and HTTPS, the latter through the private subnets' NAT
path. Each salary call is a paid OpenWeb Ninja lookup. Before each one, the server
counts it in the DynamoDB table `tollchat-v2-mcp-lookups-dev` (one item per UTC
day, through the VPC's gateway endpoint) and stops at 3,333 a day, $10 at
$0.003 a lookup (`DAILY_SALARY_LOOKUPS` in `src/lib.rs`), answering
`daily_limit`. If the count fails, the call fails without a lookup.
Each Lambda instance keeps the key it read, so after rotating the parameter,
redeploy the code (with its sync) to replace the warm instances.

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
   in computed fields: the security group's `egress` (now listing its RDS and HTTPS rules),
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

Server 0.5.0 and later will not start without `LOOKUP_TABLE` set on the function,
so apply the MCP resources before deploying it.

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
`main`, run the step 6 sync, then re-run the failed delivery jobs. Merge nothing
else in between.

- **Removed resources** are no longer in `MCP_TARGETS`; add each removed address
  to `-target` yourself, or its destroy is never planned and delivery keeps
  stopping at `phase_boundary`.
- **The sync** picks up computed drift that delivery would reject as
  `incomplete_or_drift`: route and integration changes move the stage's
  `deployment_id`, and adding or removing a security group rule changes the
  group's `egress`.
- **Read grants** in `infra/mcp-delivery.tf` are added before the `v2/infra`
  apply and removed after it, because plans refresh every MCP resource still in
  state.
- **Removals go code first:** never remove infrastructure that the deployed
  binary still needs; check its `CodeSha256` against a reproducible build first.
- **Additions go infrastructure first:** apply what the new binary needs (for
  0.5.0: the foundation's DynamoDB endpoint policy and read grants, then the
  counter table, grants, HTTPS egress and `LOOKUP_TABLE`) before deploying it.

## Verify

- `curl -s https://mcp.tollchat.ai/` returns the connect guide. Its `curl`
  examples should all return 200.
- A burst of more than five requests a second gets some 429s (stage throttle).
- Logs, kept 7 days, hold the tool, status and duration, and for a failure its
  `stage` and `code`: `aws logs tail /aws/lambda/tollchat-v2-mcp-server-dev --since 1h`.
  Toll calls never log their coordinates, routes or schedules.
- **Salary calls** also log, under `span`, the `job_title`, `location` and
  `years_of_experience` sent, OpenWeb Ninja's `upstream_status`, `upstream_ms`
  and `request_id` (quote it to OpenWeb Ninja support), and the
  `matched_job_title` and `matched_location` it answered for. The key is
  never logged. Failure codes: `key_<SSM error code>` (such as
  `key_AccessDeniedException` or `key_ParameterNotFound`), `key_no_response`,
  `key_empty_value`, `url`, `connect`, `request`,
  `http_<status>` (`http_429` is a rate limit or exhausted quota), `body`,
  `upstream`, `timeout`, and `salary_budget` stage failures (the counter is
  unavailable). The counter is the upper bound on billed lookups; today's:
  `aws dynamodb get-item --table-name
  tollchat-v2-mcp-lookups-dev --key "{\"day\":{\"N\":\"$(( $(date -u +%s) / 86400 ))\"}}"`.
  Run these in CloudWatch Logs Insights on
  `/aws/lambda/tollchat-v2-mcp-server-dev` (or with `aws logs start-query`):

  ```text
  # Calls, and lookups OpenWeb Ninja answered (a lower bound on billed ones), per day
  filter fields.tool = "estimate_salary"
  | stats count(*) as calls, count(span.upstream_status) as answered,
      pct(fields.elapsed_ms, 90) as p90_ms by bin(1d)

  # How calls ended
  filter fields.tool = "estimate_salary"
  | stats count(*) as calls by fields.status, fields.code, span.upstream_status

  # Places Glassdoor matched to somewhere else (status ambiguous_location)
  filter fields.tool = "estimate_salary" and fields.status = "ambiguous_location"
  | stats count(*) as calls by span.location, span.matched_location

  # Most asked-about jobs
  filter fields.tool = "estimate_salary"
  | stats count(*) as calls by span.job_title, span.location
  | sort calls desc | limit 20
  ```
- **Drop accounting.** Compare per-minute API Gateway requests with Lambda
  invocations (kept 15 days at one-minute resolution, no request content):

  ```bash
  API=$(aws --region us-east-1 apigatewayv2 get-apis --query "Items[?Name=='tollchat-v2-mcp-server-dev'].ApiId" --output text)
  for m in Count 4xx 5xx; do aws --region us-east-1 cloudwatch get-metric-statistics --namespace AWS/ApiGateway \
    --metric-name $m --dimensions Name=ApiId,Value=$API Name=Stage,Value='$default' \
    --start-time START --end-time END --period 60 --statistics Sum --output text; done
  for m in Invocations Errors Throttles; do aws --region us-east-1 cloudwatch get-metric-statistics --namespace AWS/Lambda \
    --metric-name $m --dimensions Name=FunctionName,Value=tollchat-v2-mcp-server-dev \
    --start-time START --end-time END --period 60 --statistics Sum --output text; done
  ```

  `Count` above `Invocations` with matching `4xx` means requests stopped at the
  gateway (usually the 429 throttle); `5xx` or Lambda `Errors` are server
  failures. A drop the client saw with neither is outside TollChat: requests
  that never reach API Gateway are invisible here by design, since there are no
  access logs. Lambda's own `START`/`REPORT` log lines give each invocation's
  time to the millisecond for seven days.

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
