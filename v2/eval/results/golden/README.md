# Golden baseline evidence

The active [200-case contract](../../GOLDEN_EVAL_SPEC.md) and
[policy 2.0.0](policy-2.0.0.json) await exact review. The measurements below are
historical 24-case results and cannot be compared directly with the expanded set.

[September 21 calibrated comparison baseline](calibrated-baseline-20260921.md):
58/71 scored trials passed (81.7%); critical pass³ was 12/17 (70.6%).
All 72 trials were attempted, with one actor-invalid trial inconclusive.
This is a provisional source-checkout reference, not a qualified production baseline.

[Open the static review page](review.html). It works offline and shows case
failures before aggregate results, followed by eight transcript samples and
the approved policy.

**The initial measurement is retained. The production reference is unset.**
The first run completed 72 trials: 27 passed (37.5%), and 3 of 24 cases passed
all three trials (12.5%). Those numbers include known actor and grader problems.
They are historical results, not an approved estimate of production quality.

`registry.json` has separate `initial` and `production` references. The initial
reference points to a byte-for-byte copy of #360's `demo-1` manifest, journal,
JSON report, and Markdown report. Each file has a SHA-256 digest. The directory
name hashes that inventory. Review annotations live outside that directory;
they never change the original verdicts or scores. Previous approvals remain in
the registry when the production reference advances. Git preserves revisions
of the registry itself.

## Approved policy 1.0.0

The owner approved these limits in the planning conversation and then requested
implementation. `policy-1.0.0.json` records that approval and its content hash
before any new candidate run. This is approval of the policy, not of the latest
calibration, a candidate, or a production deployment.

| Requirement | Fixed limit |
| --- | --- |
| Coverage | All 24 cases, exactly 3 fresh trials each, 4 workers |
| Critical cases | Every case passes 3/3 |
| Noncritical cases | Every case passes at least 2/3 |
| Suite success | At least 90% |
| Suite pass³ | At least 75% |
| Noncritical regression | Sum of lost passing trials across cases is at most 1; gains cannot cancel losses |
| Total agent + actor + judge cost | At most $5 per full run |
| Agent cost / successful trial | At most $0.05; undefined values fail |
| Trial latency | Median at most 30 seconds; p95 at most 60 seconds |
| Candidate freshness | At most 24 hours from run creation |
| Production comparison freshness | At most 30 days from run creation |
| Transcript sample | 8 trials, deterministically selected |
| Replacement runs | At most 1, only for reviewed infrastructure or actor invalidity |
| Output budget | 2,048 tokens per model call; existing case turn/tool limits also apply |

The correctness floors describe the expected supported behavior. They are not
fitted to the low initial score. Each lost trial changes a case's measured rate
by one third, so regression is counted in trials rather than a misleading
fractional case tolerance. The initial run cost $0.3888863, with 23.51-second
median and 41.51-second p95 trial latency. The resource limits allow headroom
for provider timing and cache differences. Cost includes failed trials; it does
not include prior calibration runs, which remain in the cumulative spending
ledger. Neither the $5 run gate nor this PR increases the authorized $25 total
spending ceiling.

The policy pins corpus 1.0.7 and harness 1.1.0, their fixtures, cases, grading,
actor settings, tool schemas, model settings, and prices through an evaluation
contract digest. Application commit, executable artifact, and rendered prompts
are recorded separately. Changing the evaluation contract requires a new
reviewed policy and comparable runs. Unknown versions, missing values, weakened
limits, invalid approval hashes, future timestamps, and incomplete evidence fail
closed. There is no automatic threshold adjustment.

## What remains before #362 can close

1. Human-adjudicate the two grounding disagreements in
   [calibration 7](../../evidence/golden-360/calibration-7/review.html). Its outcome
   labels agree on 34/34 examples; grounding agrees on 32/34. Approved outcome
   labels remain unchanged. No calibration approval is implied by this PR.
2. Review critical failures and actor validity. The initial report used corpus
   1.0.5 and cannot be compared directly with 1.0.7. Run the original and
   production agents on the same corrected contract, where available; otherwise
   document and approve requalification. Keep the historical report either way.
3. Obtain complete, valid evidence for the verified production artifact that
   passes every fixed limit, plus the required human reviews and matching
   successful approved deployment/canary evidence. The current runner identifies
   source checkouts. The release bundle contains ARM64 dependencies; a local
   checkout run does not prove that those executable bytes were evaluated.

Application improvements are separate work. A new run that fails remains in the
archive and leaves the production reference unset. #363 owns executing the exact
release artifact in a compatible environment, authenticating workflow evidence,
and enforcing the production gate. This PR supplies an offline qualification
contract and local bookkeeping, not release authorization.

## Known regressions and uncertainty

All conversation inputs and frozen tool responses in this set are synthetic.
The failures below were observed in the paid demo; they are not production
incidents. The synthetic promotion tests are labeled separately and never
populate the real production reference.

