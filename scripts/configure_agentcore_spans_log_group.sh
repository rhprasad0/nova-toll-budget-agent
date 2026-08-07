#!/usr/bin/env bash
# Configure the X-Ray-created reserved spans group after Transaction Search is active.
set -euo pipefail

group_name="${1:?log group name required}"
kms_key_arn="${2:?KMS key ARN required}"
retention_days="${3:?retention days required}"

for ((attempt = 1; attempt <= 120; attempt++)); do
  if aws logs put-retention-policy --log-group-name "$group_name" \
    --retention-in-days "$retention_days" >/dev/null 2>&1 && \
    aws logs associate-kms-key --log-group-name "$group_name" \
      --kms-key-id "$kms_key_arn" >/dev/null 2>&1; then
    exit 0
  fi
  sleep 5
done

echo "aws/spans was not ready for retention and KMS configuration" >&2
exit 1
