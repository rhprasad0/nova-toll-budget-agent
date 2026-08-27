# TollChat v2

This directory contains TollChat's deployed application, tests, evals, and
application infrastructure. Shared production foundations live in `../infra`.

## Runtime boundaries

- [Current-price tool](agent_tools/get_current_toll_price.py) and its
  [deterministic pricing domain](agent_tools/current_price_domain.py)
- [Annual toll-commute affordability tool](agent_tools/get_annual_toll_ballpark.py)
- [Directed routing contract](db/oracle/CONTRACT.md),
  [schema](db/oracle/schema.sql), and
  [reviewed source-data builder](oracle/build_oracle_data.py)
- [Agent-facing route validation](agent_tools/validate_toll_route.py)

## Database bootstrap

- [PostgreSQL schema](db/schema.sql)
- [IAM-authenticated database roles](db/roles.sql)
- [Missing I-95/495 OD validation](eval/results/i95-missing-od-pricing.md) and
  [production proxy mapping and pricing views](db/analysis.sql)

The independently deployable `pricing` application schema is at **1.3.0**. Its
version is stored in `pricing.schema_version`; CI tests
the bootstrap, privileges, analytics, cleanup guard, and monotonic SemVer policy
on PostgreSQL 17.9.

The independently versioned `oracle` schema is at **1.13.1**. It installs
core PostGIS 3.5.x inside `oracle`, loads the directed toll-access graph, and
exposes route validation plus bounded prompt-point retrieval to `tollchat_agent`
and internal pricing operations to `pricing_caller`.
Regenerate and verify its checked-in SQL seed and frontend coverage snapshot with:

```sh
uv run python oracle/build_oracle_data.py
uv run python oracle/build_oracle_data.py --check
```

For a new database, install pricing before oracle:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/001_create_pricing_schema.sql
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/003_create_oracle_schema.sql
```

For an existing database, read both `schema_version` tables and apply only the
matching guarded [`*_upgrade_*` migrations](db/migrations/) in dependency and
version order. Never edit or skip a released migration.

## Verify the build

From `v2/`, run the core application checks and deterministic release builds:

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python eval/run_evaluation.py --check
uv run coverage run -m pytest
uv run coverage report
node --test tests/*.mjs
npm ci --prefix lambdas/chat_proxy
npm test --prefix lambdas/chat_proxy
uv run python oracle/build_oracle_data.py --check
./scripts/build_loader_zip.sh
./scripts/build_publisher_zip.sh
./scripts/build_agentcore_zips.sh
(cd infra/build && sha256sum --check AGENTCORE_SHA256SUMS)
```

Database contract and migration checks require PostgreSQL 17 with PostGIS 3.5.
From the repository root, pass the pull request's base revision to:

```sh
v2/scripts/run_db_tests.sh BASE_GIT_REF
```

Production deployment is manual; CI never runs `terraform plan` or `apply`.
Follow the [deployment runbook](RUNBOOK.md) for the reviewed saved-plan,
smoke-test, rollout, and rollback procedures.

The public interface at `tollchat.ai` uses a private S3 origin for the v2 site
and an IAM-authenticated streaming Lambda URL behind CloudFront and WAF. The
same proxy and AgentCore runtime remain available through the private preview.

The `get_current_toll_price` Strands tool accepts stable origin and destination
point IDs plus the supported pricing profile. It validates the route through
the oracle and prices I-66 from current observations during its published
tolling windows and at $0 outside them, I-95/I-495 from current observations,
and Dulles Greenway and Dulles Toll Road from their published schedules. I-95/I-495
components use 10-minute bins and retain recent movement, prior-week context,
and the provisional `identity_proxy_v1` label for modeled OD prices. Mixed
facility trips preserve route order and return one summed total. Callers do not
submit route plans or pricing components.

Its generated input, output, progress-event, and safe-error schemas are locked
by `agent_tools/contract-manifest.json`. Contract changes require a new,
increasing SemVer release and digest; CI rejects rewrites of published releases.

The primary `get_annual_toll_ballpark` experience helps job seekers estimate
how the tolled portion of a commute affects income. It combines recent
same-date P25/P50/P90 toll scenarios with gross annual income, a fixed one-third
tax assumption, and a fixed TollChat assumption of `$0.685` per straight-line
priced-leg mile. It excludes
untolled commute segments and remains a rough starting point rather than a
quote, tax calculation, forecast, or financial plan. Current-price lookup is
the secondary experience.

The v2 Strands agent in `agent/` loads the bounded entry/exit labels, aliases,
and coordinates from RDS once at startup, then exposes exactly the current-price
and annual-affordability tools. It fails startup if that prompt data is unavailable
or invalid.

Its final system-prompt assembly and prompt-point renderer/input contract are
independently locked by `agent/contract-manifest.json` and reported in traces as
`tollchat.system_prompt_version` and `tollchat.system_prompt_renderer_version`.
Each request also reports `tollchat.system_prompt_sha256` for the exact rendered
prompt, including its date and RDS points. Contract changes require a new,
increasing SemVer release and digest; CI rejects rewrites of published releases.
Use patch releases for corrections that preserve behavior, minor releases for
compatible behavior changes, and major releases for incompatible changes.

### Local agent console

The loopback-only browser frontend streams the v2 agent's Markdown replies,
emoji, tool activity, metrics, and raw Strands events without browser analytics
or on-disk conversation storage. It also serves the FAQ and a checked-in map of
supported toll-road access points beneath four annual toll ballparks to
Washington. From `v2/`, configure the
same AWS and database environment used by the live agent tests, then run:

```sh
AWS_PROFILE=nova-toll AWS_DEFAULT_REGION=us-east-1 \
  uv run python -m agent.dev_chat
```

Open <http://127.0.0.1:8000>. The agent reads its OpenAI credential from SSM;
the Boto3 login provider refreshes the `nova-toll` profile's temporary
credentials without writing them to a project file. Run `aws login --profile
nova-toll` again when its login session expires after up to 12 hours. Required
database variables are `DB_HOST`, `DB_PORT`, `DB_NAME`, and
`DB_CA_BUNDLE_PATH`. If needed, `scripts/build_loader_zip.sh` creates the
verified RDS CA bundle at `infra/build/loader/rds-ca-bundle.pem`.

Its stable developer prompt uses OpenAI's explicit provider-managed prompt cache
with a 30-minute TTL. Strands exposes cache reuse through
`AgentResult.metrics.accumulated_usage` as `cacheReadInputTokens` and
`cacheWriteInputTokens`; toll prices, annual ballparks, final answers, and RDS
prompt-point queries are not application-cached.

The v2 loader under `v2/lambdas/loader` is the sole pricing loader. Native S3
events reach it through EventBridge; the retired loader has no trigger or
deployed function.
