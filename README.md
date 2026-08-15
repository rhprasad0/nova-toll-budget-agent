# TollChat

TollChat's original toll-pricing agent runs in production while a from-scratch
rewrite develops independently. The repository keeps the two implementations
physically separate so the production evidence remains reviewable.

| Implementation | Status | Start here |
|---|---|---|
| **Original agent** | Live at [tollchat.ai](https://tollchat.ai); complete application, infrastructure, tests, and evaluation evidence | [`single-agent/`](single-agent/) |
| **Agent rewrite** | Rewrite boundary established; implementation and deployment have not started | [`rewrite/`](rewrite/) |

```text
.
├── single-agent/  # Current deployable TollChat system
└── rewrite/       # From-scratch agent rewrite
```

For a technical review of the working system, begin with the
[original agent architecture and evidence guide](single-agent/README.md). The
rewrite directory will document its architecture as it earns one—no speculative
scaffolding required.

## License

Unless otherwise noted, project-authored source code and documentation are available under the [Apache License 2.0](LICENSE).
