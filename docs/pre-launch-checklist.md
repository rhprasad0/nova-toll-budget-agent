# Pre-launch Due Diligence — TollChat MVP

Status: in progress · Owner: Ryan Prasad · Last updated: 2026-07-26

The shippable MVP is a public chat box on tollchat.ai backed by Bedrock
AgentCore. This checklist covers everything needed to expose that publicly
*outside* agent correctness — infra, cost, ops, and data freshness. Agent
correctness (tool choice, routing, refusal behavior) is tracked separately in
[`agent-evals-tasks.md`](agent-evals-tasks.md) and is not duplicated here.

A gap belongs in Tier 1 only if, left unfixed, the MVP would (a) give
confidently wrong prices, (b) fail to function at all, or (c) spend unbounded
money. Everything else is hygiene, tracked but not gating launch.

## Tier 1 — Blockers

- [ ] **No network path from AgentCore to RDS.** `infra/network.tf:33-45`
      only grants RDS ingress to `home_ip/32` and the loader Lambda's
      security group. No security group, VPC config, or IAM role exists for
      an AgentCore runtime (`infra/lambda-stub/handler.py` is an empty
      placeholder; no `agent`/`bedrock`/`agentcore` reference anywhere in
      `infra/iam.tf` or elsewhere). Scope as its own infra work item: IAM
      execution role, runtime resource, network path to RDS.
- [ ] **Wrong-answer generator in routing logic.** `agent/toll_agent.py:104-113`,
      the `("dulles_greenway", "i495")` JUNCTIONS entry asserts both
      "NOT EVIDENCED" and "must route through dulles_toll_road" in the same
      entry. Live contradiction in code, also flagged in
      `agent-evals-tasks.md` §3.1. Resolve before traffic hits this path.
- [ ] **No cost/abuse controls on a public Bedrock endpoint.** Need a
      request rate limit, a budget alarm on Bedrock spend, and a cap on
      turns/tokens per session. Prompt-injection blast radius is small (5
      read-only tools, `pricing_reader` is SELECT-only) — cost is the real
      exposure here, not exfiltration, so scope narrowly to spend control.
- [ ] **Alarm notification integrity.** `infra/observability.tf:8`
      subscribes `bills@ryanprasad.ai`; `scripts/smoke.sh:26` tells the
      operator to check `rhprasad@outlook.com`. This exact failure mode
      (unconfirmed SNS subscription silently expiring in 3 days) already
      happened once per the `e90d981` commit message. A muted freshness
      alarm means quoting stale prices with no signal. Pick one address,
      confirm the subscription, make smoke.sh match.

## Tier 2 — Should-fix-before-launch

- [ ] `agent_tools/_oracle_route.py:123` `env_connect()` has no
      timeout/retry/except around the RDS connection. A DB blip currently
      raises uncaught — fine in tests, a raw crash in a live chat UI. Do
      alongside the Tier-1 network item since it touches the same
      connection path.
- [ ] **Oracle freshness has no stated policy.** `i66.json`, `i95.json`,
      `i66_otb.json` carry no `retrieved_at`; `i66_otb.json` has no
      generator script at all; Dulles files are hand-transcribed
      (`scripts/build_dulles_oracle.py`). Add `retrieved_at` to all five and
      write down a staleness policy (e.g. re-verify Dulles/Greenway
      quarterly) — no automation needed yet, just a stated commitment.
- [ ] **User-facing accuracy disclaimer.** Fixed-toll oracles can go stale
      and dynamic pricing has known gaps (`oracle-findings.md` §2, §6, §7 —
      107 historically unpriceable trips, one unresolved od_pair_id). Chat
      UI should say prices are estimates to verify with the operator.

## Tier 3 — Post-launch, not blocking

- [ ] No CloudWatch dashboard (alarms exist, just no visualization)
- [ ] No Terraform plan/apply step in CI — deploys are fully manual
      (`scripts/build_zips.sh` + hand-run `terraform apply`)
- [ ] No rollback artifact retention (`build_zips.sh` does `rm -rf` on the
      prior build dir before rebuilding)
- [ ] `scripts/smoke.sh` omits the `toll-express-fetcher-errors` alarm from
      its sweep (6 of 7 alarms checked)
- [ ] No storage lifecycle/retention policy against the RDS 40GB
      `max_allocated_storage` cap (guarded only by the free-storage alarm)
- [ ] Pre-commit hook (`.githooks/pre-commit`) is opt-in per clone
      (`core.hooksPath` set manually), not enforced at the repo level
