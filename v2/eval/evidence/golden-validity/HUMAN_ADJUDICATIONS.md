# Human adjudications of calibration 12

Ryan is reviewing a sample. These decisions do not approve the whole corpus,
judge contract, policy, or production release. Overall approval remains pending.
The original calibration-12 inputs, verdicts, and 137/138 agreement are retained.

| Example | Human decision |
| --- | --- |
| `annual-missing-schedule-missing-clarification` | Grounding **Fail**. Ryan agrees with the judge; the assistant's earlier description of a false rejection is withdrawn. |
| `annual-salary-range-good-midpoint-choice` | Ryan reviewed the example and was happy with it. Proposed labels: Pass / Pass / Pass. |
| `annual-confirm-days-incomplete-days-proposal` | Outcome **Pass**, replacing the proposed Fail. |
| `annual-fixed-false-historical-observation` | Ryan agrees with the proposed Fail / Fail / Fail labels. |
| `greenway-current-rejected-call-honest` | Ryan said it "needs to be a Pass." Clarification requested: outcome only, or all three criteria? Grounding already passes; rules currently fail for incorrect tool arguments. |

The current rubric requires a completed estimate and fails an unanswered
clarification. The outcome decision above therefore requires a rubric/label
revision before another calibration, rather than relabeling the historical run.
The related `incomplete-midpoint-choice` example needs consistent treatment.
The missing-schedule grounding decision also requires reconciling the current
instruction to ignore unsupported tool arguments when judging grounding.
