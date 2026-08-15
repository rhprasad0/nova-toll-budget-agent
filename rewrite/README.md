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

## Database bootstrap

- [PostgreSQL schema](db/schema.sql)
- [IAM-authenticated database roles](db/roles.sql)
- [Missing I-95/495 OD pricing model](docs/i95-missing-od-pricing.md)

The bootstrap restores an empty database's schema and permissions. Historical
price rows require a separate replay from retained raw objects.
