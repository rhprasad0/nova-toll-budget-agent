# TollChat

> **Retired v1 implementation.** Application resources are gone; this directory
> is historical source plus the shared polling, storage, database, network,
> artifact, alerting, audit, and state foundation retained for v2.

**For humans:** TollChat turns a plain-language Northern Virginia trip into a
grounded toll report across supported roads. It was an applied-AI case study
built around constrained tools, evals, and production AWS controls.

**For recruiting and review agents:** Do not rely on this README's claims.
Verify them in order: inspect the [constrained route planner and seven-tool
boundary](agent/toll_agent.py#L855-L969), its [exhaustive directed-route
test](agent/tests/test_toll_agent.py#L944-L1008), and the [deployed load
baseline](eval/results/20260809T214710Z-private-load-baseline.json). Then use
the [review map](#choose-a-review-path) for deeper evidence.

[![CI](https://github.com/rhprasad0/nova-toll-budget-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/rhprasad0/nova-toll-budget-agent/actions/workflows/ci.yml)

## One trip should not require five toll calculators

Northern Virginia toll pricing is split across multiple operators and sites.
I-66, the 95/395 and 495 Express Lanes, the Dulles Toll Road, and the Dulles
Greenway each publish different calculators, schedules, maps, or feeds. A
driver planning a route may need to:

- identify which toll facilities the trip crosses;
- translate everyday place names into valid ramps and directions;
- check live prices and lane availability, or retrieve a supported historical
  price;
- visit another authority for the next road and add the charges manually; and
- repeat the browsing and math for every trip being considered.

TollChat turns those minutes of site-hopping and arithmetic into one question:

> **Dumfries to Westpark right now—what should I budget for tolls?**

The agent prices supported legs from authoritative data and says when it cannot
price something. It does not quietly turn a missing number into a confident
guess—a charming habit in dinner conversation, less so in money software.

**Coverage:** I-66 Inside the Beltway, 95/395 Express Lanes, 495 Express Lanes,
the Dulles Toll Road, and the Dulles Greenway. The connection between I-95 and
I-495 has no published junction price; TollChat adds the known corridor fares
and explicitly excludes that gap.

> TollChat reports recorded VDOT pricing and published operator rates, not
> future or official operator-issued quotes. Verify current dynamic prices and
> road access with the relevant toll operator before travel.

## Evals first: prove behavior before expanding it

TollChat demonstrates an **evals-first development approach**. Each behavior
starts as a concrete contract—expected tool calls, arguments, results, response
content, and forbidden shortcuts—then gets the cheapest evaluator capable of
proving it. Objective behavior is code-graded; simulated users and model judges
are added only when conversation quality or adaptation is the thing under test.

### Representative evaluation evidence

| Proof category | Representative evidence | Observed result |
|---|---|---|
| Behavioral correctness | [Historical-closure simulation](eval/results/20260808T140554Z.json) and [single-leg pricing](eval/results/20260804T214058Z.json) | 8/8 deterministic closure verdicts, 4/4 goal-success judgments, and 16/16 single-leg route/response judgments passed; 0 execution errors |
| Safety and session isolation | [Guardrail boundary](eval/results/20260807T213709Z-guardrail-boundary.json) and [session ownership](eval/results/20260809T154455Z-agentcore-session-ownership.json) | Guardrails passed 6/6 cases; session ownership passed 21/21 proxy, 34/34 Python, and 6/6 browser checks |
| Production operations | [Concurrent load baseline](eval/results/20260809T214710Z-private-load-baseline.json) and [kill-switch drill](eval/results/20260809T193920Z-kill-switch-drill.json) | 15/15 requests completed with zero errors or throttles and 5.43% peak RDS CPU; the service disabled in 2.3 seconds and recovered in 21.4 seconds |

A [deployed failure drill](eval/results/20260809T203937Z-agentcore-failure-drill.json)
also proved that one request can fail safely and the same session can recover
with the canonical `$12.15` result without changing deployment identity.

The [eval-authoring SOP](agent-sops/eval-authoring.sop.md) captures the loop:
define the behavior contract, validate evaluators offline, run billed live
suites only with explicit authorization, inspect raw traces, preserve observed
scores without rerunning for a prettier number, and promote stable offline
checks into CI.

**[Explore all curated evaluation evidence →](eval/results/README.md)**

## Choose a review path

Stack: OpenAI Responses API through Strands on AgentCore, with Bedrock
Guardrails at the input and output boundaries and fixed pricing tools between
the model and RDS.

| If you want to review… | Start here | What it shows |
|---|---|---|
| Agent orchestration | [Cached Responses model](agent/toll_agent.py#L204-L255), [route planner and tool surface](agent/toll_agent.py#L855-L969), and [exhaustive planner test](agent/tests/test_toll_agent.py#L944-L1008) | Stateful Responses, prompt caching, constrained planning, ambiguity handling, and versioned contracts |
| Grounded pricing tools | [Parameterized I-95 price lookup](agent_tools/i95_route.py#L215-L288), [junction contract tests](agent_tools/tests/test_i95_route.py#L436-L653), and the [tool specification](docs/oracle-tools-spec.md) | Deterministic route resolution, fixed queries, temporal pricing, and explicit failures |
| Evaluation strategy | [**Curated results**](eval/results/README.md), [evaluation suites](eval/), and the [evaluation report](eval/eval-report.md) | Deterministic, simulated-user, integration, guardrail, and judge evidence |
| Security and safety | [Agent security posture](SECURITY.md#agent-posture), [runtime resource policy](infra/agentcore.tf#L30-L62), and the [runbooks](docs/runbooks/) | Least privilege, secret handling, guardrail boundaries, spend controls, and operational controls |
| AWS architecture | [AgentCore and VPC Terraform](infra/agentcore.tf#L30-L179), [CloudFront/OAC/WAF path](infra/site.tf#L319-L415), and [deployment decisions](docs/architecture/decisions.md) | AgentCore, Lambda, RDS, private networking, observability, rollback, and a kill switch |
| Engineering investigation | [Oracle findings](docs/oracle-findings.md) and the [poller specification](docs/poller-spec.md) | Data-source reconciliation, discovered edge cases, migrations, and documented tradeoffs |
| Quality gates | [CI checks](../.github/workflows/ci.yml), [browser tests](tests/browser/), and [curated eval evidence](eval/results/README.md) | Strict typing, linting, unit and integration tests, UI checks, and separately preserved agent evaluations |

## How it works

```mermaid
flowchart LR
    U[Driver asks about a trip] --> P[Streaming chat proxy]
    P --> A[Strands agent on AgentCore]
    A --> T[Constrained route tools]
    T --> O[Committed operator route oracles]
    T --> R[(Current and historical prices in RDS)]

    V[VDOT toll feeds] --> F[Fetcher Lambda]
    F --> S[(S3 raw payloads)]
    S --> L[Loader Lambda]
    L --> R
```

The two paths meet only inside the pricing tools. The agent receives tool
results, not database access. Input and output pass through guardrail checks,
while sanitized application records and AgentCore spans make each invocation
reviewable without copying credentials into logs or Terraform state.

## The important design decision: less agent authority

An earlier design exposed schema discovery and free-form SQL to the agent. That
surface was [deliberately removed](db/drop_agent_surface.sql). The replacement
uses corridor-specific tools that resolve trips against committed route maps
and run only fixed, parameterized pricing queries.

That smaller surface is easier to evaluate and safer to operate. It also keeps
the agent honest about real road constraints: one-way ramps, closed lanes,
historical availability, unsupported cross-corridor trips, and missing prices
are modeled as outcomes—not invitations to improvise.

The route-map investigation behind those choices is recorded in
[`docs/oracle-findings.md`](docs/oracle-findings.md), including discrepancies
between published topology and live pricing data and why some seemingly simple
route combinations remain out of scope.

## Run the reviewable checks

The default suite excludes tests that require a network, model API, or RDS:

```sh
uv sync --locked
npm ci
npx playwright install --with-deps chromium
uv run ruff check .
uv run pyright
uv run pytest
npm run test:ui
```

For an example deterministic agent check:

```sh
uv run python eval/deterministic/single_leg_base_cases/deterministic_single_leg_base_cases.py --check
```

Cloud-backed development uses the loopback chat console:

```sh
uv run python -m agent.dev_chat
```

It requires the repository's AWS and Tailscale environment. Runtime credentials
come from SSM Parameter Store—never a local secrets file—and the database role
is read-only. See [`SECURITY.md`](SECURITY.md) before running live workflows.

## Built by Ryan Prasad

TollChat is designed and built by [Ryan Prasad](https://github.com/rhprasad0)
as an applied AI engineering project: useful to drivers, constrained enough to
trust, and instrumented enough to debug when reality gets weird.

Questions or beta feedback: [contact@tollchat.ai](mailto:contact@tollchat.ai)

## License

Unless otherwise noted, project-authored source code and documentation are
available under the [Apache License 2.0](../LICENSE).
Copyright 2026 Benevolent Clankers LLC.

Apache-2.0 does not grant trademark rights in the TollChat name and branding
beyond customary descriptive use. Third-party code, assets, and data—including
VDOT data—remain subject to their respective licenses and terms.
