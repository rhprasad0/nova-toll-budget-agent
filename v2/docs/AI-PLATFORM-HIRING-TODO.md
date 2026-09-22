# AI platform hiring TODO

**Goal:** demonstrate that one engineer can build, release, measure, and operate
an AI application—the “one-person agent shop.” Target applied AI platform and
supporting infrastructure roles, with no fixed completion deadline.

**Research date:** September 22, 2026. Repository baseline:
[`a10a0aa`](https://github.com/rhprasad0/nova-toll-budget-agent/tree/a10a0aabe238a068965b91be577fbb5704e7a0ed).
Research used Exa to inspect official hiring and engineering sources, alongside
repository code, tests, runbooks, and GitHub delivery records. This is an evidence
review, not a certification of current deployed state.

## Assessment

**The biggest gap is measured operating evidence, not another infrastructure
component.** TollChat already demonstrates deterministic tools, ordering-aware
ingestion, separate environments, security boundaries, guarded migrations, and
reviewed delivery. The next convincing claim is: “Here is how it behaved, what
failed, what I changed, and the measured result.”

That emphasis matches the performance, reliability, storage, and operational
responsibilities in [OpenAI's backend engineering role](https://openai.com/careers/backend-software-engineer-chatgpt-engineering-san-francisco/).
[Anthropic's Managed Agents role](https://www.anthropic.com/careers/jobs/5395767008)
also explicitly treats session state, streaming, reliability, latency, and cost
as platform responsibilities. Its remit includes harness/evaluation work too;
these sources identify relevant signals, not an exclusively infrastructure job
description or a universal hiring checklist. Staff-level postings do not make
every listed responsibility a prerequisite for this portfolio.

**The uncomfortable part: there are no real users.** The project therefore has
limited evidence of demands someone else chose, sustained operational pressure,
or usefulness outside the builder's expectations. Synthetic workloads can prove
specific behavior honestly. They cannot establish customer-scale reliability,
sustained on-call experience, product demand, or cross-team effectiveness. A
portfolio can reduce uncertainty about your abilities; it cannot guarantee that
a manager will disregard a preference for frontier-lab experience.

Complexity is also something to defend. A one-person shop needs a system one
person can understand and operate. Explain which delivery controls protect real
boundaries, where managed services do the work, and which costs and failure
points you deliberately accept. More machinery without a measured benefit can
weaken that story.

### Evidence already earned

| Area | Existing evidence | Limit to preserve |
| --- | --- | --- |
| Delivery and isolation | [Technical guide](../README.md), [blue-green runbook](../runbooks/blue-green-deployments.md), and [completed release/recovery record](https://github.com/rhprasad0/nova-toll-budget-agent/issues/522#issuecomment-5750028330) | Production blue-green activation and development recovery rehearsals have occurred. The runbook's “not run” statement is stale. |
| Recovery | The closure record links candidate rejection, recovery, and healthy cleanup; [PR #533](https://github.com/rhprasad0/nova-toll-budget-agent/pull/533) explains the retained frontend defect | The earlier rehearsal demonstrated routing/API recovery, not frontend health. Do not discard that proof or claim it covered the browser. |
| Streaming and sessions | [Runtime](../agent/agentcore_entrypoint.py) and [proxy](../lambdas/chat_proxy/handler.mjs) implement checked streaming, release fencing, and request leases | Streaming exists. Session metadata is stored, but conversation state is in runtime memory; releases intentionally require a new chat. |
| Data and security | [Loader](../lambdas/loader/handler.py), [pricing SQL](../db/analysis.sql), [security policy](../../SECURITY.md), and [telemetry runbook](../runbooks/telemetry-pii-redaction.md) | Code and tests establish specific contracts; live observations retain their narrower scope. |
| Cost and evaluation | [Billing dashboard runbook](../runbooks/cost-dashboard.md) and [retained evaluation results](../eval/results/README.md) | Per-turn cost is unmeasured. Evaluation timings that include actors and judges are not serving latency. |

## Ranked TODO

Ranked by expected incremental hiring impact for the stated role, not dependency
order. Items 1 and 2 are the largest technical priorities. Curating existing
evidence in item 6 can start immediately. A dashboard is a way to present proof;
its existence is not the proof.

### 1. Publish a reproducible latency improvement

- [ ] **Measure the deployed serving path, identify its dominant contributors,
  and improve the largest actionable bottleneck.**

**Why:** demonstrates performance reasoning across service boundaries. OpenAI's
[agentic workflow performance investigation](https://openai.com/index/speeding-up-agentic-workflows-with-websockets/)
separates API overhead from inference and client/tool time. The transferable
lesson is measurement and attribution; it is not a requirement to add WebSockets.

**Current:** checked streaming already exists. [Issue #542](https://github.com/rhprasad0/nova-toll-budget-agent/issues/542)
covers synthetic latency publication, explicitly excludes optimization, and
predates checked streaming. Update its measurement assumptions when implementing.

**Done when:** a fixed workload measures from client request start to first
activity event, first checked answer text, and completed answer separately.
Publish release identity, caller location, session setup, concurrency, cache
state, output-token counts, sample counts, p50/p95, failures, and cost. Label
synthetic client timings separately from browser-rendered experience. Separate
current-price and annual-commute scenarios, and verify the expected tool/response
contract so a fast wrong answer cannot count as success. Show all attempted
outcomes alongside successful-response percentiles.

Use traces to attribute initialization, model, guardrail, database, and network
time. Establish cold/warm state through instrumentation; a new session alone
does not prove a cold runtime. Declare the primary metric and sample plan before
the comparison, repeat comparable runs with the model and prompt held constant,
and preserve existing correctness and safety checks. Publish negative results
too. If no safe improvement is achievable without an unacceptable cost or
correctness tradeoff, record that finding without claiming a speedup. Do not
report tool activity as model time-to-first-token or tiny samples as convincing
tail-latency evidence.

### 2. Preserve active conversations through rollout and rollback

- [ ] **Demonstrate eligible conversations continuing in the same open browser
  tab across production promotion and rollback, with explicit restart when a
  release must be withdrawn.**

**Why:** stateful deployment correctness is directly relevant to agent platforms.
Anthropic's [production engineering account](https://www.anthropic.com/engineering/multi-agent-research-system)
discusses preserving running agents during deployment, separately from checkpoint
and resume behavior.

**Current:** release mismatch deliberately rejects the session.
[Issue #545](https://github.com/rhprasad0/nova-toll-budget-agent/issues/545)
verifies that restart behavior; completing it as written will not deliver
continuity. Reconcile its acceptance criteria with this new goal.

**Done when:** a development rehearsal precedes an approved production
demonstration. Test conversations created both before and after promotion.
Eligible sessions remain associated with a healthy, compatible retained release;
new sessions reach the active release. If rollback withdraws an unsafe or
unhealthy release, stop its affected sessions and show an explicit restart
explanation. Session affinity must not keep that release serving those sessions.

Preserve isolation and release fencing while routing each eligible session to
its release. Cover compatibility with shared database changes, bounded draining,
protection against overwriting a slot that still serves sessions, concurrent
requests, reset behavior, and actual terminal answers. Do not silently replay an
uncertain turn or claim in-flight execution survived unless it was observed.
Retain sanitized browser and release evidence; a deliberate restart is a safe
exception, not proof of uninterrupted continuity.

**Boundary:** preserve the existing one-hour absolute limit, 15-minute idle
expiry, and five-turn cap. Long-lived saved history and recovery after runtime
loss are separate capabilities, not requirements for this item.

### 3. Get independent use and record what it changes

- [ ] **Run a small external pilot and publish the findings and resulting
  changes, including negative results.**

**Why:** this addresses a gap infrastructure alone cannot fill: whether other
people can complete a useful task without the builder guiding them.

**Current:** there are no real users. Start with a small qualitative sample,
such as three to five people with relevant commute questions; this is a proposed
exercise, not existing adoption or a statistically representative study.

**Done when:** record task completion, confusion, failures, and whether anyone
chooses to return. Observe without coaching every interaction, capture consented
feedback, and show which changes followed. If nobody finds the application
useful, report that and explain what the infrastructure demonstrations still
prove. Do not manufacture adoption claims or turn this into a growth project.

### 4. Establish a measured capacity and failure envelope

- [ ] **Publish bounded load results and one failure case study from detection
  through diagnosis, recovery, and corrective action.**

**Why:** this demonstrates the cross-system reasoning and latency/availability
tradeoffs described in [Anthropic's AI reliability role](https://job-boards.greenhouse.io/anthropic/jobs/5101173008).

**Current:** the [proxy configuration](../infra/agentcore.tf) limits each slot to
five concurrent executions and includes timeout and latency alarms. Controls
exist; a reproducible capacity study remains missing.

**Done when:** test below, at, and above configured capacity in development with
hard request and cost caps. Report admitted/completed/rejected requests, latency,
database pressure, provider throttles, retry amplification, spend, and time to
recover. Exercise bounded model/database failures and client disconnection;
verify timeout behavior and session-lease recovery. Define workload-specific
service objectives with attempted/completed denominators, observation windows,
and missing-probe handling. Label the case study a drill, not a customer incident.
Fix demonstrated bottlenecks before adding queues or autoscaling machinery.

### 5. Finish cost per successful turn and explain the tradeoffs

- [ ] **Publish a reproducible per-turn cost calculation alongside fixed
  infrastructure overhead and measurement coverage.**

**Why:** an owner must explain what the service costs and what an improvement
buys. Reliability, latency, and cost belong in the same engineering decision.

**Current:** the billing dashboard exists; per-turn attribution remains open in
[issue #543](https://github.com/rhprasad0/nova-toll-budget-agent/issues/543).

**Done when:** reuse the latency workload and account for model calls, cache
usage, failures, retries, and completed turns. Verify the applicable rate source
and effective date during implementation. Separate attributable inference and
other measurable request costs from idle infrastructure and organization-wide
billing. Include failed-request spend in the scenario's cost per completed turn;
show missing usage and allocation uncertainty. Explain the cost effect of the
latency or rollout-continuity change. Do not divide the whole cloud bill by a few
chats and call that the marginal cost of an answer.

### 6. Make the shop understandable and operable by another engineer

- [ ] **Complete an independent operator walkthrough and publish a compact,
  accurate engineering evidence packet.**

**Why:** repeatable workflows, reduced manual effort, and operational ownership
align with [OpenAI's developer productivity role](https://openai.com/careers/software-engineer-developer-productivity-san-francisco/).
Independence here means someone can follow the system, not that the original
builder never needs help.

**Current:** substantial delivery proof exists but is scattered, and some status
text is stale. The [September 22 development run](https://github.com/rhprasad0/nova-toll-budget-agent/actions/runs/35716572248)
failed during deployment and final evidence reporting. The [September 20 release
event](https://github.com/rhprasad0/nova-toll-budget-agent/actions/runs/35546064765)
succeeded, but its [downstream delivery](https://github.com/rhprasad0/nova-toll-budget-agent/actions/runs/35546070609)
failed before planning. Neither proves the latest main commit is serving. These
are dated observations; investigate current status before prescribing a fix.

**Done when:** another engineer follows verification and release instructions
within appropriate access boundaries. Record elapsed time, intervention required,
and confusing steps; simplify one demonstrated problem without removing a safety
invariant. Reconcile runbooks, actual serving identity, current delivery failures,
and outstanding qualification in [#308](https://github.com/rhprasad0/nova-toll-budget-agent/issues/308)
and [#362](https://github.com/rhprasad0/nova-toll-budget-agent/issues/362). Publish
a short architecture explanation and two or three case studies linking decisions,
measurements, failures, and outcomes. Explain personal contributions and AI
assistance. Preserve the routing-versus-browser limitation of the earlier rollback
evidence rather than rerunning completed work merely to create another artifact.

### 7. Prove data freshness independently of pipeline activity

- [ ] **Demonstrate frozen upstream data, duplicate/out-of-order delivery, and
  ingestion recovery without mislabeling stale prices as current.**

**Why:** dependable AI applications need dependable data beneath their tools.

**Current:** the [loader](../lambdas/loader/handler.py) handles ordering and
duplicates, and [pricing SQL](../db/analysis.sql) rejects stale observations.
However, the [freshness alarm](../infra/main.tf) counts successful loader
executions; an old or no-op replay can still emit `V2_LOAD_OK`.

**Done when:** in an isolated development replay, freeze upstream observation
timestamps while ingestion continues, replay older and duplicate inputs, and
recover a failed load. Verify the final database state against the expected
result and confirm stale prices remain unavailable as current quotes. Expose
source observation age separately from pipeline liveness. Reuse existing
ingestion mechanisms and deterministic checks.

### 8. Demonstrate database restoration

- [ ] **Restore an approved development backup into an isolated target and
  publish measured recovery results.**

**Why:** application routing recovery cannot repair lost data or undo committed
schema changes. Backups are useful only if restoration works.

**Current:** [RDS configuration](../../infra/rds.tf) includes backups and deletion
protection. Disposable database contracts and the [migration runbook](../RUNBOOK.md)
do not establish a completed deployed-database restoration.

**Done when:** verify restored schema, roles, known data watermark, and test-client
access; measure recovery time and recoverable data loss with explicit start/end
boundaries. Document cleanup and the accepted single-AZ and shared-dependency
limits. Use existing reviewed procedures and approvals; this TODO does not
authorize a production restore, migration, or availability change.

### 9. Consolidate security evidence around actual boundaries

- [ ] **Assemble a bounded verification packet for session isolation,
  credential/origin controls, and telemetry failure behavior.**

**Why:** platform ownership includes showing that isolation and diagnostics
still behave correctly when dependencies fail.

**Current:** security controls and checks are already substantive. Reuse the
[security policy](../../SECURITY.md), proxy tests, release checks, and
[telemetry verification procedure](../runbooks/telemetry-pii-redaction.md).

**Done when:** link existing proof, then fill only missing evidence using
synthetic data. Show rejection across session boundaries, enforcement of
credential/origin controls, safe omission when redaction fails, and diagnostic
metadata that remains useful. Distinguish code tests from deployed observations
and probabilistic redaction limits. Publish sanitized results, not private logs
or credentials. Another security subsystem is not the objective.

## Constraints and completion standard

- Keep latency, cost, and reliability as separate public pages and reuse existing
  snapshot publishing. Public page views must not trigger experiments or inference.
- Retain the existing agent-quality release gates and finish outstanding
  qualification. Do not expand this roadmap into an evaluation program or change
  the application model/prompt to improve infrastructure measurements.
- Do not add Kubernetes, GPU serving, multi-agent orchestration, multi-region
  infrastructure, or a generic platform just for signaling. Revisit them only
  for a target role or a demonstrated requirement.
- For each completed item retain the exact release, environment, workload or
  scenario, measurement window, outcomes, limitations, and inspectable evidence.
  Mark evidence as implemented, tested, or observed; do not treat those as
  interchangeable. Preserve failures and distinguish synthetic from external use.
- This document records future work. Executing paid experiments, changing access,
  or deploying follows the repository's existing authorization and release rules.
