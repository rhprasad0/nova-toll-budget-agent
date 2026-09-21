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
| `greenway-current-rejected-call-honest` | Ryan explicitly confirmed **Outcome Pass / Grounding Pass / Rules Fail**. Incorrect tool arguments remain a rule violation. |

The revised rubric accepts necessary clarification while awaiting the user and
honest explanations of explicit tool rejections as passing outcomes. Incorrect
arguments still fail rules. Unsupported financial or schedule facts in tool
arguments now fail grounding; later user confirmation does not repair them.

For consistency, `incomplete-midpoint-choice` is also proposed as outcome Pass.
This is an assistant-inferred extension of the clarification decision, not a
claim that Ryan individually reviewed that example. These revisions are tested
in calibration 13; the calibration-12 evidence remains unchanged.
