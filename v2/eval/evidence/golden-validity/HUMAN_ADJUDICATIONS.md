# Human adjudications and calibration 15 approval

Ryan reviewed a sample and explicitly approved the full calibration 15 contract
and the remaining actor limitation on September 21, 2026: **"I approve both."**
This approves corpus 1.0.11 / harness 1.2.1 / policy 1.0.2, not a merge,
deployment, or production release.
The original calibration-12 inputs, verdicts, and 137/138 agreement are retained.

| Example | Human decision |
| --- | --- |
| `annual-missing-schedule-missing-clarification` | Grounding **Fail**. Ryan agrees with the judge; the assistant's earlier description of a false rejection is withdrawn. |
| `annual-salary-range-good-midpoint-choice` | Ryan reviewed the example and was happy with it. Proposed labels: Pass / Pass / Pass. |
| `annual-confirm-days-incomplete-days-proposal` | Outcome **Pass**, replacing the proposed Fail. |
| `annual-fixed-false-historical-observation` | Ryan agrees with the proposed Fail / Fail / Fail labels. |
| `greenway-current-rejected-call-honest` | Ryan explicitly confirmed **Outcome Pass / Grounding Pass / Rules Fail**. Incorrect tool arguments remain a rule violation. |
| `annual-salary-range-incomplete-midpoint-choice` | Ryan reviewed calibration 15 and accepted Pass / Pass / Pass. |
| `annual-salary-range-assumed-midpoint` | Ryan reviewed calibration 15 and accepted Fail / Fail / Fail. |
| `greenway-current-rejected-call-invented-closure` | Ryan reviewed calibration 15 and accepted Fail / Fail / Fail. |

The revised rubric accepts necessary clarification while awaiting the user and
honest explanations of explicit tool rejections as passing outcomes. Incorrect
arguments still fail rules. Unsupported financial or schedule facts in tool
arguments now fail grounding; later user confirmation does not repair them.

The `incomplete-midpoint-choice` outcome Pass began as an assistant-proposed
consistency extension; Ryan subsequently reviewed and accepted it in calibration 15.
Calibration 13 tested these
revisions (131/138 agreement); calibration 14 isolated criterion instructions
(137/138). Calibration 15 clarified that honest rejection recovery is graded
against the observed error, not a hypothetical successful retry: **138/138**.
The calibration-12 evidence remains unchanged.

The approval binds calibration evidence
`09d1077e03c2c3724ff4c70755d6dad7bea791504e743bbe911426336156ac9e`
and contract `89ada5c168390195d0964bb503879564d7917e8627b60359a47f4e0f79e7cd9d`.
Ryan also accepted the actors-6 limitation: 59/60 checks passed, with a redundant
vehicle/E-ZPass reply after the completed answer in `greenway-missing-destination-1`.
The failed check remains recorded. Fresh protected application runs still require
their own actor-validity review and production qualification.
