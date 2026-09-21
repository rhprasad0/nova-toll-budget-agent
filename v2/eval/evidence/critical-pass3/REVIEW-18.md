# Calibration 18 — exact follow-up review

**Approved by Ryan with the documented disagreement; proposed labels and measured verdicts unchanged.** The first approved-contract comparison improved critical pass³ from 9/17 to 12/17, but exposed three further wording false positives. The original runs are retained in [the comparison report](../../results/golden/critical-pass3-comparison-1.md).

## Changes since calibration 16

- Accept an explicit income request using a supplied range and example midpoint.
- Accept “Would you like to use” questions listing range endpoints and their midpoint.
- Accept “not assumed to be $0” as a denial, not a zero-price quote.
- Case prompts, fixtures, actors, judge instructions, models/settings, tool schemas, and numeric policy thresholds are unchanged. The approved 60/60 development actor checks remain applicable; their exact actor fingerprints match.
- Three positive calibration examples were added. Negative tests still reject assumed income, unsupported values, extra monetary claims, and premature calls.

## Evidence

- **158/159 criterion verdicts agree**, across 53 complete examples. All three new examples pass all criteria.
- Calibration-18 evidence: `9812c119f956ddbe3d453ef9b14ebbd2ff0976b957e5623816d2880fc862709c`.
- Corpus 1.0.14 / harness 1.2.4; contract digest: `2b5be310201cf0d8b20e910a9c4b8203837379e0b0bf4b740be3ccfae5907693`.
- Policy 1.0.4, unchanged numeric thresholds; policy digest: `99365d6276aeadee2778837c40b6cf03a9d46334181eaa2012dd21fd5a83d920`.
- Calibration cost $0.06033094; cumulative accounted model spending $3.54462685.
- Interrupted calibration 17 is retained with all usage reconciled; it was not approved.

## Disagreement for human adjudication

`greenway-current-wrong-route`: proposed **Outcome FAIL**, measured **Outcome PASS**. Grounding PASS and Rules FAIL agree with their proposed labels. The synthetic call requests exit 7, while its supplied result describes Route 28. The judge accepts the supported returned price as an outcome while rejecting the incorrect call under Rules. The original proposed outcome label requires the requested route call to be correct.

**Recommendation:** retain the proposed FAIL label and accept this recorded Outcome disagreement as a known diagnostic limitation for the comparison. Overall success still fails Rules and the deterministic route/missing-call/money checks. Do not relabel or discard the measured verdict. No release threshold is relaxed.

Assistant response: The published fixed Greenway toll from Leesburg Bypass to Route 28 is $5.80 for your passenger car with E-ZPass in toll mode, evaluated at 8 AM EDT.

Measured Outcome explanation: The assistant reports the published fixed Greenway rate of $5.80, matching the successful tool result's total and its schedule_derived/published_schedule source. It uses the requested two-axle passenger/E-ZPass/toll profile, gives the correct requested destination route as stated in the returned pricing result, and describes the timestamp as “evaluated,” not as a live observation. The recorded call input used exit 7 rather than the requested exit 28, which would be a separate argument/rules defect, but the successful result itself explicitly supplies the requested Greenway-to-Route 28 route and supports the reported fixed rate. No annual estimate or unsupported claim was substituted.

## New examples

### annual-salary-range-good-income-range-example

Expected and measured: **Outcome PASS / Grounding PASS / Rules PASS**.

Please provide **one gross annual income estimate** between **$110,000 and $130,000**—for example, **$120,000**.

### annual-salary-range-good-income-choice-question

Expected and measured: **Outcome PASS / Grounding PASS / Rules PASS**.

Would you like to use **$110,000, $120,000, or $130,000**?

### annual-no-paired-days-good-zero-not-assumed

Expected and measured: **Outcome PASS / Grounding PASS / Rules PASS**.

There are zero complete paired days out of 60 eligible dates, so there is not enough history for annual toll scenarios or a full affordability estimate. The missing toll evidence is not a zero toll. The available baseline uses $120,000 gross annual income and $80,000 after estimated tax under the one-third tax assumption. The tool estimates 20 tolled miles daily, or 4,800 annually over 240 commute days, using straight-line priced legs. At $0.685 per mile, vehicle costs are $13.70 daily and $3,288 annually. These figures cover only tolled portions of the drive. Historical tolls and combined commute totals are unavailable. Historical toll cost: Unavailable—not assumed to be $0.

## Application candidate ready

Prompt 2.3.2 retains the source fix and clarifies annualized-daily table labels, paired/eligible coverage counts, stale-observation timestamps, hourly-income clarification, and stopping when an annual route has no alternatives. It has not been scored under this contract.

Approval authorizes fresh reference/candidate comparisons under this exact contract, accepting the documented calibration disagreement. It does not authorize merge, deployment, or production qualification.
