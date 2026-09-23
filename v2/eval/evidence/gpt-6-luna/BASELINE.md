# GPT-6 Luna: first 200-case baseline

**All 600 trial slots ran: 409 passed, 184 failed, and 7 were inconclusive.** The raw pass rate is **68.97% of 593 scored trials**. This is the first retained local measurement, not a qualified production baseline.

## Results

| Measure | Result |
| --- | ---: |
| Cases / trials attempted | 200 / 600 |
| Scored / inconclusive | 593 / 7 |
| Successful / failed scored trials | 409 / 184 |
| Pass@1 | 409/593 — 68.97% |
| Pass³ under the scoring contract | 96/194 cases — 49.48% |
| Cases passing every trial, across the full corpus | 96/200 — 48.00% |
| End-to-end trial latency, p50 / p95 | 19.03s / 30.69s |
| Application-run elapsed time | 49.2 minutes |
| Application-run cost, including actors and judges | $1.720441030 |
| Calibration plus application run | $2.161853985 of $25 |

Pass³ excludes six cases without three scored trials; their seven inconclusive trials are not passes. The runner therefore reports `complete=false` and `full_corpus_complete=false`, despite all 600 slots being attempted. Its overall confidence interval is withheld. No hidden retries, corrections, or replacements were made.

## Coverage

| Subset | Passed / scored | Pass rate | Inconclusive |
| --- | ---: | ---: | ---: |
| Development | 328/474 | 69.20% | 6 |
| Reserved | 81/119 | 68.07% | 1 |
| Current | 156/223 | 69.96% | 5 |
| Annual | 245/358 | 68.44% | 2 |
| Mixed | 8/12 | 66.67% | 0 |

Development/reserved and current/annual/mixed are separate partitions. Reserved cases are public; these measurements are evidence, not permission to tune against them.

| Coverage family | Passed / scored | Inconclusive |
| --- | ---: | ---: |
| annual_evidence | 57/83 | 1 |
| annual_finance | 47/84 | 0 |
| annual_inputs | 75/108 | 0 |
| annual_routes | 66/83 | 1 |
| current_evidence | 63/72 | 0 |
| current_i95 | 24/56 | 4 |
| current_state | 63/72 | 0 |
| current_unsupported | 6/23 | 1 |
| mixed | 8/12 | 0 |

## Failure patterns

| Recorded primary category | Trials |
| --- | ---: |
| outcome | 78 |
| tool_use | 53 |
| grounding | 35 |
| budget | 15 |
| actor_validity | 7 |
| clarification | 3 |

- **Route selection:** rejected endpoint arguments recur in I-95/I-495 partial routes, Greenway direction changes, and corrected annual routes. For example, `current-restart-accept` uses the wrong duplicate Westpark endpoint in some trials despite the origin-specific SOP rule.
- **Unsupported requests and clarification:** the model calls tools for unsupported cash, HOV, or vehicle profiles, or prices before required clarification. Budget failures here mean tool/turn limits, not exhaustion of the $25 spending ceiling.
- **Annual completeness:** judges flag omitted non-forecast wording, scope/provenance disclosures, coverage details, and required presentation of financial results. These are raw contract judgments and can include judge errors.
- **Concrete arithmetic error:** all three `annual-annual-distance-rounding` trials assert that displayed daily mileage multiplied by commute days exactly equals the returned annual mileage. The values are independently rounded; 23.11 × 240 is 5,546.40, not 5,547.36.

## Grading caveats retained in the score

- **Signed money check:** all three `current-movement-falling` trials fail `unsupported_money` although every semantic judge passes. The deterministic parser treats “down $2.00” as positive $2.00 while the fixture stores −$2.00. No corrected score is substituted.
- **Known judge disagreement:** several Grounding failures reject the documented current-only pricing limitation, repeating the approved calibration finding. These need adjudication before interpreting the score as pure application accuracy.
- **Duplicate endpoints:** `current-source-text-injection` stops at a strict `i495:1859ND` versus `i495:185ND` mismatch. Both frozen catalog entries have the same Westpark label and coordinates; the intended injection behavior is therefore not exercised by those rejected attempts. This deserves case/contract review separately from origin-specific routing violations.
- **Actor validity:** four trials were marked invalid and three uncertain. Several contain earlier application/tool errors, which remain in the evidence rather than disappearing behind the inconclusive classification.

