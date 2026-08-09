# Issue 125 actionable alarms context

## Requirements and decisions

- Add actionable proxy failure/latency, AgentCore session, toll freshness, and
  RDS CPU/memory/connection/credit alarms through the existing SNS topic.
- Reuse the existing OpenAI project soft-budget alert; AWS Budgets cannot
  monitor spend billed directly by OpenAI.
- Apply and verify the reviewed Terraform in the private-preview account.
- Curate only metadata-only successful evidence and leave issue #125 open until
  the supporting commit is merged.

## Existing patterns

- `infra/observability.tf` owns the SNS topic, freshness alarms, and current
  proxy/session alarms.
- The proxy returns safe errors for caught request and stream failures, so the
  Lambda `Errors` metric alone misses representative failures.
- Loader `LOAD_OK` logs already feed the `NovaToll/LoadSuccess` freshness
  metric through a CloudWatch Logs metric filter.
- Infrastructure contracts live in `tests/test_agentcore_infrastructure.py`;
  proxy behavior uses Node's built-in test runner.

## Baseline and thresholds

The 14-day private-preview baseline observed proxy p99 up to 48.7 seconds,
AgentCore active sessions up to 6, RDS CPU up to 24.5%, FreeableMemory p01 at
65.4 MiB, 3 CloudWatch database connections, 79 PostgreSQL max connections,
and a full 288 CPU-credit balance. Initial thresholds follow the approved plan
and will be revisited by the separate load-test gate.

## AWS documentation findings

- AgentCore publishes `ActiveSessionCount` once per minute in
  `AWS/Bedrock-AgentCore` with `Service=AgentCore.Runtime`.
- Lambda `Duration` supports percentile statistics; latency alarms use p99.
- RDS CPU-credit metrics publish every five minutes.
- Confirmed SNS subscriptions receive alarm actions; CloudWatch alarm history
  records successful SNS action execution.
