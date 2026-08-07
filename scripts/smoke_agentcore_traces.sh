#!/usr/bin/env bash
# Invoke the Tailscale-only preview, then prove its correlated trace is complete.
set -euo pipefail

PROFILE="${AWS_PROFILE:-nova-toll}"
REGION="${AWS_REGION:-us-east-1}"
PREVIEW_URL="${PREVIEW_URL:?set PREVIEW_URL to the Tailscale-reachable preview URL}"
RUNTIME_GROUP="${RUNTIME_LOG_GROUP:-/aws/nova-toll/agentcore/traces}"
SPANS_GROUP="${SPANS_LOG_GROUP:-aws/spans}"
WAIT_SECONDS="${TRACE_WAIT_SECONDS:-600}"
AWS=(aws --profile "$PROFILE" --region "$REGION")
WORKDIR="$(mktemp -d)"
SESSION_ID="$(cat /proc/sys/kernel/random/uuid)"
START_TIME="$(date +%s)"
trap 'rm -rf "$WORKDIR"' EXIT

query_until_present() {
  local group="$1" query="$2" output="$3" attempts=$((WAIT_SECONDS / 5)) query_id status
  for ((attempt = 0; attempt <= attempts; attempt++)); do
    query_id="$("${AWS[@]}" logs start-query --log-group-name "$group" \
      --start-time "$START_TIME" --end-time "$(date +%s)" --query-string "$query" \
      --query queryId --output text)"
    while :; do
      status="$("${AWS[@]}" logs get-query-results --query-id "$query_id" --query status --output text)"
      [[ "$status" == "Complete" ]] && break
      [[ "$status" == "Failed" || "$status" == "Cancelled" || "$status" == "Timeout" ]] && {
        echo "trace query failed: $status" >&2
        return 1
      }
      sleep 2
    done
    "${AWS[@]}" logs get-query-results --query-id "$query_id" --output json >"$output"
    [[ "$(uv run python -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["results"]))' "$output")" != 0 ]] && return
    sleep 5
  done
  echo "no trace records for session $SESSION_ID in $group before timeout" >&2
  return 1
}

curl --fail --silent --show-error --header 'content-type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\",\"message\":\"Price a trip from Dumfries to Westpark using the toll route tool.\"}" \
  "$PREVIEW_URL/api/chat" >"$WORKDIR/response.json"
grep -q '"answer"' "$WORKDIR/response.json"

query_until_present "$RUNTIME_GROUP" \
  "fields @timestamp, @message | filter @message like /tollchat.runtime_trace/ | filter @message like /$SESSION_ID/ | sort @timestamp asc" \
  "$WORKDIR/runtime.json"
query_until_present "$SPANS_GROUP" \
  "fields @message | filter attributes.session.id = \"$SESSION_ID\" | sort @timestamp asc" \
  "$WORKDIR/spans.json"

uv run python -c 'import json,sys; json.dump({"runtime": json.load(open(sys.argv[1])), "spans": json.load(open(sys.argv[2]))}, open(sys.argv[3], "w"))' \
  "$WORKDIR/runtime.json" "$WORKDIR/spans.json" "$WORKDIR/trace.json"
uv run python scripts/verify_agentcore_trace.py "$WORKDIR/trace.json" >/dev/null

runtime_count="$(uv run python -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["results"]))' "$WORKDIR/runtime.json")"
span_count="$(uv run python -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["results"]))' "$WORKDIR/spans.json")"
printf '{"status":"ok","session_id":"%s","runtime_records":%s,"native_spans":%s}\n' \
  "$SESSION_ID" "$runtime_count" "$span_count"
