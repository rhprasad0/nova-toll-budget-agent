# TollChat agent rewrite

This directory is the exclusive home for TollChat's from-scratch agent rewrite,
including its future code, tests, evals, infrastructure, and documentation.

The complete original implementation lives in
[`single-agent/`](../single-agent/) and keeps its existing build and deployment
behavior. The rewrite has no compatibility or dependency contract with it.
Reuse code only through an explicit future change that copies or reintroduces
the needed behavior here.

Documents in `single-agent/` remain historical reference material until the
rewrite deliberately adopts them.

## Adopted contract

- [Historical pricing MVP](docs/historical-pricing-mvp-contract.md)
- [Point-in-time pricing and insights MVP](docs/point-in-time-pricing-mvp-contract.md)

## Database bootstrap

- [PostgreSQL schema](db/schema.sql)
- [IAM-authenticated database roles](db/roles.sql)
- [Missing I-95/495 OD pricing model](docs/i95-missing-od-pricing.md)

For an existing database, apply the additive dynamic-pricing analysis migration:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f rewrite/db/migrations/001_dynamic_pricing_analysis.sql
```

The database functions return the dynamic subtotal and its source provenance.
The caller remains responsible for supplying the complete immutable dynamic
component list from the canonical route plan and for adding scheduled tolls,
the pricing profile, and route metadata required by the adopted contracts.
The defensive database boundary accepts at most 16 dynamic components, 128
characters per route-step identifier, and 64 KiB of component JSON.

The bootstrap restores an empty database's schema and permissions. Historical
price rows require a separate replay from retained raw objects.
