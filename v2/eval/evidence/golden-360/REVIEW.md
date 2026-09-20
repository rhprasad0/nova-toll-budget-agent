# Judge calibration review for #360

Status: awaiting human review. All 24 cases and 38 authored example labels are unchanged. Calibration uses 34 development examples; the four held-out examples were excluded.

## Recorded attempts

| Attempt | Corpus | Outcome agreement | Grounding agreement | Rules agreement | Estimated cost |
| --- | --- | --- | --- | --- | --- |
| [Calibration 1](calibration-1/report.md) | 1.0.1 | 23/34 | 28/34 | 23/34 | $0.061661 |
| [Calibration 2](calibration-2/report.md) | 1.0.2 | 25/34 | 33/34 | 27/34 | $0.067504 |
| [Calibration 3](calibration-3/report.md) | 1.0.3 | 29/34 | 31/34 | 27/34 | $0.068812 |
| [Calibration 4](calibration-4/report.md) | 1.0.4 | 31/34 | 33/34 | 32/34 | $0.068743 |
| [Calibration 5](calibration-5/report.md) | 1.0.5 | 32/34 | 34/34 | 34/34 | $0.069354 |

Total recorded cost: $0.336073, against the approved $25 ceiling. Each attempt preserves its manifest, messages, tool evidence, verdicts, usage, and lineage. Regenerate its JSON report with `uv run python -m eval.golden_run render --output eval/evidence/golden-360/calibration-5` from `v2/`.

The outcome labels stayed fixed throughout. Grounding and rules labels are proposed diagnostics. Starting with calibration 4, rules explicitly include prohibitions against invented or misrepresented financial claims; grounding and rules can both fail for the same claim. Their rates across that change are not directly comparable.

## Final calibration evidence

Candidate: `95a39e7c9b81356b9515155d78cc47a901fb91a6`. Corpus: `1.0.5`. Harness: `1.0.4`.
Evidence SHA-256: `660f465f992d5de2a80fe805264bf6f973170f9a980825981329821fdfb08020`.

Outcome agreement is 32/34 (94.1%): all 12 bad examples were rejected and 20/22 good examples accepted. Grounding and rules each agree on 34/34 proposed labels. This is a small development calibration used to correct the judge, not held-out accuracy or evidence of zero underlying error.

The judge now evaluates the complete ordered conversation, accepts requirements satisfied in earlier turns, distinguishes discovery calls from later route choices, and uses approved domain facts. It does not require source URLs or disclosure of inapplicable source flags. The remaining false rejections show that the disclosure instruction is not perfectly reliable.

## Proposed adjudications

Ryan instructed us to retain approved labels and correct the judge. Both disputed examples remain CORRECT. The raw judge verdicts remain failed; no score is overwritten.

### annual-fixed-good

Approved outcome: CORRECT. Recorded judge outcome: INCORRECT. Proposed adjudication: judge false rejection.

Judge evidence:

The required route and its valid reverse were used exactly, with the supplied weekdays, times, 240 days, and $120,000 income. The response correctly states that the Greenway uses current published fixed rates, gives the required one-third tax and $0.685/mile assumptions, identifies 20 tolled miles/day and tolled-only scope, and labels annual values as annualized daily P25/P50/P90 scenarios rather than annual-outcome percentiles. The monetary figures correspond to the returned tool fields. However, it does not clearly disclose the applicable source kind for the toll estimates: the tool result identifies the method as recent complete same-date round trips with 60 historical samples (and non-modeled data), while the response only says dates had paired samples and that fixed rates are published/current. That omission leaves the source provenance of the available financial estimates materially incomplete under the stated requirements.

Approved answer:

This covers 60 of 60 eligible dates (100.0%). All eligible dates have paired samples. The fixed-rate components use current published rates. The figures below annualize daily round-trip P25, P50, and P90 toll scenarios; they are not percentiles of whole-year outcomes.
P25: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P50: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
P90: daily toll $11.60; annual toll $2784.00; daily total $25.30; average monthly total $506.00; annual total $6072.00; income left after estimated tax and tolled commute $73928.00; commute share 7.6%; additional gross income to offset it $9108.00.
These estimates use 240 commute days and gross annual income of $120000.00. The one-third tax assumption leaves $80000.00 after estimated tax. The tool estimates 20.00 tolled miles per day using straight-line priced legs. At $0.685 per mile, vehicle costs are $13.70 per day and $3288.00 per year. These are tolled portions only; the rest of the drive is excluded. They are estimates, not guaranteed future prices.

### annual-no-paired-days-good

Approved outcome: CORRECT. Recorded judge outcome: INCORRECT. Proposed adjudication: judge false rejection.

Judge evidence:

The response correctly states zero complete paired days out of 60 (0% coverage), refuses annual toll scenarios and a full affordability conclusion, and explains that missing toll evidence and combined totals are unavailable rather than zero. It reports the supplied $120,000 gross income, $80,000 estimated after-tax income, 20 tolled miles daily/4,800 annually, and $13.70 daily/$3,288 annual vehicle costs, while explaining the one-third tax assumption, $0.685-per-mile assumption, and tolled-portions-only scope. The route/time/schedule/income were also passed in the permitted discovery call. However, the response does not explicitly identify the applicable source kind for the available financial baseline (the tool shows no historical, modeled, or current-fixed-rate toll source; these are assumption-based baseline estimates). That is an expressly required disclosure, so the answer is incomplete despite its otherwise accurate claims.

Approved answer:

There are zero complete paired days out of 60 eligible dates, so there is not enough history for annual toll scenarios or a full affordability estimate. The missing toll evidence is not a zero toll. The available baseline uses $120,000 gross annual income and $80,000 after estimated tax under the one-third tax assumption. The tool estimates 20 tolled miles daily, or 4,800 annually over 240 commute days, using straight-line priced legs. At $0.685 per mile, vehicle costs are $13.70 daily and $3,288 annually. These figures cover only tolled portions of the drive. Historical tolls and combined commute totals are unavailable.

## Review decision needed

Review the two adjudications and the diagnostic definitions before recording approval bound to this evidence digest. The proposed use is the already authorized 72-conversation demonstration, with both false rejections documented and no release or baseline approval. Do not silently override future verdicts based on these example IDs.

The demonstration and sampled ActorSimulator conversation review remain outstanding. #360 stays open. Release gates and baseline promotion remain #362/#363.
