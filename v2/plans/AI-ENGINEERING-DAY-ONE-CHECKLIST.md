# TollChat — Badass AI Engineering Checklist

**Goal:** Make TollChat unmistakable evidence of strong practical AI engineering: a real agent with defensible evaluations, observable behavior, controlled releases, and honest failure analysis.

**Core story:** I operate a real agent, know how it fails, measure those failures, and use a controlled release process to ship improvements.

This checklist intentionally favors a small number of defensible artifacts over framework breadth. The “theater” is **honest production rehearsal**: synthetic incidents, candidate releases, and model comparisons that exercise real controls without pretending TollChat has traffic or operators it does not have.

---

## 1. Keep every public claim accurate

- [ ] Replace every description of the existing experiment as a “1,000-case eval set.”
- [ ] Describe it as **one frozen commute fixture, five prompt variants, and 200 repeated generations per variant**.
- [ ] Use the defensible result: **996/1,000 responses stayed within supplied quantitative evidence; 999/1,000 contained no incorrect quantitative fact.**
- [ ] Link the complete methodology, denominators, failures, and limitations beside the result.
- [ ] Do not describe optional MCP, AgentCore Gateway, AgentCore Memory, shadow traffic, or persistent production traces as current architecture.
- [ ] Do not claim production scale, users, SLOs, or percentiles unsupported by meaningful traffic.

---

## 2. Prove the day-one contribution loop

- [ ] Create `docs/day-one-walkthrough.md` around one realistic assignment:

  > “A prompt, model, or tool change may have regressed grounded answers. Determine whether it is safe to release.”

- [ ] Make the walkthrough require the engineer to:
  1. run the relevant offline tests;
  2. reproduce a known failure from a frozen fixture or trace;
  3. classify the failure;
  4. make or inspect a candidate change;
  5. run representative live evals in development;
  6. compare the candidate with the accepted baseline;
  7. inspect at least one failed trace;
  8. approve or reject the release with evidence;
  9. identify the rollback target.
- [ ] Keep setup and commands copy-pasteable from a clean checkout.
- [ ] State which steps require AWS access and provide an offline path for the rest.
- [ ] Include the expected outputs so another engineer can tell whether each command worked.
- [ ] Time the walkthrough; a prepared engineer should be able to complete it in roughly one focused session.
- [ ] Have another person follow it once without coaching and fix the confusing parts.

This is the central demonstration: **join the repository, investigate agent behavior, and make a defensible ship/no-ship decision.**

---

## 3. Build the minimum credible release loop

### 3.1 Development and production

- [ ] Finish the existing development/production isolation work.
- [ ] Keep separate AWS accounts, state, permissions, runtimes, databases, and deployed credentials.
- [ ] Store deployed credentials in SSM Parameter Store.
- [ ] Build once per commit and promote the **same artifact bytes** from development to production.
- [ ] Keep the production tool set explicit and versioned.
- [ ] Require human approval before production promotion.
- [ ] Retain a known-good rollback target.

### 3.2 Candidate release evaluation

- [ ] Run the existing representative behavioral suite against the candidate in development.
- [ ] Record the accepted baseline and compare the candidate against it.
- [ ] Grade at least:
  - correct tool selection;
  - valid tool arguments;
  - clarification when required;
  - supported-route task completion;
  - quantitative grounding;
  - prohibited or unsafe behavior.
- [ ] Keep deterministic graders for facts that code can verify.
- [ ] Calibrate any model grader against human judgments before treating it as a gate.
- [ ] Classify failures consistently: tool selection, tool arguments, tool execution, grounding, instruction following, safety, or infrastructure.
- [ ] Make the report show task-level failures before aggregate scores.
- [ ] Fail promotion on a real regression rather than relying on an impressive aggregate score.
- [ ] Save both passing and failing release reports as durable artifacts.
- [ ] Include at least one documented candidate that the gate rejected.

### 3.3 Release manifest

- [ ] Attach the following to each demonstrated release:
  - git SHA;
  - artifact digest;
  - model identifier;
  - prompt version;
  - tool-contract version;
  - evaluation report;
  - development smoke-test result;
  - production smoke-test result;
  - rollback target.
