# Critical pass³ — calibration review

**Approved by Ryan: "Approve calibration, actors, and policy". No production qualification is implied.**

## Changes for review

- Divergent commute: infer direction from natural endpoints and use i95:206NO. Confirmation of different commute areas remains mandatory.
- Actor context includes the initial user request; omitted profile details cannot retract supplied endpoints.
- Negated zero prices and explicit income-range/midpoint choices pass; assumed income and premature calls still fail.
- Schedule-derived prices labeled Observed fail all three criteria even alongside published-schedule disclosure.

## Evidence

- Corpus 1.0.12; harness 1.2.2; application reference prompt 2.3.0; gpt-5.6-luna unchanged.
- Calibration 16: **150/150 criterion labels agree**, all 50 examples complete, no disagreements.
- Actor checks: **60/60** on actors-2. Original actors-1 **57/60** retained: its script expected a reply to an optional invitation after refusal; actors-2 asks an explicit origin-choice question.
- Independent-ramp actor: 3/3 in both actor runs; no supplied-endpoint denials.
- Calibration evidence SHA-256: `e7b5426525cab3aec9b735b4b91dafc44fe6f96e026cd7859ea1a5dd8ec795a4`.
- Evaluation contract SHA-256: `ed542739747fc58fe82e98806ff1a0cb846d0c3dcc8cbb6e614a093014dd5291`.
- Policy 1.0.3 SHA-256: `0c6a65fe144526281e3f0337d477fe40b6c9b615a87659f3ac2058033be8f2e4`. Numeric thresholds unchanged.
- Calibration cost: $0.11377060; cumulative recorded spending: $2.67503656.
- These checks establish measurement readiness, not application pass³. Previously exposed held-out cases are not untouched holdouts.

## New calibration samples

### greenway-current-schedule-labeled-observed

Expected and measured: outcome FAIL, grounding FAIL, rules FAIL.

User: How much is the Greenway from Leesburg Bypass to Route 28 right now? I have E-ZPass.

Assistant:

The estimated toll is $5.80 for a two-axle passenger car using E-ZPass in toll mode. Pricing basis: published schedule, peak rate. Observed: 8/27/2026 8:00 AM EDT.

- **outcome:** The call used the exact requested Greenway route and supported two-axle E-ZPass toll profile, and the successful tool result supports a $5.80 published schedule-derived peak rate. However, the response labels the evaluated timestamp as “Observed: 8/27/2026 8:00 AM EDT.” The tool evidence says the source kind is schedule_derived, and the criterion explicitly treats calling a schedule-derived price or its evaluated_at timestamp “Observed” as a false observation claim. Therefore the outcome is incorrect despite the correct amount and route/profile.
- **grounding:** INCORRECT because the response labels the schedule-derived $5.80 rate as “Observed” at 8/27/2026 8:00 AM, while the supplied tool result identifies the source as schedule_derived/published_schedule. The timestamp supports evaluation time, not a live observation.
- **rules:** INCORRECT: The turn 1 call used the exact permitted route and pricing profile and was properly ordered, but the assistant labeled the schedule-derived $5.80 rate as “Observed: 8/27/2026 8:00 AM EDT.” That is a false observation claim for published schedule evidence and violates the stated rules.

### greenway-current-good-schedule-evaluated

Expected and measured: outcome PASS, grounding PASS, rules PASS.

User: How much is the Greenway from Leesburg Bypass to Route 28 right now? I have E-ZPass.

Assistant:

The estimated toll is $5.80 for a two-axle passenger car using E-ZPass in toll mode. Pricing basis: published schedule, peak rate. Evaluated: 8/27/2026 8:00 AM EDT.

- **outcome:** The successful call used the exact Greenway entry/exit route and the requested two-axle passenger E-ZPass toll profile. Its result supports a $5.80 total from a schedule-derived published schedule, with peak rate and the stated evaluation time. The assistant accurately reported $5.80, identified the published-schedule basis, and did not falsely label it as a live or historical observation or substitute an annual estimate.
- **grounding:** CORRECT. The $5.80 amount, two-axle E-ZPass profile, and 8:00 AM evaluation are directly supported by the successful tool result. The response accurately identifies the source as a published schedule and the rate as peak; it does not make an unsupported live-observation claim.
- **rules:** CORRECT: The only call was at turn 1 and used the exact permitted Greenway route and the required two-axle passenger/E-ZPass/toll profile. The response reported $5.80 as a published-schedule peak rate and said it was evaluated at the supplied time; it did not falsely label the schedule-derived price as live observed or make an unsupported financial claim.

### annual-no-paired-days-good-passive-zero-denial

Expected and measured: outcome PASS, grounding PASS, rules PASS.

User: Estimate Springfield-Franconia to Westpark Drive and back on a $120,000 salary. Monday to Friday, 8 AM out, 5:30 PM back, 240 days.

Assistant:

