# Issue 125 actionable alarms plan

## Test strategy

- Prove caught proxy request and stream failures emit a sanitized stable marker
  while preserving the browser-safe response contract.
- Assert every requested Terraform alarm's metric, threshold, evaluation,
  missing-data policy, resource dimension, and SNS action.
- Validate the deployed alarm set, CloudWatch-to-SNS action, recipient delivery,
  and existing OpenAI soft-budget alert before curating evidence.

## Implementation

1. Add failing proxy and infrastructure regressions.
2. Add the minimum log marker, metric filter, alarms, descriptions, runbook, and
   smoke coverage needed to satisfy those tests.
3. Run focused and full CI-equivalent checks.
4. Address adversarial and security review findings.
5. Apply only the intended Terraform plan, verify delivery, curate evidence,
   run Gitleaks, and commit locally.
