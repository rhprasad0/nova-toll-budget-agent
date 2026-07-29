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

- [ ] **No network path from AgentCore to RDS.** `infra/network.tf:39-65`
      only grants RDS ingress to the Tailscale subnet-router SG and the
      loader Lambda's security group. No security group, VPC config, or IAM
      role exists for an AgentCore runtime (`infra/lambda-stub/handler.py`
      is an empty placeholder; no `agent`/`bedrock`/`agentcore` reference
      anywhere in `infra/iam.tf` or elsewhere). Scope as its own infra work
      item: IAM execution role, runtime resource, network path to RDS.
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

## Tier 1B — Legal & Compliance Blockers

Free product, public chat box, traces-only collection (no accounts). These
close before launch because exposure starts the moment the URL is public, not
after traffic arrives.

- [ ] **Terms of Service.** Mirror the pattern used by every comparable free
      estimate tool (CostPrism, Construction Estimator, Estimation Pro AI,
      Dozi): "estimates only, not quotes," "AS IS, no warranty of accuracy,"
      liability capped at **$0** since the service is free. A $0 cap tied to
      $0 paid is the enforceable version of this clause.
- [ ] **In-product accuracy disclaimer, not just in the ToS.** The FTC's
      July 2026 Section 5 policy statement on AI accuracy holds that a
      disclaimer "could not be buried in terms of service" — it must be
      prominent and persistent where the user actually is. Put a visible
      line in the chat UI itself (e.g. "Estimates only — verify with the
      toll operator before you drive"). This replaces and specifies where
      the old Tier 2 "user-facing accuracy disclaimer" item lives — same
      underlying gap (`oracle-findings.md` §2, §6, §7 — 107 historically
      unpriceable trips, one unresolved od_pair_id), placement now decided.
- [ ] **Privacy policy, even for traces-only collection.** IP address is
      personal data under GDPR regardless of company size or revenue (GDPR
      triggers on any EU visitor, not company scale), and origin/destination
      text typed into chat functions as home/work location data — more
      sensitive than generic analytics. State what's collected (chat
      transcript + IP + timestamp via CloudFront/AgentCore logs), why, that
      it's not sold, and the retention window (next item).
- [ ] **Explicit retention window on stored traces** (e.g. 90 days).
      "Traces, nothing else" needs a number attached or it's unbounded
      liability by default — cheap to decide now, expensive to retrofit
      after a deletion request.
- [ ] **"I'm an AI assistant" label in the chat UI.** Not legally required —
      CA's bot-disclosure law targets deceptive human-impersonation for
      sales, SB 243 targets companion/relationship bots, TollChat fits
      neither — but the label is free and closes the question outright.
- [ ] **Form an LLC before the public URL goes live**, if not already done.
      Separates personal liability from the business once anyone can hit a
      public chat box.

## Tier 2 — Should-fix-before-launch

- [ ] `agent_tools/_oracle_route.py:123` `env_connect()` has no
      timeout/retry/except around the RDS connection. A DB blip currently
      raises uncaught — fine in tests, a raw crash in a live chat UI. Do
      alongside the Tier-1 network item since it touches the same
      connection path.
- [ ] **Oracle freshness has no stated policy.** `i66.json` and `i95.json`
      carry no `retrieved_at`; Dulles files are hand-transcribed
      (`scripts/build_dulles_oracle.py`). Add `retrieved_at` to all four and
      write down a staleness policy (e.g. re-verify Dulles/Greenway
      quarterly) — no automation needed yet, just a stated commitment.

## Tier 3 — Post-launch, not blocking

- [ ] No CloudWatch dashboard (alarms exist, just no visualization)
- [x] ~~No Terraform plan/apply step in CI~~ — `.github/workflows/terraform.yml`
      now runs `plan` on PRs touching infra and `apply` automatically on
      push to `main` (`docs/terraform-ci-tasks.md`)
- [ ] No rollback artifact retention (`build_zips.sh` does `rm -rf` on the
      prior build dir before rebuilding)
- [ ] `scripts/smoke.sh` omits the `toll-express-fetcher-errors` alarm from
      its sweep (6 of 7 alarms checked)
- [ ] No storage lifecycle/retention policy against the RDS 40GB
      `max_allocated_storage` cap (guarded only by the free-storage alarm)
- [ ] Pre-commit hook (`.githooks/pre-commit`) is opt-in per clone
      (`core.hooksPath` set manually), not enforced at the repo level
