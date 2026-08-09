# TollChat rollback

Rollback restores an explicitly approved package set from a prior successful
Terraform workflow run. Do not use `reviewed/latest` or rebuild a Git commit:
the workflow's reviewed release ID and its retained SHA-256 manifest are the
rollback identity.

## Select and disable

Copy `Reviewed release: <git-sha>/<manifest-sha256>` from the job summary of
the prior successful Terraform workflow run chosen for rollback. Confirm its
package uploads in the validated CloudTrail audit record, then export only the
identifier:

```bash
export REVIEWED_RELEASE=<git-sha>/<manifest-sha256>
```

If public chat is enabled, engage the public switch and apply
`enable_public_chat=false` as described in the
[kill-switch runbook](kill-switch.md). Then capture the approved proxy
concurrency and set it to zero:

```bash
set -euo pipefail
export AWS_PROFILE=nova-toll
export AWS_REGION=us-east-1
baseline_concurrency="$(aws lambda get-function-concurrency \
  --function-name tollchat-chat-proxy \
  --query ReservedConcurrentExecutions --output text)"
test "$baseline_concurrency" = 5
rollback_validated=false
artifact_dir=""
fail_closed() {
  if [[ "$rollback_validated" != true ]]; then
    aws lambda put-function-concurrency \
      --function-name tollchat-chat-proxy \
      --reserved-concurrent-executions 0 >/dev/null || \
      echo "EMERGENCY: verify proxy concurrency is zero" >&2
  fi
  if [[ -n "$artifact_dir" && -d "$artifact_dir" ]]; then
    rm -r -- "$artifact_dir"
  fi
}
trap fail_closed EXIT
aws lambda put-function-concurrency --function-name tollchat-chat-proxy \
  --reserved-concurrent-executions 0 >/dev/null
```

Keep a second approved client ready with the emergency restore command from
the kill-switch runbook.

## Restore the retained package set

Download into a temporary directory, bind the manifest to the approved release
ID, and verify every package before Terraform reads it:

```bash
reviewed_release="${REVIEWED_RELEASE:?Set from a prior successful Terraform workflow run}"
[[ "$reviewed_release" =~ ^[0-9a-f]{40}/[0-9a-f]{64}$ ]] || {
  echo "Invalid reviewed release identifier" >&2
  exit 1
}
release_digest="${reviewed_release#*/}"
artifact_dir="$(mktemp -d)"
artifact_bucket="nova-toll-agentcore-920534282028"
aws s3 cp "s3://$artifact_bucket/reviewed/$reviewed_release/" \
  "$artifact_dir/" --recursive --only-show-errors
test "$(cd "$artifact_dir" && sha256sum SHA256SUMS | cut -d ' ' -f1)" = \
  "$release_digest"
(cd "$artifact_dir" && sha256sum --check SHA256SUMS)
```

Any missing object or digest mismatch aborts the rollback and the EXIT trap
keeps proxy concurrency at zero. Never substitute a rebuilt package. Reviewed
object versions are excluded from expiration so the audit trail remains
recoverable even if a current version is accidentally replaced.

Fetch the Cloudflare token from SSM as described in `SECURITY.md`, then plan
with the verified packages and public-site files. Keep the public edge off:

```bash
terraform -chdir=infra init
terraform -chdir=infra plan -out=rollback.tfplan \
  -var "fetcher_package_path=$artifact_dir/fetcher.zip" \
  -var "loader_package_path=$artifact_dir/loader.zip" \
  -var "agentcore_package_path=$artifact_dir/agentcore.zip" \
  -var "chat_proxy_package_path=$artifact_dir/chat-proxy.zip" \
  -var "site_index_path=$artifact_dir/preview.html" \
  -var "site_script_path=$artifact_dir/preview.mjs" \
  -var "site_privacy_path=$artifact_dir/privacy.md" \
  -var "site_terms_path=$artifact_dir/terms.md" \
  -var enable_public_chat=false
terraform -chdir=infra show rollback.tfplan
# After owner approval:
terraform -chdir=infra apply rollback.tfplan
```

Verify the plan changes only the approved packages, public-site files, and
their expected runtime or endpoint dependencies. It must not create a public
Lambda URL, public origin access control, `/api/*` behavior, or WAF. Do not
roll back the database, raw feed objects, or Terraform state.

## Validate with bounded private concurrency

Keep public traffic disabled, permit one private proxy invocation at a time,
and run the [canonical deployed toll smoke](canonical-smoke.md):

```bash
aws lambda put-function-concurrency --function-name tollchat-chat-proxy \
  --reserved-concurrent-executions 1 >/dev/null
test "$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' https://preview.tollchat.ai/api/config)" = 200
PREVIEW_URL=https://preview.tollchat.ai/ \
  uv run --frozen python scripts/smoke_agentcore_canonical.py >/dev/null
```

If the smoke fails, `set -e` exits and `fail_closed` returns concurrency to
zero. Investigate and choose another approved release; do not retry traffic.

## Restore approved proxy concurrency

Only after the private smoke succeeds, restore and verify the captured value:

```bash
aws lambda put-function-concurrency --function-name tollchat-chat-proxy \
  --reserved-concurrent-executions "$baseline_concurrency" >/dev/null
test "$(aws lambda get-function-concurrency \
  --function-name tollchat-chat-proxy \
  --query ReservedConcurrentExecutions --output text)" = "$baseline_concurrency"
rollback_validated=true
printf 'Restored reviewed release %s\n' "$reviewed_release"
```

The EXIT trap now removes only the temporary package directory. Do not restore
public traffic until the private smoke and no-leak checks pass.
