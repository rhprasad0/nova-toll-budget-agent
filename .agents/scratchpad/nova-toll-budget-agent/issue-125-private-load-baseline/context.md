# Context

## Summary

Issue #125 requires a short private load test while toll ingestion writes to RDS,
followed by rollout thresholds grounded in the observed baseline. The approved
profile is three requests per worker across five concurrent workers (15 total).

## Existing documentation

- `AGENTS.md` requires an isolated worktree, a ready PR only with authorization,
  SSM-backed credentials, curated passing evidence, and Gitleaks before commit.
- `README.md` describes the Python 3.13/uv workflow and deployed AWS environment.
- `docs/runbooks/canonical-smoke.md` defines the private browser contract and
  metadata-only evidence policy.
- `docs/runbooks/alarms.md` defines the current launch alarm thresholds.

## Relevant implementation

- `scripts/smoke_agentcore_canonical.py` owns the exact browser-response validator.
- `scripts/smoke.sh --fire` proves the fetcher-to-loader path but also publishes an
  SNS message, so the load test will invoke the fetcher directly instead.
- `infra/lambda.tf` caps the chat proxy and loader at five concurrent executions.
- `infra/observability.tf` defines the latency, AgentCore session, and RDS alarms.

## Dependency map

Private HTTP requests -> chat proxy -> AgentCore -> RDS pricing reader

Async fetcher invoke -> encrypted raw S3 object -> loader -> RDS pricing writer

Both paths -> CloudWatch metrics/logs -> metadata-only load report

## Constraints

- Use only the standard library and existing AWS CLI.
- Fail closed if telemetry, deployment identity, ingestion overlap, or response
  validation is incomplete.
- Never curate a failed or superseded run.
- Do not resize RDS from one short run; a breach routes through issue #95.
