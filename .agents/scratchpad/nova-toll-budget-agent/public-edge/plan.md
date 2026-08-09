# Public edge plan

## Test strategy

- Proxy accepts both private API Gateway v1 and Function URL v2 event shapes.
- Invocation hooks allow six model calls and five tools, cancel the next call,
  reset per request, and force the runtime's existing safe error on exhaustion.
- Terraform tests require the default-off flag, conditional Lambda URL/OAC and
  `/api/*` behavior, direct-origin-denial permissions, exact route allowlist,
  WAF limits/responses/metrics, public-only kill switch, and single-attempt
  deadlines.
- Terraform validation proves provider schema compatibility.

## Implementation

1. Add failing regression tests and record the expected failures.
2. Add the small event normalizer and invocation-limit hook.
3. Add conditional public-edge and WAF resources around the existing function
   and distribution.
4. Reconcile the launch-plan spend wording and existing kill-switch statement.
5. Run focused tests, formatting, type checks, full non-live tests, Terraform
   validation, pre-commit checks, and gitleaks.
6. Commit locally; do not push or open a PR.

## Adversarial follow-up

- Public POST requests hash the exact serialized body for Lambda OAC signing.
- Public chat consumes both tool-plus-answer and answer-only NDJSON streams.
- Browser regression coverage verifies both client contracts.

## PR feedback

- Reproduce parallel tool callbacks inheriting copied context-variable values.
- Keep counters in shared Strands invocation state while retaining request-local
  completion status.
- Run focused and full validation before pushing the fix.
