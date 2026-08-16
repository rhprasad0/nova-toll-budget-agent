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

- [Historical pricing MVP](docs/historical-pricing-mvp-contract.md)
- [Point-in-time pricing and insights MVP](docs/point-in-time-pricing-mvp-contract.md)
- [Routing oracle](docs/oracle-spec.md)

## Database bootstrap

- [PostgreSQL schema](db/schema.sql)
- [IAM-authenticated database roles](db/roles.sql)
- [Missing I-95/495 OD pricing model](docs/i95-missing-od-pricing.md)

The independently deployable `pricing` application schema starts at semantic
version **1.0.1**. Its version is stored in `pricing.schema_version`; CI tests
the bootstrap, coexistence backfill, privileges, analytics, cleanup guard, and
monotonic SemVer policy on PostgreSQL 17.9. The retained v1 `public` contract
remains version 5.0.0 and continues to run its existing schema tests.

The independently versioned `oracle` schema starts at **1.0.0**. It installs
core PostGIS 3.5.x inside `oracle`, loads the directed toll-access graph, and
exposes only `oracle.validate_toll_route(text, text)` to `tollchat_agent`.
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

After pricing `1.0.0` or newer exists, install the oracle additively:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/002_create_oracle_schema.sql
```

After the shadow loader is active, copy and verify the current v1 source rows:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/backfill.sql
```

See the [shadow rollout runbook](docs/pricing-shadow-rollout.md) for deployment,
verification, rollback, and deliberately guarded cleanup.

The database functions return the dynamic subtotal and its source provenance.
The caller remains responsible for supplying the complete immutable dynamic
component list from the canonical route plan and for adding scheduled tolls,
the pricing profile, and route metadata required by the adopted contracts.
The defensive database boundary accepts at most 16 dynamic components, 128
characters per route-step identifier, and 64 KiB of component JSON.

The v2 loader is an independent copy under `v2/lambdas/loader`. Native S3
events reach it through EventBridge while v1 keeps its direct S3 notification.
Both paths are idempotent on their table keys and share no deployment state.
