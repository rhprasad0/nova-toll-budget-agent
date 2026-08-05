# TollChat kill switch

The immediate kill switch is the proxy Lambda concurrency limit; it stops both private and public invocation without touching RDS or the ingestion pipeline.

```bash
AWS_PROFILE=nova-toll aws lambda put-function-concurrency \
  --function-name tollchat-chat-proxy \
  --reserved-concurrent-executions 0
```

Confirm `/api/config` no longer succeeds and record the incident time. For a public incident, also set `enable_public_chat = false` and apply Terraform so CloudFront removes `/api/*`; this restores the declared state.

Restore only after approval:

```bash
AWS_PROFILE=nova-toll aws lambda put-function-concurrency \
  --function-name tollchat-chat-proxy \
  --reserved-concurrent-executions 5
```

Then run the private preview smoke test. Never place credentials or response content in the incident record.
