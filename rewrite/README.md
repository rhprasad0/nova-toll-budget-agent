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
