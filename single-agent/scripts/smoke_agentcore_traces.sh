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
MARKER="verify-$(cat /proc/sys/kernel/random/uuid)"
START_TIME="$(date +%s)"
trap 'rm -rf "$WORKDIR"' EXIT

query_trace() {
  local group="$1" query="$2" output="$3" query_id status
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
}

curl --fail --silent --show-error --cookie-jar "$WORKDIR/cookies" \
  --header 'content-type: application/json' --header "origin: ${PREVIEW_URL%/}" \
  --header 'sec-fetch-site: same-origin' \
  --data "{\"message\":\"Price a trip from Dumfries to Westpark using the toll route tool. $MARKER\"}" \
  "$PREVIEW_URL/api/chat" >"$WORKDIR/response.json"
grep -q '"answer"' "$WORKDIR/response.json"

deadline=$((START_TIME + WAIT_SECONDS))
while :; do
  query_trace "$RUNTIME_GROUP" \
    "fields @message | filter @message like /tollchat.runtime_trace/ | filter @message like /$MARKER/ | limit 2" \
    "$WORKDIR/marker.json"
  if SESSION_ID="$(uv run python -c 'import json,sys; rows=json.load(open(sys.argv[1]))["results"]; ids={json.loads(next(x["value"] for x in row if x["field"]=="@message"))["session_id"] for row in rows}; assert len(ids)==1; print(ids.pop())' "$WORKDIR/marker.json" 2>/dev/null)"; then
    break
  fi
  (( $(date +%s) >= deadline )) && { echo "session marker was not ingested" >&2; exit 1; }
  sleep 5
done

while :; do
  query_trace "$RUNTIME_GROUP" \
    "fields @timestamp, @message | filter @message like /tollchat.runtime_trace/ | filter @message like /$SESSION_ID/ | sort @timestamp asc" \
    "$WORKDIR/runtime.json"
  query_trace "$SPANS_GROUP" \
    "fields @message | filter attributes.session.id = \"$SESSION_ID\" | sort @timestamp asc" \
    "$WORKDIR/spans.json"
  uv run python -c 'import json,sys; json.dump({"runtime": json.load(open(sys.argv[1])), "spans": json.load(open(sys.argv[2]))}, open(sys.argv[3], "w"))' \
    "$WORKDIR/runtime.json" "$WORKDIR/spans.json" "$WORKDIR/trace.json"
  if uv run python scripts/verify_agentcore_trace.py "$WORKDIR/trace.json" \
    > /dev/null 2>"$WORKDIR/verify-error"; then
    break
  fi
  if (( $(date +%s) >= deadline )); then
    sed -n '1p' "$WORKDIR/verify-error" >&2
    exit 1
  fi
  sleep 5
done

runtime_count="$(uv run python -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["results"]))' "$WORKDIR/runtime.json")"
span_count="$(uv run python -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["results"]))' "$WORKDIR/spans.json")"
printf '{"status":"ok","runtime_records":%s,"native_spans":%s}\n' \
  "$runtime_count" "$span_count"
