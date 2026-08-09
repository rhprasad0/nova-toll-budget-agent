# Deployed AgentCore failure drill

This private drill covers issue #125's single representative failure requirement
with #98's runtime-exception case. It does not complete issue #98's broader
failure matrix.

Deploy the exact reviewed AgentCore and chat-proxy packages, then run from an
approved Tailscale client:

```bash
report="$(mktemp)"
trap 'rm -f "$report"' EXIT
PREVIEW_URL=https://preview.tollchat.ai/ \
  uv run --frozen python scripts/drill_agentcore_failure.py >"$report" &&
  uv run --frozen python -m json.tool "$report" >/dev/null &&
  mv "$report" "eval/results/$(date -u +%Y%m%dT%H%M%SZ)-agentcore-failure-drill.json"
```

The runner sends one request-scoped runtime exception through the private
browser path, requires the exact safe terminal error, correlates its governed
trace, and then runs the canonical $12.15 request in the same browser session.
It also fails if the AgentCore runtime version or proxy package digest changes
during the drill.

Only a successful metadata-only report belongs in `eval/results/`. Update the
evidence README and run `gitleaks git --pre-commit --redact .` before committing
that report. Failed or superseded output stays outside the repository. Never
curate prompts, markers, headers, cookies, raw responses, governed traces, or
request, session, trace, resource, or account identifiers.
