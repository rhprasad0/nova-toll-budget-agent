#!/usr/bin/env bash
# Post-apply end-to-end smoke test for the toll poller (spec §Migration step 1,
# implementation-plan WP4 "Done when"). Read-only except for the SNS test
# publish and an optional fetcher invoke. Traces one full tick:
#   EventBridge/fetcher -> 2 objects in raw/ -> LOAD_OK in loader logs ->
#   LoadSuccess metric -> all alarms OK -> SNS test delivered.
#
#   ./smoke.sh          verify the most recent tick
#   ./smoke.sh --fire   invoke toll-fetcher now, then verify
set -euo pipefail

PROFILE=nova-toll
REGION=us-east-1
BUCKET=nova-toll-raw-920534282028
TOPIC_ARN="arn:aws:sns:${REGION}:920534282028:nova-toll-alerts"
AWS=(aws --profile "$PROFILE" --region "$REGION")
DATE_UTC="$(date -u +%Y-%m-%d)"
fail=0
say() { printf '%-22s %s\n' "$1" "$2"; }

# 0. SNS test message — an unconfirmed subscription silently mutes every alarm,
#    so this both tests wiring and forces the confirmation email to matter.
"${AWS[@]}" sns publish --topic-arn "$TOPIC_ARN" \
  --subject "nova-toll smoke test" \
  --message "Smoke test $(date -u +%FT%TZ). If you got this, the alarm path works." >/dev/null
say "sns publish" "sent -> check rhprasad@outlook.com (confirm the subscription if you haven't)"

# 1. optionally fire the fetcher, then give the loader a moment to run
if [[ "${1:-}" == "--fire" ]]; then
  "${AWS[@]}" lambda invoke --function-name toll-fetcher --payload '{}' /dev/null >/dev/null
  say "fetcher invoke" "done — waiting 30s for S3 event -> loader"
  sleep 30
fi

# 2. two raw objects landed today (one per feed)
for feed in i95 i66; do
  n=$("${AWS[@]}" s3api list-objects-v2 --bucket "$BUCKET" \
        --prefix "raw/feed=${feed}/date=${DATE_UTC}/" --query 'length(Contents)' --output text 2>/dev/null)
  [[ "$n" == "None" || -z "$n" ]] && n=0
  if [[ "$n" -ge 1 ]]; then say "s3 raw/$feed" "$n object(s) today"; else say "s3 raw/$feed" "MISSING"; fail=1; fi
done

# 3. LOAD_OK in loader logs within the last 30 min (covers fetch+event+load)
since=$(( ($(date +%s) - 1800) * 1000 ))
# sum length() across pages — filter-log-events auto-paginates and prints one count per page
hits=$("${AWS[@]}" logs filter-log-events --log-group-name /aws/lambda/toll-loader \
        --start-time "$since" --filter-pattern '"LOAD_OK"' --query 'length(events)' --output text 2>/dev/null \
        | awk '{s+=$1} END{print s+0}')
if [[ "$hits" -ge 1 ]]; then say "loader LOAD_OK" "$hits in last 30m"; else say "loader LOAD_OK" "NONE in last 30m"; fail=1; fi

# 4. LoadSuccess metric present per feed
for feed in i95 i66; do
  pts=$("${AWS[@]}" cloudwatch get-metric-statistics --namespace NovaToll --metric-name LoadSuccess \
         --dimensions Name=feed,Value=$feed --start-time "$(date -u -d '1 hour ago' +%FT%TZ)" \
         --end-time "$(date -u +%FT%TZ)" --period 3600 --statistics Sum \
         --query 'length(Datapoints)' --output text 2>/dev/null || echo 0)
  if [[ "$pts" -ge 1 ]]; then say "metric LoadSuccess/$feed" "present"; else say "metric LoadSuccess/$feed" "MISSING"; fail=1; fi
done

# 5. every alarm in OK (not ALARM, not INSUFFICIENT_DATA)
for a in toll-fetcher-errors toll-loader-errors toll-freshness-i95 toll-freshness-i66 \
         toll-loader-onfailure-queue toll-rds-free-storage; do
  st=$("${AWS[@]}" cloudwatch describe-alarms --alarm-names "$a" \
        --query 'MetricAlarms[0].StateValue' --output text 2>/dev/null || echo MISSING)
  if [[ "$st" == "OK" ]]; then say "alarm $a" "OK"; else say "alarm $a" "$st"; fail=1; fi
done

echo
if [[ "$fail" == 0 ]]; then echo "SMOKE OK — full tick traced end to end."; else
  echo "SMOKE INCOMPLETE — items above marked MISSING/not-OK. Freshness/LoadSuccess"
  echo "need a real loader run; re-run with --fire or wait for the next 10-min tick."
fi
exit "$fail"
