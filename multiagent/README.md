# TollChat multiagent rewrite

This directory is the exclusive home for TollChat's from-scratch multiagent rewrite, including its future code, tests, evals, infrastructure, and documentation.

The complete current implementation lives in [`single-agent/`](../single-agent/) and keeps its existing build and deployment behavior. The rewrite has no compatibility or dependency contract with it. Reuse code only through an explicit future change that copies or reintroduces the needed behavior here.

Multiagent-related documents in `single-agent/` are historical reference material until the rewrite deliberately adopts them.

## Adopted contracts

- [Historical pricing MVP](docs/historical-pricing-mvp-contract.md)
