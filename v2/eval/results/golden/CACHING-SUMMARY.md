# Golden eval caching validation

## Current fixture correction

Corpus 1.0.20 corrects `greenway-current-wrong-route`: the call, result, and
answer now consistently describe Route 7 while the user requests Route 28.
Expected labels remain Outcome fail, Grounding pass, and Rules fail. The user
adjudicated the previous Outcome pass as incorrect. Fresh calibration-25 used
eight local workers and reached **180/180 agreement** across 60 development
examples, including Outcome fail / Grounding pass / Rules fail for wrong-route.
All 180 fresh judge calls have complete usage: $0.10953080, 234,420 cache-read
tokens, no cache-write tokens. Linked cumulative spend is $7.60716767.

Candidate: `00585d9bb2696baf7a2aea2f460edd0a71f2c582`. Exact evidence digest:
`95070932bbde164f79d36ca8a76a7fa1508b3c3f46865165c112dfb2d7b2ca32`.
Full manifest, append-only events, reports, and summary remain locally under
ignored `eval/private/critical-pass3/calibration-25/`. The user approved this exact calibration for local execution and authorized
continuation through task completion. Approval is recorded in its private
`review.json`; protected CI activation remains pending.

Initial application run `durable-1` completed at 13/17 critical pass³ and
60/72 successful trials. It remains retained, including a Rules false negative
for a permitted discovery call. Prompt 2.3.1 addresses observed-versus-evaluated
source labels, annualized daily scenario labels, and unchosen salary suggestions.
The next paid run links `durable-1`; no passing streak is claimed yet. All 138 relevant corpus, runner, baseline, and gate tests pass
(including a gate rerun after updating the pending policy contract). Historical calibration-24 evidence remains intact. Pending policy 1.0.9 binds
the corrected corpus contract; numeric thresholds and protected CI workers are
unchanged.

## Historical caching validation

The manual runner and protected eval CI share explicit prefix caching and
cache-write accounting. Application and scheduled-check sources are unchanged.
Adversarial review isolated the factory to the golden runner, bound adapter source
to calibration identity and CI receipts, and corrected stale activation docs.

| Run | Workers | Agreement | Wall time | Cost | Cache reads / writes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Calibration 22 | 4 | 180/180 | 130.67 s | $0.11008381 | 230,513 / 3,907 |
| Calibration 23 | 8 | 179/180 | 70.09 s | $0.10902200 | 234,420 / 0 |
| Calibration 24, after review fixes | 4 | 179/180 | 131.00 s | $0.10971680 | 234,420 / 0 |

Each calibration made 180 fresh judge calls over 60 examples with 516,298 input
tokens and complete usage. Cache savings were 27–28% against the same tokens at
uncached rates, including write charges. Later runs reused warm prefixes. Eight
workers were 1.86× faster in the original comparison; this was not a quota stress
test. Keep four scored workers under the existing timing policy.

Calibration 23 falsely passed Grounding for
`annual-tysons-clarification-silent-modeling`, missing an observed-price claim
despite `uses_modeled=true`. Calibration 24 falsely passed Outcome for
`greenway-current-wrong-route`: it accepted a correct destination in the returned
fixture despite the wrong destination in the call. Rules rejected both examples.
Neither miss was relabeled or rerolled; the four-worker miss means concurrency is
not an established cause. Historical actor checks passed 60/60 (87 calls,
27.80 seconds, $0.01947340); they were not rerun after factory relocation.

**Activation remains pending human adjudication and exact approval** of corpus
1.0.19, harness 1.2.9, and policy 1.0.8. Calibration 24 ran at `17bcdad`; its
evidence digest is
`c92c0dcb52f97b4dbcf87d8e41a0ae19a29a11255d2458c7d7b60c5e20ca9c30`.
This summary is not executable calibration evidence. Full journals and reports
are preserved locally under ignored `eval/private/` and in git at `5bc2e92`;
restore and verify exact evidence before requesting approval or activating CI.
The pending reference intentionally has no executable evidence directory.

Recorded cumulative spend through calibration-24 was $7.49763687;
calibration-25 links it as its prior run. Older totals retain
their documented accounting limitations. Historical application experiments do
not qualify main's application behavior; no new application-scored run was made.

Validation before evidence trimming: 155 focused tests passed, including the CI
execution path and previously failing release-contract checks. Ruff, journal
replay, archive hashes, policy digest, and secret scans passed.
