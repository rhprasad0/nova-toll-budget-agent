# TollChat v2

This directory is the exclusive home for TollChat's from-scratch v2,
including its future code, tests, evals, infrastructure, and documentation.

The complete live implementation lives in
[`v1/`](../v1/) and keeps its existing build and deployment behavior. V2 has no
compatibility or dependency contract with it.
Reuse code only through an explicit future change that copies or reintroduces
the needed behavior here.

Documents in `v1/` remain historical reference material until v2 deliberately
adopts them.

## Adopted contract

- [Current pricing MVP](docs/current-pricing-mvp-contract.md)
- [Routing oracle](docs/oracle-spec.md)
- [Agent-facing oracle route function](docs/oracle-route-function-contract.md)

## Database bootstrap

- [PostgreSQL schema](db/schema.sql)
- [IAM-authenticated database roles](db/roles.sql)
- [Missing I-95/495 OD pricing model](docs/i95-missing-od-pricing.md)

The independently deployable `pricing` application schema starts at semantic
version **1.2.0**. Its version is stored in `pricing.schema_version`; CI tests
the bootstrap, coexistence backfill, privileges, analytics, cleanup guard, and
monotonic SemVer policy on PostgreSQL 17.9. The retained v1 `public` contract
remains version 5.0.0 and continues to run its existing schema tests.

The independently versioned `oracle` schema is at **1.6.0**. It installs
core PostGIS 3.5.x inside `oracle`, loads the directed toll-access graph, and
exposes endpoint-based route validators plus bounded I-66 and I-95/I-495
pricing comparisons to `tollchat_agent`.
Regenerate and verify its checked-in seed with:

```sh
uv run python oracle/build_oracle_data.py
uv run python oracle/build_oracle_data.py --check
```

Prepare an existing database additively; this does not move or modify v1 data:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/001_create_pricing_schema.sql
```

Upgrade an existing pricing `1.0.0` database with the guarded, rerunnable
migration:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql
```

Then install the facility-specific comparison views with:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/006_upgrade_pricing_1_0_1_to_1_1_0.sql
```

Then preserve exceptional I-95 schedule evidence as an explicit diagnostic:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/014_upgrade_pricing_1_1_0_to_1_1_1.sql
```

After pricing `1.0.0` or newer exists, install the oracle additively:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/003_create_oracle_schema.sql
```

Upgrade an existing oracle `1.0.0` database with the guarded, rerunnable
coordinate migration:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/004_upgrade_oracle_1_0_0_to_1_0_1.sql
```

Then upgrade oracle `1.0.1` to `1.0.2`:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/005_upgrade_oracle_1_0_1_to_1_0_2.sql
```

Then install the shared resolver and Python-facing exact-path validator:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/007_upgrade_oracle_1_0_2_to_1_1_0.sql
```

Then normalize Greenway pricing components for oracle `1.1.1`:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/008_upgrade_oracle_1_1_0_to_1_1_1.sql
```

Then move the conditional DTR charge onto the Greenway/DTR handoffs for oracle
`1.1.2`:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/009_upgrade_oracle_1_1_1_to_1_1_2.sql
```

Then make pricing-route resolution atomic for oracle `1.2.0`:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/010_upgrade_oracle_1_1_2_to_1_2_0.sql
```

Then correct DTR pricing metadata and allow direct IAD airport-access connectors
as untolled terminal routes for oracle `1.3.0`:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/011_upgrade_oracle_1_2_0_to_1_3_0.sql
```

Then expose current I-66 pricing through the least-privilege oracle `1.4.0`
function:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/012_upgrade_oracle_1_3_0_to_1_4_0.sql
```

Then expose current I-95/I-495 pricing through the least-privilege oracle
`1.5.0` function:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/013_upgrade_oracle_1_4_0_to_1_5_0.sql
```

Then add the bounded 12-week pricing sample views:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/015_upgrade_pricing_1_1_1_to_1_2_0.sql
```

Finally add schedule-independent ballpark routing and least-privilege sample
functions:

```bash
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/016_upgrade_oracle_1_5_0_to_1_6_0.sql
```

After the shadow loader is active, copy and verify the current v1 source rows:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/backfill.sql
```

See the [shadow rollout runbook](docs/pricing-shadow-rollout.md) for deployment,
verification, rollback, and deliberately guarded cleanup.

The `get_current_toll_price` Strands tool accepts stable origin and destination
point IDs plus the supported pricing profile. It validates the route through
the oracle and prices I-66 and I-95/I-495 from current observations plus Dulles
Greenway and Dulles Toll Road from their published schedules. I-95/I-495
components use 10-minute bins and retain recent movement, prior-week context,
and the provisional `identity_proxy_v1` label for modeled OD prices. Mixed
facility trips preserve route order and return one summed total. Callers do not
submit route plans or pricing components.

Its generated input, output, progress-event, and safe-error schemas are locked
by `agent_tools/contract-manifest.json`. Contract changes require a new,
increasing SemVer release and digest; CI rejects rewrites of published releases.

The `get_annual_toll_ballpark` tool validates outbound and return routes without
consulting live I-95 direction, samples complete same-date round trips from the
latest 12 weeks, and returns nearest-rank P25/P50/P90 daily values annualized by
the caller's planned commute days. Results remain recent historical context—not
a quote, forecast, or budget—and disclose modeled prices and current fixed-rate
assumptions.

The v2 loader is an independent copy under `v2/lambdas/loader`. Native S3
events reach it through EventBridge while v1 keeps its direct S3 notification.
Both paths are idempotent on their table keys and share no deployment state.