- [ ] Document the flow as:

  > **versioned change → development runtime → representative eval → trace inspection → approval → production smoke test → rollback if needed**

---

## 4. Make one execution trace review-ready

- [ ] Add OpenTelemetry tracing to development and synthetic evaluation runs.
- [ ] Prefer the existing Strands / AgentCore / CloudWatch path over a new observability stack.
- [ ] Capture:
  - request or fixture ID;
  - model, prompt, and tool versions;
  - model/tool spans;
  - validated tool arguments and results;
  - grader outcomes and explanations;
  - latency;
  - input/output tokens;
  - estimated cost where reliable.
- [ ] Publish one sanitized trace that can be explained from request to grader result.
- [ ] Show the trace alongside its release decision.
- [ ] Use synthetic fixtures or explicitly consented development data.
- [ ] Do not persist production conversation text unless the privacy policy and implementation are deliberately redesigned.

---

## 5. Turn a real failure into the centerpiece

- [ ] Publish a concise postmortem for the **Dulles-to-Reagan cross-direction false invariant** or another genuine eval-discovered failure.
- [ ] Include:
  - observed behavior;
  - user impact;
  - why existing tests missed it;
  - the failed trace or fixture;
  - root cause;
  - correction;
  - regression case;
  - release/rollback decision.
- [ ] Be able to walk through the failure without relying on a model-generated summary.
- [ ] Optionally write up the incorrect-time generation as a second, smaller failure story.

**Walkthrough to prepare:** “Here is what failed, how the eval found it, what the trace showed, and the test that prevents it from returning.”

---

## 6. Add legitimate repeated-trial reliability

- [ ] Select a representative subset of behavioral tasks rather than repeating only one fixture.
- [ ] Run at least three independent trials per selected task initially.
- [ ] Publish the task count, trials per task, model/settings, grader, and raw failures.
- [ ] Calculate per-task and suite-level `pass^k` only from repeated independent trials.
- [ ] Keep the original 1,000-generation stress test as a separate experiment.
- [ ] Treat `pass^k` as supporting reliability evidence, not a substitute for representative tasks and readable failures.

---

## 7. Demonstrate model and prompt decision-making

- [ ] Run one baseline-versus-candidate comparison using the same representative tasks and trial count.
- [ ] Compare:
  - task success;
  - quantitative grounding;
  - tool-use failures;
  - latency;
  - tokens and estimated cost;
  - notable qualitative regressions.
- [ ] Write a one-page decision record stating what changed, what improved, what regressed, and whether the candidate should ship.
- [ ] Prefer a real upcoming model or prompt decision over a contrived benchmark.
- [ ] If the candidate loses, publish the rejection; refusing a fashionable model for evidence-backed reasons is a stronger artifact than forcing a win.
- [ ] Do not tune on the final reported cases and then describe the result as an unbiased evaluation.

---

## 8. Rehearse an incident and rollback

- [ ] Inject one safe synthetic failure in development, such as malformed tool output, a tool timeout, schema drift, or an invented quantitative claim.
- [ ] Detect it through the same trace and evaluation path used by candidate releases.
- [ ] Follow a short runbook to:
  1. confirm impact;
  2. identify the failing layer;
  3. stop or reject promotion;
  4. select the last known-good artifact;
  5. restore or redeploy it;
  6. run smoke tests;
  7. add a permanent regression case.
- [ ] Preserve the drill report with timestamps and command output.
- [ ] Label the artifact **simulation**; do not present it as a real production incident.
- [ ] Ensure the drill cannot mutate production data or deployed schemas.

---

## 9. Show team-ready change review

- [ ] Add a concise pull-request checklist for prompt, model, grader, or tool changes:
  - behavior being changed;
  - affected contract/version;
  - representative eval result;
  - candidate-versus-baseline delta;
  - failed traces reviewed;
  - privacy/security impact;
  - latency/cost impact where measurable;
  - rollout and rollback plan.
