# Canonical deployed toll smoke

Run this gate from an approved Tailscale client after deploying the candidate
and before promoting it. It sends one versioned synthetic I-66 request through
the private browser path, verifies the exact AgentCore tool trajectory and
historical RDS result, and prints only metadata suitable for review.

```bash
report="$(mktemp)"
trap 'rm -f "$report"' EXIT
PREVIEW_URL=https://preview.tollchat.ai/ \
  uv run --frozen python scripts/smoke_agentcore_canonical.py >"$report"
mv "$report" "eval/results/$(date -u +%Y%m%dT%H%M%SZ)-agentcore-canonical-smoke.json"
```

The command exits nonzero for any browser, AgentCore, tool, RDS, trace, or
contract failure. A failure blocks promotion and must not be copied into
`eval/results/`. If AWS, the model provider, or another external dependency has
a confirmed outage, record the affected service and time in the launch review,
then rerun after recovery; an outage does not waive the required passing run.

The script defaults to the `nova-toll` AWS profile, `us-east-1`, the governed
runtime trace log group, and a 600-second trace deadline. Override those values
with `AWS_PROFILE`, `AWS_REGION`, `RUNTIME_LOG_GROUP`, or `TRACE_WAIT_SECONDS`.
Credentials remain in the configured AWS credential chain; never put them in
the command, report, or repository.