| Observed behavior | Interpretation and retained evidence |
| --- | --- |
| Greenway estimate rejected for not being an official quote | Judge/disclosure problem; supporting domain facts were clarified later |
| Origin correction and salary clarification stopped early | Actor invalidity; affected application-quality interpretations are inconclusive |
| Franconia-Springfield Parkway selected 206NO instead of approved 212NO | Ambiguous alias; owner kept 212NO and approved clearer wording in 1.0.7 |
| Negated “not $0.00” flagged as an invented price | Mechanical-check regression fixed after the original run; original failure retained |
| Divergent-leg confirmation returned with stop=true | Held-out actor invalidity; confirmation never reached the application |
| Pentagon/Eads Street maps to two frozen IDs | Unresolved catalog ambiguity; review exact-ID failures before attributing them to the agent |

The [original demo review](../../evidence/golden-360/DEMO_REVIEW.md) records eight
earlier inspected samples. The static page here selects another deterministic
sample: first a held-out, failing, and passing trial when available, then sorted
remaining trial IDs until eight are selected. All cases are visible in aggregate;
all transcripts remain in the raw report. Every critical failure needs human
review, even when it falls outside the eight displayed samples.

Held-out cases were visible during authorship. Case 23 also had prior regression
exposure; its demo transcript was inspected after the full run. Rendering this
page exposes its selected held-out transcript as well. Do not use exposed
held-out examples for tuning while continuing to call them untouched holdouts;
reclassify or replace them and requalify the changed suite. Existing exposed
reports remain historical evidence.

Three repeats do not establish a precise failure probability. Trials share cases,
fixtures, and provider conditions. The reported 95% case-cluster bootstrap
interval (25–50% in the initial run) describes this finite corpus; it is not a
population guarantee. Zero observed violations do not establish zero risk.

## Commands and review contract

From `v2/`:

```bash
uv run python -m eval.golden_baseline capture --run eval/evidence/golden-360/demo-1
uv run python -m eval.golden_baseline review --run eval/evidence/golden-360/demo-1 --output eval/results/golden/review.html
uv run python -m eval.golden_baseline qualify --run RUN --review HUMAN_REVIEW.json --calibration CALIBRATION --baseline PRODUCTION_RUN --baseline-review PRODUCTION_REVIEW.json
uv run pytest -q tests/test_golden_baseline.py tests/test_development_deployment_status.py
```

Omit the two baseline arguments only for initial bootstrap. The qualifier checks
report values against a fresh offline rendering of the recorded journal. It
never modifies the input report, calls a model, or contacts a deployed service.
It prints a decision with bound report/policy/review/configuration identities;
failure returns a nonzero exit status. `capture` is idempotent for identical
bytes and rejects an attempt to replace the initial reference. For subsequent
runs, use the `archive()` helper without resetting the initial reference.

A human review contains `status`, `reviewer`, `evidence` (review notes),
`approved_at`, `evidence_sha256`, `report_sha256`, and `policy_sha256`. It also
records the exact sorted `critical_failures_reviewed` case IDs, `sample_ids`
returned by `sample_ids(report)`, `actor_validity: "valid"`,
`unresolved_findings: []`, and a nonempty `held_out_exposure` note. Listing IDs
does not replace reading the underlying evidence.

Before execution, retain an `execution` declaration with `declared_at`, the
`identity_sha256` of the full frozen executable identity, `policy_sha256`, the
selected `baseline_report_sha256` (null for bootstrap), `replacement_number: 0`,
and `supersedes: null`. Include that unchanged declaration in the human review.
Local timestamps establish a review contract; #363 must authenticate that the
declaration existed before execution. This module cannot authenticate a person
or a caller-supplied JSON document.

Calibration approval is `CALIBRATION/review.json`, bound to its evidence digest.
It includes an `approved_at` before candidate execution, an
`adjudicated_disagreements` mapping of every disputed example ID to its recorded
disagreement list, and `unresolved_findings: []`; review notes explain the
adjudication. A missing or stale-contract calibration blocks qualification.

For a replacement, retain both complete run directories; never combine trials.
Set `replacement_number: 1` and `supersedes` to the prior evidence digest. Pass
`--superseded PRIOR_RUN --superseded-review PRIOR_REVIEW.json`. The prior review
must contain a digest-bound `rerun_authorization` approved before the replacement
declaration, with reason `infrastructure` for an incomplete run or
`actor_validity` for a run explicitly reviewed as invalid. A second replacement,
changed identity, or an unchanged quality failure cannot use this path. A changed
agent or suite is a new reviewed experiment, not a replacement attempt.

`update_registry()` is the local post-promotion helper, deliberately absent from
the CLI. It requires a qualified decision, a matching successful migration,
apply/readiness and existing canary record, and a human approval bound to that
decision and promotion evidence. The timezone-aware timestamps must satisfy
`run_created_at <= evaluated_at <= completed_at <= approval.approved_at <= now`;
`completed_at` records completion of deployment and its canary. It reuses the existing canary validator,
checks the expected prior production reference, and writes the history and new
reference atomically under a file lock. Its caller must first authenticate the
deployment and approval provenance; #363 supplies that protected integration.
The candidate report must already be archived under its content hash; missing
or changed bytes block the update. The pending `initial-review.json` records
outstanding reviews and assistant findings without claiming human approval.
Failed promotion leaves `registry.json` byte-for-byte unchanged. The
[protected release integration](../../GOLDEN_RELEASE.md) uses the same qualifier
with versioned development S3 storage. Policy 1.0.2 has exact-contract
approval; approved policy 1.0.1, policy 1.0.0, and this historical archive are retained.
