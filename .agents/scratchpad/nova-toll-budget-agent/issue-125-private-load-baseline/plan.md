# Plan

## Test scenarios

1. Fifteen valid responses produce aggregate latency percentiles and prove five
   simultaneous workers; expected output is a passing metadata-only report.
2. Any HTTP or browser-contract failure rejects the run; expected output is a
   nonzero exit and no JSON report.
3. Missing or non-overlapping loader evidence rejects the run.
4. Missing CloudWatch telemetry or a breached launch threshold rejects the run.
5. Unsafe deployment/report metadata is rejected before serialization.

## Implementation

- Add one operator script that reuses the canonical response validator, coordinates
  five workers, invokes ingestion, queries AWS telemetry, and builds the report.
- Add one focused unit-test module with mocked HTTP/AWS boundaries.
- Run the live test only after the local implementation checks pass.
- On success, curate the report and document the observed rollout baseline.
- Run repository validation and Gitleaks, commit, push, open a ready PR, and wait
  for CI.

## Risks

- CloudWatch metrics arrive asynchronously; poll to a bounded deadline.
- A runtime deployment during the test invalidates evidence; pin and recheck its
  live version.
- A real capacity breach blocks publication rather than being normalized away.