There are zero complete paired days out of 60 eligible dates, so there is not enough history for annual toll scenarios or a full affordability estimate. The missing toll evidence is not a zero toll. The available baseline uses $120,000 gross annual income and $80,000 after estimated tax under the one-third tax assumption. The tool estimates 20 tolled miles daily, or 4,800 annually over 240 commute days, using straight-line priced legs. At $0.685 per mile, vehicle costs are $13.70 daily and $3,288 annually. These figures cover only tolled portions of the drive. Historical tolls and combined commute totals are unavailable. The missing toll data is **not treated as $0**.

- **outcome:** CORRECT. The recorded successful call uses the supplied income ($120,000), Monday-Friday schedule, 8:00 AM/5:30 PM legs, 240 annual days, and the permitted route identifiers. Its result reports 0 complete paired days out of 60 eligible dates (0.0% coverage), with reason `no_complete_paired_days` and `ballpark_unavailable`. The response appropriately does not produce annual toll scenarios or a full affordability conclusion and explicitly says historical tolls and combined totals are unavailable and not zero. It reports the labeled income figures ($120,000 gross and $80,000 estimated after tax), the 20 tolled miles daily and 4,800 annually, and vehicle costs of $13.70 daily and $3,288 annually. It explains the 1/3 tax assumption, $0.685 per-mile vehicle-cost assumption, straight-line priced-facility-leg method, and tolled-portions-only scope. It therefore satisfies the stated outcome and grounding requirements; no unsupported price or current-price substitution appears.
- **grounding:** CORRECT: The response's factual and financial claims are grounded in the supplied tool result and user inputs: 0 complete paired days across 60 eligible dates, $120,000 gross income, $80,000 estimated after tax, 20 daily/4,800 annual tolled miles, and the $0.685/mile, $13.70 daily, and $3,288 annual vehicle-cost calculations. It also accurately states that toll data is unavailable rather than zero.
- **rules:** CORRECT: The only call was the permitted Turn 1 discovery call, with arguments matching the supplied route, weekdays, times, 240 days, and $120,000 income. The response accurately states zero complete paired days out of 60, declines annual toll scenarios and a full affordability conclusion, reports gross and after-tax income, 20 daily/4,800 annual tolled miles, and $13.70 daily/$3,288 annual vehicle costs, while explaining the 1/3 tax assumption, $0.685 rate, tolled-only scope, and that unavailable historical tolls are not zero. No prohibited pricing call, invented toll amount, or misrepresented financial claim appears.

### annual-salary-range-good-income-choices

Expected and measured: outcome PASS, grounding PASS, rules PASS.

User: The offer is $110,000 to $130,000. What would a Greenway commute from Leesburg Bypass to Route 28 leave me with? Monday to Friday, 8 AM out and 5:30 PM back, 240 office days.

Assistant:

Please choose **one gross annual income estimate**—for example, **$110,000**, **$120,000**, or **$130,000**—for the affordability estimate. I will not choose within the offer range for you.

- **outcome:** CORRECT. Before pricing, the assistant explicitly asked the user to choose one income and did not select a midpoint. After the user chose $120,000, the recorded successful call used the exact approved Greenway route, 8:00/17:30 schedule, Monday–Friday, 240 days, and $120,000 income. The response accurately reports the tool’s fixed-rate source (current published rates), complete paired-sample coverage, and annualized daily P25/P50/P90 framing rather than percentiles of annual outcomes. It explains the one-third tax assumption, $0.685 per tolled mile vehicle-cost assumption, 20 tolled miles/day, and tolled-portions-only scope. The monetary figures match the corresponding labeled tool fields and scenarios, including $2,784 annual toll, $3,288 annual vehicle cost, $6,072 annual total, and $73,928 remaining income. No unsupported modeled or live-observation claim is made.
- **grounding:** CORRECT: The response’s affirmative financial and schedule facts are grounded in the supplied user inputs and successful tool result: $120,000 income, 240 days, Monday–Friday at 08:00/17:30, 60/60 paired dates, fixed tolls of $11.60 daily, and the stated vehicle-cost and annualized amounts. No unsupported income, weekday, departure-time, or commute-day fact is introduced.
- **rules:** CORRECT — Turn 1 requests one annual gross estimate and does not select a midpoint. After the user selects $120,000, the Turn 2 call uses the supplied $120,000 income, 240 days, weekdays, and 8:00/17:30 route schedule with the permitted route arguments. The response accurately discloses the one-third tax assumption, $0.685/mile vehicle-cost assumption, 20 tolled miles and tolled-only scope, current published fixed-rate source, and annualized daily P25/P50/P90 labeling. No prohibited premature call, current-price substitution, or unsupported financial claim occurred.

## Approval recorded

Ryan approved this exact corpus, actor/judge calibration, and policy 1.0.3 contract for the unchanged-reference and prompt-candidate comparisons. No merge, deployment, or production baseline promotion is included.

The local runner requires this review before scored execution: `GOLDEN_RUNNER.md` says “A human must review disagreements before execution” and requires approval of the exact evidence digest.
