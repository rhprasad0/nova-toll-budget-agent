# Golden 3.0.3 repeat calibration review

**120/120 references match all 360 expected judge labels.** This separately authorized repeat used 16 workers on the unchanged 3.0.3 corpus and judge guidance. Open the [static review page](review.html) for every complete transcript, tool result, expected label, and measured explanation. Corpus and calibration approval remain pending.

## Recorded result

- **Zero label disagreements**, zero measurement failures, and no unknown usage across 360 judge calls. All 120 authored actor-validity assessments are valid.
- All 100 proposed passing references pass all three criteria. All 20 negative controls remain rejected overall, with each criterion matching its expected label.
- Case 65's negative control matches the approved Outcome/Rules failures and Grounding pass. Realistic cases 79/80 and their premature-call control also match.
- Cost: **$0.19815320** for this run; **$1.01510851 cumulative of $25**, including all four previous calibrations. There were no per-reference retries or replacement verdicts within this run.
- No application scoring or live actor simulation occurred.

## Comparison with the previous run

The [previous calibration](CALIBRATION-4.md) measured the same corpus and judge configuration with two disagreements. This repeat changes exactly two boolean verdicts: case 26's `ignore-corrected-entry` control now passes Grounding while still failing Outcome and Rules, and case 99's `missing-history-then-explicit-current-check` reference now passes Outcome. Both now match the existing labels without changing their transcripts or grading instructions.

All case definitions, labels, fixtures, prompts, model settings, and evaluator source hashes match the previous run. The source commit and complete-checkout hash differ because the earlier evidence and review documents were committed between runs. The corpus remains **3.0.3**, harness **2.0.10**.

Both runs remain recorded in full. A clean repeat does not erase the earlier errors or establish perfectly reliable judges; it demonstrates variation on identical grading inputs. These are calibration results against authored labels, not application accuracy or production qualification.

## Confusion matrices

| Criterion | Matching passes | Matching failures | Expected failure, measured pass | Expected pass, measured failure |
| --- | ---: | ---: | ---: | ---: |
| outcome | 100 | 20 | 0 | 0 |
| grounding | 107 | 13 | 0 | 0 |
| rules | 100 | 20 | 0 | 0 |

## Validation and provenance

The offline corpus validator passed. The raw report reproduces byte-for-byte from its manifest and events; usage and cost reconcile, all five receipt sets retain their hashes, and all 120 transcripts and expected labels match the preceding run. The HTML page is checked against the exact report, including zero disagreements, offline loading, keyboard disclosure, links, and mobile layout. The existing 92 corpus/development/runner tests passed for this unchanged judge revision; this repeat changes evidence and documentation only.

- Source commit: `1e11b362549f401166e4b7ea1dd8c06131b3f39d`.
- Run ID: `516a6312-f373-49fe-8726-d26e6eda4109`; prior run: `e874bb7f-b846-4947-9116-34a07979625d`.
- Corpus SHA-256: `596b2f1c7abd0c77087c415da7905b673561011f06c612e9d27a739acad6833f`.
- Evidence SHA-256: `6b1931359cacf2d9ffbb1ac9dcf425c44bd3ad56cc6217f70f11d3b547dc4a1b`.
- [Raw report](calibration-5/report.json), [reference checklist](calibration-5/report.md), [events](calibration-5/events.jsonl), [manifest](calibration-5/manifest.json), and [receipt](receipt-5.json).

Earlier [3.0.0](README.md), [3.0.1](CALIBRATION-2.md), [3.0.2](CALIBRATION-3.md), and [first 3.0.3](CALIBRATION-4.md) evidence is preserved. This measurement does not approve the corpus, authorize application scoring, or qualify a release.
