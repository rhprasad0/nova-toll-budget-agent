# TollChat open-beta launch plan

**Status:** blocked until every launch gate below has reviewable evidence.

**Goal:** expose TollChat to a deliberately small public audience, collect useful
feedback and governed traces, and preserve a fast path back to the private
preview. Open beta is a learning stage: it carries no availability promise and
does not relax privacy, security, or toll-accuracy requirements.

This document is the delivery plan. `docs/public-agent-launch-gate.md` remains
the authorization record and must be reconciled with this plan before public
chat is enabled.

## Launch shape

```text
Private preview
Owner -> Tailscale -> private API Gateway -> Lambda proxy -> AgentCore

Open beta
Browser -> CloudFront + WAF -> Lambda proxy -> AgentCore -> RDS / OpenAI
            |                                  |
            + rate and size limits             + governed 30-day traces

Rollback
Disable public route -> set proxy concurrency to 0 only for service-wide harm
-> restore the last reviewed artifact -> restore approved proxy concurrency
-> verify the private preview
```

SSM Parameter Store remains the source of truth for every credential. Public
traffic receives only the validated event contract and guarded answer; it never
receives model, tool, database, provider, or infrastructure details.

## [Gate 1 - Public edge and spend boundary](https://github.com/rhprasad0/nova-toll-budget-agent/issues/122)

- [ ] Add a separately switchable CloudFront `/api/*` origin without weakening
      the existing private preview.
- [ ] Prevent callers from bypassing CloudFront and WAF through the origin's
      hostname, or apply equivalent controls at that origin. Prove a direct
      origin request cannot invoke chat.
- [ ] Keep public chat disabled by default in Terraform and verify disabling it
      removes the public API behavior.
- [ ] Attach AWS WAF before the proxy. Enforce per-source request throttling and
      reject oversized bodies at the edge; retain the proxy's validation as the
      trust boundary.
- [ ] Preserve the five-turn session cap, five reserved proxy executions, safe
      dependency timeouts, and fixed response contract.
- [ ] Bound model output and total model/tool calls per invocation. An ordinary
      timeout is the final brake, not the primary cost control.
- [ ] Configure an OpenAI project budget alert and notification path; do not
      describe it as a hard ceiling unless current provider behavior proves it
      stops requests. AWS Budgets does not control spend billed by OpenAI.
- [ ] Before launch, verify either a hard provider/org limit or an automated
      public-off response whose request bounds, concurrency, and alert delay
      produce an explicit, owner-approved maximum cost exposure.
- [ ] Verify the dedicated runtime and proxy roles still have only the existing
      read-only pricing, Guardrail, trace, and invocation permissions.

## [Gate 2 - Session ownership](https://github.com/rhprasad0/nova-toll-budget-agent/issues/123)

