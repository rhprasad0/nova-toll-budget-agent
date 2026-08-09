# Public edge context

## Scope

Implement issue #122's default-off public API edge without changing the private
preview or enabling public chat. Work remains local until separately authorized.

## Decisions

- Route CloudFront `/api/*` to the existing proxy through an IAM-protected
  Lambda Function URL and Lambda OAC.
- Default `enable_public_chat` to false; omit the route and its public resources
  when disabled.
- Allow only `GET /api/config`, `POST /api/chat`, and `POST /api/reset`.
- WAF: 32 KiB body limit, 20 combined chat/reset requests per source IP per
  five minutes, sanitized 404/413/429/503 responses, metrics only, no managed
  rule groups, and a public-only default-action kill switch.
- Limit each agent invocation to five executed tool calls and six model calls;
  retain five turns, 2,048 output tokens per model call, five proxy executions,
  and existing 50/55-second deadlines.
- CloudFront uses one origin attempt, a five-second connection timeout, and a
  55-second response timeout.
- Keep prepaid OpenAI usage and spend alerts as an owner-accepted soft boundary;
  defer automated spend cutoff until OpenAI models are approved through Bedrock.
- Do not add a daily IP quota, full WAF logs, sampled requests, or a standalone
  evidence report.

## Existing paths

- `infra/site.tf`: static CloudFront distribution and conditional public edge.
- `infra/variables.tf`: default-off public switch.
- `infra/agentcore.tf`: existing proxy Lambda, private API, and dedicated roles.
- `lambdas/chat_proxy/handler.mjs`: shared API handler; normalize Function URL
  v2 events without changing private API Gateway v1 behavior.
- `agent/agentcore_entrypoint.py`: session runtime and invocation-limit hooks.
- `tests/test_agentcore_infrastructure.py`, `agent/tests/`, and proxy Node tests:
  regression coverage.

## Existing documentation

- `README.md` confirms the public product is pre-launch and the deployed agent
  uses OpenAI directly with a future Bedrock Mantle path.
- `deployment_plan.md` is the launch checklist; its exact hard-spend language
  needs to reflect the owner-approved soft boundary.
- `docs/runbooks/kill-switch.md` currently documents only the service-wide
  Lambda concurrency switch and must stop claiming no public origin exists.

## Dependency map

Browser -> CloudFront/WAF -> signed Lambda Function URL -> existing proxy ->
private AgentCore VPC endpoint -> existing runtime and pricing tools.

No new application dependency or credential is required.
