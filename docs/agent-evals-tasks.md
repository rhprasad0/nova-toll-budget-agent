# Agent Evals — Tasks

Status: in progress · Owner: Ryan Prasad · Last updated: 2026-07-26

Working checklist for building a `strands-agents-evals` suite over
`agent/toll_agent.py`, before any AgentCore deployment work starts. Worked
one task at a time, checked off in place as each lands — not a spec for
finished work (contrast `docs/oracle-tools-spec.md`'s `Status: implemented`);
this graduates to that style once there's a finished design to describe.

## 1. Scope

In scope: build-time evals for `toll_agent.py`'s orchestration (tool
selection, cross-corridor leg-splitting, refusals, error surfacing). Out of
scope: staging validation, shadow-mode traffic replay, A/B rollout, and
AgentCore Evaluations sampling live OTel traces post-deployment — all of
that depends on AgentCore infrastructure that doesn't exist yet.
`docs/oracle-tools-spec.md` §4 already names OTel traces as the eventual
successor to the tools' own `INFO`-log audit trail; nothing new to decide
there, just not this task.

Today, `agent/tests/test_toll_agent.py` only asserts on the static
system-prompt string, and `tests/test_toll_agent_live.py` is a single
hand-rolled live scenario (Dumfries → Westpark) that walks `agent.messages`
to confirm the agent splits at the Springfield junction instead of
overshooting to Washington D.C. — a real failure a manual smoke test once
caught. This work generalizes that one case into a real suite and fills in
everything it doesn't cover.

## 2. The constraint that shapes the whole design

`trip_pricing_i95`/`trip_pricing_i495` refresh every 10 minutes.
`tests/test_toll_agent_live.py`'s own docstring already explains why it
never asserts on dollar amounts: a hardcoded price fails tomorrow and reads
as an agent regression when it's really just a stale rate. That rules out
`Case(expected_output=...)` and `OutputEvaluator` scoring on price content
anywhere prices are real (non-`dulles_route`) data.

So this suite is **trace-first, not output-first**: assert on which tools
were called, with what parameters, in what order, and whether the agent's
narration matches what the tools actually returned — not on the dollar
figure. `dulles_route` is the one exception where fixed-toll output could
be asserted verbatim, if that's ever useful.

This also means the suite does **not** re-test tool internals —
`agent_tools/tests/` already covers each tool's own correctness (label
resolution, error shapes, pricing math). This suite tests orchestration
only: did the agent choose, sequence, and interpret the tools correctly.

## 3. Decisions

- **Rigor level: lean, targeted subset**, not the full AWS Strands+
  AgentCore blueprint's 3-layer system. Deterministic tool-selection/
  parameter checks are the pass/fail bar whenever the suite runs;
  LLM-judge evaluators are used only on dimensions that are genuinely a
  judgment call. No numeric pass thresholds (no >95%/>85%/>90% targets)
  and no `pass^k` multi-trial repetition for this first version — see §7
  for why, and what to add if flakiness actually shows up.