Any future grader or case correction needs a new version and matching calibration. Keep this original baseline. Since both the corpus and evaluation models differ from historical 24-case runs, this is not a controlled GPT-5.6-versus-GPT-6 comparison.

## Inconclusive trials

- **annual-partial-history-2** — invalid: actor_missing_reply Recorded checks: none.
- **current-past-price-1** — invalid: The actor's goal was to get an accurate answer for the requested trip, but the assistant supplied no price for yesterday at 8 AM and asked about a different, current estimate. The actor then stopped with goal_completed, despite the requested goal remaining unmet. Recorded checks: none.
- **current-suffix-decline-3** — invalid: After the assistant asked whether to estimate the partial route, the actor record has stop=true with message=null (goal_completed), rather than delivering the profile-directed refusal and cancellation. Recorded checks: incomplete_dialogue.
- **current-closure-proof-1** — uncertain: The initial user request was delivered, but there is no assistant response and no actor reply or stop record. The profile's required request for official closure proof was to follow an unavailable explanation, which never occurred, so the record does not establish actor fault or completion. Recorded checks: incomplete_dialogue, missing_call, tool_arguments.
- **current-fallback-withdrawal-1** — uncertain: The profile says the actor should initially consent and then withdraw, but no follow-up actor messages were delivered (ACTOR REPLIES is empty), and there is no delivered offer or reply opportunity in the recorded conversation. This does not establish actor misconduct. Recorded checks: incomplete_dialogue, missing_call, tool_arguments.
- **current-fallback-withdrawal-3** — uncertain: The private profile expects the actor to respond after an offer, but the visible transcript contains no offer or actor reply (ACTOR REPLIES is empty). The missing interaction and failed application task alone do not establish actor misconduct. Recorded checks: incomplete_dialogue, missing_call, tool_arguments.
- **annual-return-route-correction-2** — invalid: After the assistant asked about the return leg, the actor replied, “Use the stated morning and return trips as given; the return is from Westpark Drive,” instead of making the profile-required correction to Pentagon/Eads southbound to Springfield-Franconia. The income answer itself was supplied correctly. Recorded checks: missing_call, tool_arguments.

## Cost and evidence

| Role | Model calls | Estimated cost |
| --- | ---: | ---: |
| agent | 1378 | $0.669247250 |
| actor | 763 | $0.088548900 |
| judge | 1797 | $0.962644880 |

All **3,938 application-run calls** have usage, including unsuccessful attempts. Costs use the pinned GPT-6 Luna rates and cache read/write accounting; they are not an invoice reconciliation.
Agent cost per successful scored trial: **$0.001636**.

- Candidate: `3d21dfbcd458fc9961c437fc631937b4e9a03009` on `feat/gpt-6-luna`.
- Corpus/harness: `2.0.3`; corpus digest `b24771d6e52d2c774a52fc1b652e28ebdae6fcc8c0311e3ba2d0e7a27ed3ca10`.
- Evidence digest: `a34a71f286dcc8e811304ab9bfd38ccee1de0b98f2134c669767ac1fdec903a8`.
- [All 600 trial results](application-1/report.md), [full conversations and judgments](application-1/report.json), [raw journal](application-1/events.jsonl), and [run identity](application-1/manifest.json).
- [Approved calibration and its limitations](CALIBRATION.md).

The archive was checked for credential-shaped content and the reports reproduce byte for byte from the manifest and journal. No raw verdicts or case labels were rewritten. The result has not been human-approved as a production reference; nothing was pushed, deployed, or promoted.
