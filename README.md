# TollChat

TollChat v1 runs in production while v2 develops independently around a
deterministic domain core. The versioned layout keeps the live product and its
evidence easy to review without blurring it into work in progress.

| Implementation | Status | Start here |
|---|---|---|
| **v1** | Live at [tollchat.ai](https://tollchat.ai); complete application, infrastructure, tests, and evaluation evidence | [`v1/`](v1/) |
| **v2** | In development; PostgreSQL pricing schema, provenance contracts, modeled I-95 pricing, and deterministic analysis are implemented, while agent runtime and deployment remain future work | [`v2/`](v2/) |

```text
.
├── v1/  # Live TollChat product
└── v2/  # Deterministic single-agent rewrite in development
```

For a technical review of the working system, begin with the
[v1 architecture and evidence guide](v1/README.md). For the new deterministic
pricing contracts and database work, begin with the [v2 guide](v2/README.md).

## License

Unless otherwise noted, project-authored source code and documentation are available under the [Apache License 2.0](LICENSE).