- **Judge model: Amazon Nova 2 Pro** — a different model family entirely
  from the Claude Haiku `toll_agent.py` runs on, which sidesteps
  same-family self-grading bias. **Unverified as of this writing:** per
  AWS's Dec 2025 Bedrock announcement, Nova 2 Pro was in *preview*,
  "early access available to all Amazon Nova Forge customers" — not
  confirmed generally available on this account. §6 tracks confirming the
  exact model ID, whether it needs a cross-region inference-profile
  prefix (same empirical check `toll_agent.py` already had to do for
  Haiku's `"us."` prefix), and actual account access.
- **Both tiers run on-demand/pre-deploy, not gated on every CI push** —
  see §5.

## 4. Correctness dimensions

Each grounded in a real documented failure mode or system-prompt rule
already in this repo, not invented for the occasion. Tagged with how it's
checked. **This list is a draft — dimension prioritization is Ryan's call,
open for edits.**

1. **No fabricated price/route** *(deterministic + `FaithfulnessEvaluator`)*
   — every reported number must trace to an actual tool return; every leg
   boundary must trace to either a tool call or the documented `JUNCTIONS`
   table in `agent/toll_agent.py` — never invented.
2. **Correct cross-corridor splitting** *(`TrajectoryEvaluator`)* — at the
   documented junction, not overshoot (`toll_agent.py`'s `_ANTI_EXAMPLE`).
   The Dumfries→Westpark case already covers i95↔i495; extend to
   i66_itb↔i495 and i495↔dulles_toll_road. The i495↔dulles_toll_road case
   is lower-confidence than the other two: its junction evidence in
   `JUNCTIONS` is explicitly the weakest ("route-number correlation," not
   a verbatim label match) — a failure there may mean the junction data
   deserves another look, not that the agent regressed.
3. **Correct refusal on unevidenced junctions** *(`RefusalEvaluator`)* —
   `dulles_greenway`↔`i495` and `i66_otb`↔`dulles_toll_road`: say "not
   enough data," never guess a connection.
4. **Correct refusal when no pricing tool exists at all**
   *(`RefusalEvaluator`)* — I-66 OTB is locatable via
   `find_toll_locations` but has no route tool; the agent must say so, not
   substitute a nearby corridor's price.
5. **`find_toll_locations` disambiguation quality** *(deterministic —
   `ToolSelectionAccuracyEvaluator`/`ToolParameterAccuracyEvaluator`
   already cover "resolved to the right label," since that's the
   observable signal on the pricing call that follows)* — vague/misspelled
   human input resolves correctly before a pricing tool is called.
6. **Multi-leg reporting shape** *(deterministic string/shape check on the
   final output — not a judge model)* — never fuse a cross-corridor trip
   into one price; separate legs, name the untolled connector, a
   clearly-labeled summed total. This is a mechanical formatting rule, not
   a judgment call, so a plain check is cheaper and more reliable than an
   LLM judge here.
7. **Faithful error surfacing** *(`FaithfulnessEvaluator`)* — a tool hard
   error (e.g. i95's closed-lane gate) is reported as what it is, never
   silently dropped or worked around.

No numeric thresholds are attached to any dimension yet, by decision, not
oversight (§3). Once any metric is actually collected, report it as a
measured result — never phrase a target as an achieved number.

## 5. Two tiers, mirroring the repo's existing `live` marker convention

`pyproject.toml` already splits `-m "not live"` (default, CI-run) from
`-m live` (manual, hits real Bedrock/RDS) for the tool-level tests. This
suite reuses that split — with one correction to how it applies here:
**every eval case invokes the `strands.Agent` itself, which always calls
Bedrock.** Stubbing the tools removes the RDS dependency and the
price-drift problem; it does not remove the Bedrock call. So neither tier
is free the way `ruff`/`pyright`/the tool-unit-tests are — both need AWS
credentials, and today's CI (`.github/workflows/ci.yml`: checkout →
`uv sync` → ruff → pyright → pytest) has none. That means **the whole
suite, repeatable tier included, runs on-demand and pre-deploy, not on
every push**, unless CI grows AWS credentials (a separate, bigger decision
— see §7 task 4).

- **Repeatable tier:** tools stubbed (mechanism TBD — see §6), so no RDS
  and no per-run price drift; deterministic scoring (same input → same
  expected trajectory). Still a real Bedrock call per case. This is where
  the case table and most evaluators live.
- **Live tier (`-m live`, manual/pre-deploy):** a small number of cases
  against real Bedrock + real RDS, to catch drift between the stubbed
  tools and actual tool behavior. Generalizes (does not delete)
  `tests/test_toll_agent_live.py`'s existing Dumfries→Westpark case.

LLM-judge cases cost more than deterministic ones (agent call *and* judge
call per case, non-deterministic score), but the credential/cost boundary
that matters most for CI design is agent-call-at-all, which both tiers share.

## 6. Research notes on `strands-agents-evals`

Verified directly against the `strands-agents/evals` GitHub repo (not blog
paraphrase — one AWS blog post used names like `ToolSelectionGrader`/
`run_all_layers` that don't appear in the actual repo):

- Core API: `Case[InputT, OutputT]` (input, optional `expected_output`,
  optional `expected_trajectory`, `metadata`), bundled into an
  `Experiment`, run via `experiment.run_evaluations(task_fn)` →
  `EvaluationReport` (`.scores`, `.test_passes`, `.reasons`,
  `.overall_score`). A `strands-evals` CLI (`validate`, `run --agent
  module:factory`) wraps the same API for CI.
- Verified evaluator classes: `OutputEvaluator`, `TrajectoryEvaluator`,
  `InteractionsEvaluator`, `ToolSelectionAccuracyEvaluator`,
  `ToolParameterAccuracyEvaluator`, `HelpfulnessEvaluator`,
  `FaithfulnessEvaluator`, `CoherenceEvaluator`, `RefusalEvaluator`,
  `InstructionFollowingEvaluator`, `GoalSuccessRateEvaluator`, plus
  multimodal/chaos variants not relevant here.
- `tools_use_extractor.extract_agent_tools_used_from_messages(agent.messages)`
  turns a trajectory into evaluator input — the formalized version of what
  `tests/test_toll_agent_live.py` already hand-rolls with its own
  `_tool_uses()` helper.
- Simulators: `ActorSimulator` (multi-turn conversation) and
  `ToolSimulator` — both class names confirmed to exist, but neither's
  actual API/intended use was verified (docs described simulators as
  *generating* interactions, which may not mean "pin a fixed return
  value"). **Not assumed further until §7 task 0 confirms it.**
- Default judge model is Bedrock Claude (per docs, "Claude 4"); swappable
  per-evaluator — this is how Nova 2 Pro gets substituted in (§3).
- Docs were served from two different URL shapes (`/docs/...` and
  `/latest/documentation/docs/...`) — smells like version skew between
  doc revisions. §7 task 0 confirms the installed package's actual API
  before real cases get written against it.

AWS's own recommended pattern is two-phase: *build-time* (this doc,
`strands-agents-evals`, gates before deploy) and *production*
(out of scope here — AgentCore Evaluations sampling live OTel traces
post-deployment, LLM-as-judge over real traffic).

## 7. Tasks

### Task 0 — Setup
- [x] Create a worktree branch for this work (repo rule, `CLAUDE.md`) —
      `agent-evals`.
- [x] Commit this checklist as `docs/agent-evals-tasks.md`.
- [ ] Add `strands-agents-evals` as a dev dependency in `pyproject.toml`.
- [ ] Confirm the installed version's actual evaluator API against the
      verified class names in §6 before writing real cases against it —
      spend 15 minutes here, not zero, not a day.
- [ ] Confirm `ToolSimulator` actually does what task 2 needs (pin a fixed
      return value per tool for a `strands.Agent` under test). **If it
      doesn't fit, don't invent a third pattern** — this repo already has
      a working stub convention for exactly this job:
      `agent_tools/tests/conftest.py`'s `FakeConnection` plus the
      `_env_connect`/`_resolve_at_time` module-level aliases each tool
      exposes specifically so `monkeypatch` can stub them
      (`docs/oracle-tools-spec.md` §5). Reuse that before reaching for
      anything new.
- [ ] Confirm Amazon Nova 2 Pro's exact Bedrock model ID, whether it needs
      a cross-region inference-profile prefix (same empirical-check
      pattern `agent/toll_agent.py` already used for Haiku's `"us."`
      prefix), and that this AWS account actually has access — it was in
      preview/early-access as of the Dec 2025 Bedrock announcement, not
      confirmed generally available. Surface it back if inaccessible,
      rather than silently substituting another judge model.

### Task 1 — Case table and evaluators (repeatable tier)
- [ ] New `agent/evals/` (cases + experiment runner), separate from
      `agent/tests/` (prompt-string-only) and root `tests/` (live-only,
      cross-cutting).
- [ ] Stub all 5 tools so cases run with no RDS connection and no price
      drift — using whichever mechanism task 0 confirms fits
      (`ToolSimulator`, or the existing `FakeConnection`/monkeypatch
      convention if it doesn't).
- [ ] Case table (derived from §4's dimensions and the oracle data, per §8
      below — not from real user queries, since there aren't any yet):
  - One happy-path case per tool (i66, i95, i495, dulles fixed-toll).
  - The 3 cross-corridor splits (i95↔i495, i66_itb↔i495,
    i495↔dulles_toll_road — flag the last as lower-confidence per §4.2).
  - The 2 documented negative/unevidenced junctions (refuse, don't guess).
  - The i66_otb "locatable, not priceable" refusal.
  - An ambiguous/misspelled-location case exercising `find_toll_locations`.
  - A stubbed closed-lane tool error, checking the agent surfaces it
    faithfully.
- [ ] Deterministic evaluators (the pass/fail bar when this tier runs —
      "deterministic" means reproducible scoring, not free; every case
      still calls Bedrock, per §5): `ToolSelectionAccuracyEvaluator` +
      `ToolParameterAccuracyEvaluator` against each case's
      `expected_trajectory`, via
      `tools_use_extractor.extract_agent_tools_used_from_messages`; plus a
      plain string/shape check on final output for the multi-leg
      separate-reporting rule (dimension 6 — no judge model needed for a
      mechanical formatting check).
- [ ] LLM-judge evaluators (on-demand, not every push — costs an agent
      call *and* a judge call per case): `TrajectoryEvaluator` for the
      leg-splitting-not-overshooting cases, `RefusalEvaluator` for the
      negative-junction and i66_otb cases, `FaithfulnessEvaluator` for
      "does the narrated price/error match the tool's actual return." No
      other evaluator types needed for the lean subset.

### Task 2 — Thin live tier
- [ ] Keep `-m live`: generalize `tests/test_toll_agent_live.py` into a
      handful of cases (Dumfries→Westpark plus 1-2 ordinary
      single-corridor calls) against real Bedrock + real RDS — a
      pre-deploy smoke that catches drift between the repeatable tier's
      stubbed tools and real tool behavior. Not a full case-table re-run
      against live infra.

### Task 3 — Wire it up
- [ ] Default: run the whole suite (repeatable tier included) on-demand
      and pre-deploy, under the existing `live`-style marker convention —
      **not** on every CI push, since every case calls Bedrock and today's
      `.github/workflows/ci.yml` has no AWS credentials at all. Adding
      OIDC/credentials to CI so some slice runs on every push is a real
      option but a separate, bigger piece of work than this covers — note
      it as a possible follow-up, don't build it now.
- [ ] Document the run commands here.

## 8. Named deviations from the AWS blueprint

Worth calling out explicitly in the write-up, since they're deliberate
choices, not gaps:

- **Blueprint says seed 20-50 cases from real user queries; there is no
  production traffic here.** Cases are instead derived systematically from
  documented failure modes and the oracle data itself
  (`docs/oracle-findings.md` §8, the `JUNCTIONS` negatives, the i95
  closed-lane gate, i66_otb's no-pricing-tool gap) — arguably a *better*
  seed than organic queries would be at this stage, since every case
  traces to a known, evidenced behavior rather than a guess at what users
  might ask.
- **Blueprint defaults `num_trials=5` (pass^k) broadly; this first version
  skips it entirely.** `toll_agent.py` runs at `temperature=0`, and §3
  explicitly drops multi-trial repetition and numeric thresholds for now.
  If real flakiness shows up in practice, the cross-corridor split cases
  are the one behavior with documented history of it (the original
  overshoot bug) and the obvious first candidate for `pass^k` — not a
  reason to add it everywhere today.
- **No numeric pass thresholds (>95%/>85%/>90%)** — that's the full
  blueprint's framework, not adopted here (§3).