- [ ] Complete [#108](https://github.com/rhprasad0/nova-toll-budget-agent/issues/108):
      issue the anonymous session credential from the backend instead of
      accepting a browser-created UUID as proof of ownership.
- [ ] Bind chat and reset requests to that credential, with secure expiry and
      rotation matching the AgentCore session lifecycle. For an anonymous beta,
      prefer an `HttpOnly`, `Secure`, `SameSite` cookie and reject cross-site
      state-changing requests.
- [ ] Prove that browser-supplied or guessed runtime IDs, cross-site requests,
      and credentials invalidated by reset or expiry cannot continue or reset
      another session. Do not claim an ordinary bearer cookie resists deliberate
      token copying.
- [ ] Do not add user accounts unless beta evidence or an approved privacy
      requirement makes them necessary.

## [Gate 3 - Trace policy, terms, and user notice](https://github.com/rhprasad0/nova-toll-budget-agent/issues/124)

- [ ] Complete the launch-critical decisions in
      [#96](https://github.com/rhprasad0/nova-toll-budget-agent/issues/96),
      [#117](https://github.com/rhprasad0/nova-toll-budget-agent/issues/117),
      and [#114](https://github.com/rhprasad0/nova-toll-budget-agent/issues/114).
- [ ] Inventory the exact content, processors, readers, region, retention, and
      deletion limits of the existing AgentCore and application trace paths.
- [ ] Record owner and legal/privacy approval for the beta collection purpose,
      applicable user choice, toll-data terms, disclaimer, and non-affiliation
      language. Do not encode an unreviewed legal conclusion in application
      behavior.
- [ ] Publish effective, versioned terms and a privacy notice. Add an accessible
      just-in-time notice beside the composer before the first submission.
- [ ] State plainly that trip text, answers, tool activity, and safety-filter
      results may be retained for 30 days; identify processors and the privacy
      request contact; warn against submitting sensitive information.
- [ ] Separate mandatory operational telemetry from optional feedback use. If
      approval requires a choice for full-content product improvement, enforce
      that choice before capture and support withdrawal prospectively.
- [ ] Use the approved 30-day AWS trace destinations already implemented and
      document their different content and deletion behavior plus the stateful
      model provider's storage and processing. Do not add the durable
      product-record system in
      [#90](https://github.com/rhprasad0/nova-toll-budget-agent/issues/90)
      until a concrete retention, lookup, or deletion requirement needs it.

## [Gate 4 - Operational readiness](https://github.com/rhprasad0/nova-toll-budget-agent/issues/125)

- [ ] Complete the deployed kill-switch drill in
      [#93](https://github.com/rhprasad0/nova-toll-budget-agent/issues/93),
      including recovery of the private preview and confirmation that ingestion
      and RDS remain healthy.
- [ ] Run one stable deployed toll-query smoke test from
      [#99](https://github.com/rhprasad0/nova-toll-budget-agent/issues/99).
- [ ] Exercise one representative dependency failure from
      [#98](https://github.com/rhprasad0/nova-toll-budget-agent/issues/98)
      and prove the browser receives only the safe error contract.
- [ ] Add actionable alarms for proxy failures and latency, AgentCore sessions,
      toll-data freshness, RDS CPU/free memory/connections/CPU credits, and
      provider spend. Confirm the SNS recipient actually receives them.
- [ ] Run a short private load test with ingestion active. Set alert and rollout
      thresholds from that baseline; resize RDS only if the evidence requires it.
- [ ] Implement the launch-critical slice of
      [#104](https://github.com/rhprasad0/nova-toll-budget-agent/issues/104):
      check expected feed/corridor row coverage and plausible rate changes before
      publication, and preserve the last-known-good snapshot when a check fails.
- [ ] Retain the last reviewed packages and record their digests. Verify the
      rollback runbook restores approved proxy concurrency before the private
      smoke test, then exercise it before enabling public traffic.

## [Gate 5 - Beta feedback and ownership](https://github.com/rhprasad0/nova-toll-budget-agent/issues/126)

- [ ] Label the product **Open Beta** and state that behavior may change and no
      availability commitment is offered.
- [ ] Link to the monitored feedback contact without automatically attaching the
      conversation. If structured ratings or free text are added later, first
      define their destination, fields, validation, access, retention, deletion,
      disclosure, and abuse controls in Gate 3.
- [ ] Route privacy, security, incorrect-price, and availability reports to a
      monitored owner. Define the first-response expectation for the beta.
- [ ] Review aggregate health and a bounded sample of approved traces daily for
      the first week; record decisions without copying user content into issues
      or evaluation reports.

## Release evidence

Run the normal repository checks and preserve only successful, non-sensitive
evidence:

```bash
uv sync --locked
uv run pytest
npm --prefix lambdas/chat_proxy ci
npm --prefix lambdas/chat_proxy test
uv run ruff check .
uv run ruff format --check .
uv run pyright
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
./scripts/build_zips.sh
gitleaks git --redact
```

Before launch, the authorization record must link to evidence for WAF limits,
direct-origin denial, public-off behavior, cross-session isolation, terms and
privacy approval, trace/provider retention, IAM simulation, feed-quality
rejection, alarms, bounded cost exposure, the canonical query, the safe failure,
the kill switch, and rollback. Curate representative reports in `eval/results/`
according to its README; failed or superseded runs stay out.

## Rollout

1. **Private rehearsal:** deploy the exact candidate, run all release evidence,
   and record explicit go/no-go approval.
2. **Quiet public beta:** enable the public route for directly invited testers
   without broad promotion. Supervise it for at least one normal ingestion
   cycle and review every alert and safe failure.
3. **Open announcement:** widen discovery without raising the established
   concurrency or spending boundaries. Change one limit at a time only when
   observed demand and health justify it.

Disable the public route immediately for suspected data exposure, session
crossover, credential leakage, unsafe browser output, or materially incorrect
toll behavior. Pause expansion for breached health, capacity, or spend
thresholds; restore the known-good state before diagnosing.

## Deferred until beta evidence

The following are not launch blockers unless rehearsal or beta telemetry exposes
the risk they address: the durable product store (#90), managed AgentCore
Evaluations (#91), speculative RDS resizing (#95), expanded lifecycle testing
(#100), comprehensive dashboards (#102), VPC Flow Logs and network
defense-in-depth (#103, #105, #107), restore drills (#106), feed-quality
monitoring beyond the publication gate above (#104), equivalent-call loop
detection beyond the hard per-invocation cap (#112), and the portfolio video
(#113).

## Practice references

- [Google SRE: progressive rollouts](https://sre.google/sre-book/service-best-practices/)
- [AWS operational-readiness review](https://docs.aws.amazon.com/wellarchitected/latest/operational-readiness-reviews/appendix-b-example-orr-questions.html)
- [AWS automated testing and rollback](https://docs.aws.amazon.com/wellarchitected/latest/framework/ops_mit_deploy_risks_auto_testing_and_rollback.html)
- [GitHub public-preview lifecycle](https://docs.github.com/en/get-started/using-github/exploring-early-access-releases-with-feature-preview)
- [NIST Generative AI Risk Management Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)
- [OWASP: LLM unbounded consumption](https://owasp.org/www-project-top-10-for-large-language-model-applications/2_0_vulns/LLM10_UnboundedConsumption)
- [ICO: privacy in the product lifecycle](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/designing-products-that-protect-privacy/privacy-in-the-product-design-lifecycle/)
