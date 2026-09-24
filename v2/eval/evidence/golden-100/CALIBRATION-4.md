# Golden 3.0.3 calibration review

**Complete measurement; corpus and calibration approval pending.** All five previously disputed references now match their labels. Two disagreements remain across two other references. Open the [static review page](review.html) for all 120 complete transcripts, tool evidence, expected labels, and judge explanations.

## Approved adjudication and changes

Ryan approved failing **Outcome and Rules** for case 65's `no-day-adjustment-choice` negative control. Asking whether to use 156 days omitted the required invitation to adjust the proposal. Correctly using the user's later 134-day correction does not cure that missing workflow step. Grounding still passes. Only this reference's expected Outcome label and rationale changed; all 100 case definitions, 120 transcripts, and 107 fixtures remain unchanged from 3.0.2.

The shared judge guidance now explicitly accepts recognizable road abbreviations such as DTR, requires disclosure of only sources actually used, and treats incorrect financial labels as Rules violations even after a correctly labeled table. It distinguishes the required annual-day adjustment invitation from final-answer disclosure. These are evaluator changes; the application model and prompt remain unchanged. Five-turn actors and the realistic cases 79/80 remain as reviewed.

## Recorded result

- **120/120 references complete**, 360 judge calls, no measurement failures or unknown usage. All authored actor-validity assessments are valid.
- **2 disagreements across 2 references**: one proposed passing reference and one negative control. Agreement is **358/360 (99.4%)** against authored labels, not application accuracy or independent truth.
- All five references disputed in calibration 3 now match, including case 65's adjudicated labels. Cases 79/80 and their premature-call control also match.
- **None of the 20 negative controls passed all three judges.** Rules matches all 120 labels.
- Cost: **$0.20658857** for this run; **$0.81695531 cumulative of $25**, including all three prior calibrations. The run used **16 workers**, with no retries or replacement verdicts.
- No application scoring or live actor simulation occurred. Earlier [3.0.0](README.md), [3.0.1](CALIBRATION-2.md), and [3.0.2](CALIBRATION-3.md) evidence remains intact. A single calibration does not establish general judge reliability; both remaining references matched in the prior run.

## Confusion matrices

| Criterion | Matching passes | Matching failures | Expected failure, measured pass | Expected pass, measured failure |
| --- | ---: | ---: | ---: | ---: |
| outcome | 99 | 20 | 0 | 1 |
| grounding | 106 | 13 | 0 | 1 |
| rules | 100 | 20 | 0 | 0 |

## Remaining disagreements (agent analysis)

Neither requires a new product-policy decision in the agent's assessment. The existing criteria cover both; the measured verdicts remain unchanged for review.

### dev3-correct-dulles-road-entry-ignore-corrected-entry

Case 26's negative control deliberately ignores a corrected origin. Outcome and Rules correctly fail. Grounding also fails because the judge treats keeping the original route as falsely claiming to have priced the corrected route. The assistant explicitly says it will keep the original route and estimate; the original result supports that estimate, and no claim is made that it covers Wiehle Avenue. The rubric separates pure route-selection violations from unsupported factual claims. Retain the expected Grounding pass; this is a judge criterion-boundary error, and the control is still rejected overall.

**grounding: expected True; measured False.**

> INCORRECT: After the user corrected the origin to Wiehle Avenue, the assistant said it would keep the original route and estimate. That is an unsupported route claim because the only priced result was for Fairfax County Parkway to Spring Hill Road, not Wiehle Avenue to Spring Hill Road.

### dev3-missing-history-then-explicit-current-check-good

Case 99 correctly explains missing annual history, supplies the available income/distance/vehicle baseline, then answers a separately requested current-toll question. The Outcome judge demands annual scenarios and affordability totals that the no-history result cannot support. The shared criterion explicitly requires only the available baseline and missing-history disclosure in this situation. Retain the expected Outcome pass; the response honors the evidence limit and the user's later workflow switch. Grounding and Rules pass.

**outcome: expected True; measured False.**

> The declared objective is to answer the annual affordability request, but the assistant reports that historical tolls and combined totals are unavailable and supplies no annualized daily P25/P50/P90 scenarios, daily toll/combined costs, monthly and annual combined costs, remaining income, or additional gross salary needed to offset costs. The later $9.85 current toll is a separate quote and does not complete the annual estimate.

## Validation and provenance

**92 relevant corpus/development/runner tests passed**, including reference replay and independent financial reconciliation. Repository static checks passed. The raw report reproduces byte-for-byte from its manifest and events. All usage is known, the corpus matches its frozen digest, and all four receipt sets retain their file hashes. The HTML page embeds the exact transcripts and measured verdicts and is checked for offline loading, keyboard access, valid links, and mobile layout.

- Source commit: `5b93f0c6d45355039928b45546a816c92ff41b1a`; corpus `3.0.3`; harness `2.0.10`.
- Run ID: `e874bb7f-b846-4947-9116-34a07979625d`; prior run: `3d9aa3b8-953d-4244-a540-9d9e21a8b8db`.
- Corpus SHA-256: `596b2f1c7abd0c77087c415da7905b673561011f06c612e9d27a739acad6833f`.
- Evidence SHA-256: `c73dde3311a04e73dba293764fb9ffd69f730571d7e4c55d302df2b45d2a5aa6`.
- [Raw report](calibration-4/report.json), [reference checklist](calibration-4/report.md), [events](calibration-4/events.jsonl), [manifest](calibration-4/manifest.json), and [receipt](receipt-4.json).

Ryan's case-65 adjudication is recorded; it is not blanket approval of the corpus or this new calibration. The development corpus cannot qualify production.
