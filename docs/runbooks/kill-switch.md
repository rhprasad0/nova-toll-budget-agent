# TollChat kill switch

When public chat is enabled, its immediate kill switch is the CloudFront web
ACL's default action. In AWS WAF (`us-east-1`, CloudFront scope), edit
`tollchat-public-chat`, change the default action from `Allow` to a custom
`Block` response using the existing `unavailable` body and status `503`, and
save. Terraform ignores drift for this field so a normal apply cannot reopen
chat. Verify the public `/api/config` returns 503 while the static site and
private preview remain available. Restore the default action to `Allow` only
after approval.

For service-wide harm, the proxy Lambda concurrency limit stops both private
and public invocation without touching RDS or the ingestion pipeline.

```bash
AWS_PROFILE=nova-toll aws lambda put-function-concurrency \
  --function-name tollchat-chat-proxy \
  --reserved-concurrent-executions 0
```

Terraform intentionally ignores concurrency drift for this function so a normal apply cannot undo the kill switch during an incident.

Confirm `https://preview.tollchat.ai/api/config` no longer succeeds through
Tailscale and record the incident time.

Restore only after approval:

```bash
AWS_PROFILE=nova-toll aws lambda put-function-concurrency \
  --function-name tollchat-chat-proxy \
  --reserved-concurrent-executions 5
```

Then run the private preview smoke test. Never place credentials or response content in the incident record.
