# TollChat

TollChat is evolving from a production single-agent toll-pricing assistant into a from-scratch multiagent system. The repository keeps those generations physically separate so the current evidence remains reviewable while the rewrite develops independently.

| Implementation | Status | Start here |
|---|---|---|
| **Single agent** | Live at [tollchat.ai](https://tollchat.ai); complete application, infrastructure, tests, and evaluation evidence | [`single-agent/`](single-agent/) |
| **Multiagent** | Rewrite boundary established; implementation and deployment have not started | [`multiagent/`](multiagent/) |

```text
.
├── single-agent/  # Current deployable TollChat system
└── multiagent/    # From-scratch rewrite
```

For a technical review of the working system, begin with the [single-agent architecture and evidence guide](single-agent/README.md). The multiagent directory will document its own architecture as it earns one—no speculative scaffolding required.

## License

Unless otherwise noted, project-authored source code and documentation are available under the [Apache License 2.0](LICENSE).