- [ ] Add a small ownership map for prompts, tools, graders, fixtures, deployment, and operational docs.
- [ ] Record important engineering decisions, including why deterministic code owns routing and money.
- [ ] Document how to add a new eval case discovered during development or an incident.
- [ ] Keep review artifacts short enough that a teammate would actually use them.

---

## 10. Package the repository for a 90-second review

- [ ] Keep the live URL and screenshot above the README fold.
- [ ] State the hard problem: correct toll and commute-pay answers under incomplete, directional, and time-sensitive data.
- [ ] State the trust boundary: **the model talks; deterministic tools route and price**.
- [ ] Add a short **How a change ships** section linking the release manifest and eval report.
- [ ] Add a short **What an eval caught** section linking the postmortem.
- [ ] Link the day-one walkthrough, candidate decision record, and rollback drill.
- [ ] Link one sanitized trace walkthrough.
- [ ] Link reproduction commands for offline and live evals.
- [ ] Clearly distinguish unit tests, behavioral cases, and repeated generations.
- [ ] Keep the architecture diagram faithful to the deployed system.
- [ ] Retain privacy, limitations, supported coverage, and refusal behavior.
- [ ] Remove framework bingo and unsupported “production-grade” language.

---

## 11. Publish the engineering evidence

- [ ] Publish three concise technical write-ups in the repository or on TollChat:
  1. **The eval that caught a real toll-routing bug**
  2. **Why 996/1,000 generations is not a 1,000-case eval set**
  3. **How a TollChat change goes from trace to release gate to rollback**
- [ ] Each post should contain one concrete artifact, one result, and one limitation.
- [ ] Link to the relevant repository page rather than only the homepage.
- [ ] Link all three from the README so the evidence is visible without hunting through the repository.

---

## 12. Optional MCP demonstration

- [ ] Build this only after the release gate, trace, and postmortem are public.
- [ ] Expose the existing deterministic pricing capabilities through a small read-only MCP server.
- [ ] Reuse the existing validation and tool contracts.
- [ ] Demonstrate one external client calling it.
- [ ] Describe MCP as an optional interoperability surface.
- [ ] Keep the public Strands agent on its existing native tools unless MCP provides a real operational benefit.

---

## 13. Do not build for signaling alone

- [ ] No multi-agent topology without a task that needs multiple agents.
- [ ] No RAG or long-term memory without a retrieval or memory requirement.
- [ ] No AgentCore Gateway merely to place “Gateway” in the diagram.
- [ ] No fake human escalation without a real operator and response process.
- [ ] No production-prompt shadowing that violates the privacy posture.
- [ ] No “14 days of traces” requirement; one excellent sanitized trace is initially enough.
- [ ] No P99 or SLO claim from an insignificant sample.
- [ ] No fallback chain merely to make the system look enterprise-ready.
- [ ] No new platform abstraction when the existing tool and release contracts already demonstrate the principle.
- [ ] No unlabeled simulation passed off as production history.
- [ ] No dashboard without a decision or investigation it helps perform.
- [ ] No eval score without raw failures, denominators, and a stated release consequence.

---

## 14. Definition of done

The engineering proof package is complete when these artifacts are public and linked from the README:

- [ ] Existing evaluation claims use accurate denominators and clearly state their limitations.
- [ ] A clean-checkout day-one walkthrough ending in an evidence-backed ship/no-ship decision.
- [ ] One candidate release evaluated against an accepted baseline.
- [ ] One release manifest showing versions, evidence, promotion, and rollback target.
- [ ] One sanitized end-to-end trace with evaluation outcome, latency, tokens, and cost.
- [ ] One real failure postmortem with a permanent regression case.
- [ ] One representative repeated-trial reliability report with honest denominators.
- [ ] One baseline-versus-candidate model or prompt decision record.
- [ ] One clearly labeled incident-and-rollback simulation.
- [ ] One concise change-review checklist another engineer could use.

**Optional MCP is not part of the minimum packet.**

The outcome is not a pile of AI buzzwords. It is a repository that shows **sound judgment under real agent failure modes**.
