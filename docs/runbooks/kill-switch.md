# TollChat kill switch

The immediate kill switch is the proxy Lambda concurrency limit; it stops both private and public invocation without touching RDS or the ingestion pipeline.

```bash
AWS_PROFILE=nova-toll aws lambda put-function-concurrency \
  --function-name tollchat-chat-proxy \
  --reserved-concurrent-executions 0
```

Terraform intentionally ignores concurrency drift for this function so a normal apply cannot undo the kill switch during an incident.

Confirm `https://preview.tollchat.ai/api/config` no longer succeeds through Tailscale and record the incident time. The public static site has no chat origin to disable.

Restore only after approval:

```bash
AWS_PROFILE=nova-toll aws lambda put-function-concurrency \
  --function-name tollchat-chat-proxy \
  --reserved-concurrent-executions 5
```

Then run the private preview smoke test. Never place credentials or response content in the incident record.
