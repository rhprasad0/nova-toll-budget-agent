# TollChat v1 (retired)

The v1 application is retired. Its site, DNS, AgentCore runtime, chat proxy,
loader, sessions, telemetry, deployment roles, and operational controls no
longer exist. Do not deploy or operate the historical application source in
this directory.

The retained Terraform is shared infrastructure still used by v2:

- VDOT fetch schedules and raw S3 storage;
- PostgreSQL RDS and private networking;
- shared VPC endpoints, artifact storage, alerting, audit, and Terraform state;
- the Tailscale bridge to RDS and the private v2 preview.

The current application, deployment guide, tests, and database contracts live
under [`v2/`](../v2/).

## Retained checks

CI keeps only source checks that remain meaningful for the historical code and
shared foundation:

```sh
uv sync --locked
uv run python scripts/check_agent_contract_versions.py HEAD^
uv run ruff check .
uv run ruff format --check .
uv run pyright
for file in agent-sops/*.sop.md; do scripts/validate-sop.sh "$file"; done
```

Tests and runbooks tied to removed application infrastructure were removed with
the resources they exercised. Historical evaluation reports under
`eval/results/` remain evidence of v1 behavior, not claims about the live v2
system.

## Shared infrastructure

See [`docs/poller-spec.md`](docs/poller-spec.md) for the deployed polling and
foundation contract. Terraform changes are manual: create and review a saved
plan locally with the `nova-toll` AWS profile, then apply that exact plan. CI
does not plan or apply infrastructure.

SSM Parameter Store remains the source of truth for credentials used by the
retained system. Never place credentials in local files or Terraform state.

Historical project source is available under the
[Apache License 2.0](../LICENSE).
