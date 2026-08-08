# TollChat AgentCore deployment plan

**Status:** implementation complete; AWS deployment and public launch are not authorized by this change.

This plan replaces the Amazon Q draft with an AWS-supported design. A private API Gateway streams a small Lambda proxy, which validates requests and makes IAM-signed `InvokeAgentRuntime` calls through the AgentCore data-plane VPC endpoint.

## Target architecture

```text
Private preview
Owner → Tailscale subnet router → execute-api VPC endpoint → private API Gateway
      → streaming Lambda proxy
      → AgentCore data-plane VPC endpoint → AgentCore Runtime → RDS / OpenAI

Public site
Browser → CloudFront → static S3 page (no chat origin)
```

SSM Parameter Store remains the credential source of truth. The public site remains unchanged static S3/CloudFront content; chat exists only at `preview.tollchat.ai`.

## Phase 1 — Review and package

- [x] Add `bedrock-agentcore` and ADOT 0.18+ dependencies; lock them with `uv.lock`.
- [x] Package direct code for `aarch64-manylinux2014`, including the agent, tools, oracle data, SOP, CA bundle, and locked dependencies.
- [x] Package the Node.js streaming Lambda proxy and its locked AWS SDK separately.
- [x] Keep validation-only placeholder zips, but reject a real runtime deployment unless the ARM64 artifact path is provided.
- [x] Verify the reproducible package locally: 42.5 MiB compressed, 103.1 MiB expanded, SHA-256 `d25654b47de6c122e9e28cb54cb833dd2aa827794a7c3b9017eeb139d52e22a5`, below the 250 MB/750 MB AgentCore limits. Re-record the deployed digest with deployment evidence.

## Phase 2 — Private runtime foundation

- [x] Create two non-overlapping private subnets (`172.31.224.0/24` and `172.31.225.0/24`) in the existing default VPC.
- [x] Add one NAT gateway for OpenAI HTTPS egress and private route-table associations.
- [x] Extend the existing S3 gateway endpoint to the private route table.
- [x] Create separate security groups for the runtime, data-plane endpoint, Lambda proxy, and execute-api endpoint.
- [x] Permit runtime-to-RDS only on TCP 5432 and HTTPS egress for SSM, OpenAI, and AWS telemetry.
- [x] Create `com.amazonaws.us-east-1.bedrock-agentcore` as a private interface endpoint; accept 443 only from the proxy security group.
- [x] Create a private, encrypted, public-blocked artifact bucket.

**Availability note:** one NAT is an accepted preview limitation. Add one NAT and route table per AZ before committing to a multi-AZ public availability objective.

## Phase 3 — Runtime security and application boundary

- [x] Create a dedicated AgentCore role trusted by `bedrock-agentcore.amazonaws.com`, constrained by source account and runtime ARN.
- [x] Grant only artifact read, one SSM parameter read, `pricing_reader` RDS IAM connect, the designated Guardrail, and telemetry writes.
- [x] Create a versioned Bedrock Guardrail with high prompt-attack filtering and content safety filters.
- [x] Implement the native `BedrockAgentCoreApp` entrypoint rather than a custom HTTP server.
- [x] Validate 1–8000 character prompts, cap a microVM session at five turns, guard both input and output, append the estimates disclaimer, and return stable safe errors.
- [x] Create the native `aws_bedrockagentcore_agent_runtime` and a `preview` endpoint using AWS provider 6.47+ with VPC mode, 15-minute idle timeout, and 60-minute lifetime. AgentCore owns the automatically created `DEFAULT` endpoint, so Terraform does not try to recreate it.
- [x] Manage native `aws_bedrockagentcore_resource_policy` resources on both runtime and preview endpoint, explicitly denying invocation unless `aws:SourceVpce` matches.
- [x] Keep `/nova-toll/openai_api_key` in SSM. Do not create an AgentCore credential provider or delete the parameter.

## Phase 4 — Tailscale-only preview

