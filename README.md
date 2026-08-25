# TollChat

TollChat is the deployed deterministic toll-pricing assistant.

| Area | Purpose |
|---|---|
| [`v2/`](v2/) | Application, pricing loader, tests, evals, and application infrastructure |
| [`infra/`](infra/) | Shared polling, storage, database, network, security, and state foundation |

```text
.
├── infra/  # Shared production foundation
└── v2/     # Deployed application
```

For the working system, begin with the [v2 guide](v2/README.md).

## Shared foundation changes

Build and pass the real fetcher package for every root `infra/` plan. The
bucket-policy guard rejects placeholder plans:

```sh
v2/scripts/build_fetcher_zip.sh
AWS_PROFILE=nova-toll terraform -chdir=infra init
AWS_PROFILE=nova-toll terraform -chdir=infra plan \
  -var='fetcher_package_path=build/fetcher.zip' \
  -out=build/foundation.tfplan
AWS_PROFILE=nova-toll terraform -chdir=infra show build/foundation.tfplan
AWS_PROFILE=nova-toll terraform -chdir=infra apply build/foundation.tfplan
```

Review the saved plan before applying it. Load credentials from SSM into the
process environment only; never place them in Terraform variables or plans.

## License

Unless otherwise noted, project-authored source code and documentation are available under the [Apache License 2.0](LICENSE).
