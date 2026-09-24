# AI evaluation engineering: TollChat

TollChat is a reference implementation for building and deploying tool-using AI
agents. This work improved the reliability of its evaluation system so that
simulated-user and grading errors could be distinguished from application defects.

## Problem and implementation

A failed evaluation revealed three measurement problems: simulated users stopped
before delivering required clarifications, rejected tool calls were missing from
the grading evidence, and a judge sometimes evaluated its own explanation instead
of the agent conversation.

The implementation enforced structured evaluator output, made invalid simulated
conversations inconclusive, and included tool rejections in the judge's evidence.
It separated grading into task outcome, factual grounding, and rule compliance,
with human review resolving ambiguous examples. The application model and prompt
and the numerical release thresholds were unchanged.

## Measured results

- Expanded judge calibration from 34 to **46 development examples**, including
  clarification, consent, unsupported claims, and honest tool-error handling.
- The final judge matched **138 of 138 criterion labels**: 46 each for outcome,
  grounding, and rules. This is development-set agreement, not held-out accuracy
  or an application success rate.
- The final simulated-user diagnostic passed **59 of 60 checks** and delivered
  every required clarification. One redundant reply after a completed answer
  remains a known limitation.
- Six actor diagnostics and seven calibration runs cost **$0.79 total**.
  Regression tests cover evaluation integrity and rejection of unapproved or
  changed evaluation contracts.

Ryan reviewed sample cases and explicitly approved the final evaluation contract
and actor limitation on September 21, 2026. A qualified production baseline is
still outstanding; this work does not claim production readiness. Four cases
were excluded from calibration, but prior review exposure means they are not
untouched holdouts.

## Engineering skills demonstrated

LLM evaluation design, simulated-user testing, judge calibration, tool-call
validation, failure diagnosis, human adjudication, cost measurement, Python
regression testing, and CI/CD gates that bind approval to the evaluated contract.

## Supporting records

[Approved calibration report](evidence/golden-360/calibration-15/report.json) and
[human decisions](evidence/golden-validity/HUMAN_ADJUDICATIONS.md) support these
claims. The repository retains the active gate evidence and required regression
fixtures. Superseded experiment logs are recoverable from Git commit `0336ddf`;
the [accounting receipts](evidence/golden-validity/README.md) identify archived
live-run evidence. The [release guide](GOLDEN_RELEASE.md) describes the remaining
production qualification process.