- [x] Create a Lambda proxy with a separate role allowed only to invoke the one runtime and preview endpoint, and stop sessions on that runtime.
- [x] Validate UUID sessions and request bodies before invoking AgentCore; expose only fixed tool labels/statuses and the guarded final answer.
- [x] Reserve five Lambda executions and retain proxy logs for 30 days.
- [x] Create an execute-api interface endpoint whose security group accepts port 443 only from the existing Tailscale router.
- [x] Keep the tailnet grant owner-only (`rhprasad0@github`) and add a policy test proving the CI identity cannot reach preview HTTPS.
- [x] Create a private REST API and custom domain with independent `aws:SourceVpce` allow/deny policies, Lambda response streaming, and same-origin preview assets.
- [x] Add `preview.tollchat.ai` to the ACM certificate and create an unproxied DNS record for the execute-api endpoint.
- [ ] Apply Terraform, approve the advertised VPC route in Tailscale if needed, and verify that a tailnet client succeeds while a non-tailnet client times out.

## Phase 5 — Frontend

- [x] Keep `site/index.html` byte-for-byte unchanged and build a dedicated accessible `preview.html` page.
- [x] Use `crypto.randomUUID()`, render all model content with `textContent`, expose activity/errors via live regions, enforce the 8000-character client limit, and provide a new-chat action.
- [x] Consume validated NDJSON incrementally so tool lifecycle states render before the final answer.

## Phase 6 — Public path (not implemented)

- [x] Remove the dormant CloudFront chat origin, WAF, and `enable_public_chat` scaffold so the main page cannot expose preview accidentally.
- [x] Alarm on proxy errors and active sessions through the existing SNS topic.
- [x] Extend the existing CloudTrail advanced selectors to capture AgentCore runtime data events without losing protected S3 object events.
- [ ] Configure and verify an OpenAI-side daily/project budget. AWS Budgets does not control spend billed by OpenAI.
- [ ] Complete and approve every item in `docs/public-agent-launch-gate.md`, including privacy/retention, legal text, IAM simulation, alarm delivery, kill switch, rollback, and end-to-end eval evidence.
- [ ] Design and authorize a separate public path only after the launch gate is complete.

## Phase 7 — Verification and evidence

Run locally and in CI:

```bash
uv sync --locked
uv run pytest
npm --prefix lambdas/chat_proxy ci
npm --prefix lambdas/chat_proxy test
uv run ruff check .
uv run ruff format --check .
uv run pyright
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
./scripts/build_zips.sh
gitleaks git --redact
```

After an authorized private deployment, add only successful, technically representative evidence to `eval/results/` and update its README. Required evidence: package digest/size, Terraform plan, private/non-private reachability, known-route response and disclaimer, blocked prompt injection, oversized input, five-turn cutoff, IAM simulation, alarm delivery, kill-switch drill, and rollback drill. Failed or superseded runs stay out of the curated directory.

## Phase 8 — Public operations

- Review AgentCore and proxy error/session metrics daily during the first week.
- Review API Gateway and proxy metrics without copying user content into tickets.
- Run the existing deterministic and simulated suites before every runtime version promotion; do not create duplicate evaluator implementations unless a measured gap requires one.
- Retain the previous reviewed artifact for rollback.
- When Bedrock Mantle is approved and passes the full suite, switch the model backend, remove OpenAI/SSM permission, and remove the NAT only after confirming every remaining runtime dependency has a private AWS path.

## Rollback and kill switch

The immediate kill switch sets the proxy Lambda reserved concurrency to zero. The public static site has no chat route. Rollback deploys the last reviewed AgentCore artifact and then exercises the private smoke/evaluation suite. Exact commands are in `docs/runbooks/kill-switch.md` and `docs/runbooks/rollback.md`.

## AWS references

- [Deploy AgentCore Runtime from source code](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-code-deploy.html)
- [AgentCore Runtime versioning and endpoints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)
- [Configure AgentCore Runtime for VPC access](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)
- [AgentCore Runtime IAM permissions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)
- [Invoke an AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html)
- [AgentCore resource-based policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html)
- [AgentCore generated observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)
- [CloudTrail data-event resource types](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html)
- [Private REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-private-apis.html)
- [Private custom domain names](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-private-custom-domains.html)
- [REST API response streaming](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-streaming.html)
