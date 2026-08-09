# AgentCore tracing

TollChat's private preview captures every invocation for evaluation and debugging. Native Strands spans retain structure and timing but redact all sensitive message attributes. The correlated `tollchat.runtime_trace` records are the canonical source for sanitized application-visible content.

## Storage and schema

- `aws/spans`: Transaction Search spans, including `session.id`, trace/span identifiers, model and tool span structure, and timing.
- `/aws/nova-toll/agentcore/traces`: application-sanitized, versioned `tollchat.runtime_trace` records written directly by the runtime.
- Both groups use the AgentCore telemetry CMK and expire after 30 days. CloudWatch Logs retention deletes expired events asynchronously and does not support deleting one session from an otherwise retained log stream.
- No trace archive is created and no individualized trace lookup or deletion is offered. Fixed retention controls and disclosure approval before public use remain tracked in issues #90 and #96.

Record version 1 is JSON Lines with `stage` (`input_guardrail`, `agent`, `output_guardrail`, or `invoke`), trace/span/session/AWS request identifiers, chunk index/count, SHA-256, and a sanitized JSON payload. The payload holds prompts, application-visible model messages, tool calls and results, full Guardrail assessments, final responses, errors, timings, and deployed model/prompt/toolset versions. System-prompt text and provider-hidden reasoning are never included.

Credential-like keys or values cause the whole containing string field to become `[REDACTED]` before export. Native Strands input, output, and system attributes are also `[REDACTED]`; CloudWatch data protection is a second read-time control, not the primary sanitizer. Vended `APPLICATION_LOGS` delivery remains disabled because it would duplicate unsanitized invocation request and response payloads.

ADOT botocore auto-instrumentation remains disabled because its AWS SDK spans include the caller's temporary access-key ID. Explicit TollChat spans and governed Guardrail records retain the required operation detail without exporting that credential identifier.

## Access and queries

Request access from the repository owner to assume `nova-toll-trace-reviewer`. Do not grant general production-log or deployment permissions. CloudTrail records role assumption and CloudWatch Logs query API calls.

Query a known session in `aws/spans`:

```text
fields @timestamp, traceId, spanId, name, attributes.session.id
| filter attributes.session.id = "SESSION_ID"
| sort @timestamp asc
```

Query its content records in the runtime group:

```text
fields @timestamp, @message
| filter @message like /tollchat.runtime_trace/
| filter @message like /SESSION_ID/
| sort @timestamp asc
```

Export the query results only to a temporary local file, run `uv run python scripts/verify_agentcore_trace.py <file>`, then delete the raw export. Never commit raw traces or place them in `eval/results/`.

## Deployment check

For a new account, Terraform enables Transaction Search first. Its Logs resource policy allows X-Ray to write both `aws/spans:*` and `/aws/application-signals/data:*`. AWS then creates the reserved `aws/spans` group; the Terraform bootstrap waits for it and applies retention and CMK settings before the data-protection policy. Terraform also connects the runtime's `TRACES` delivery source to the `XRAY` destination. Do not add `APPLICATION_LOGS` delivery.

The direct-code runtime entry point must remain `opentelemetry-instrument agent/agentcore_entrypoint.py`; setting OTEL environment variables without that launcher does not initialize the ADOT pipeline. After applying infrastructure and deploying the runtime package, run the private trace smoke command documented by `scripts/smoke_agentcore_traces.sh`. It invokes the `preview` qualifier with a unique session, waits for ingestion, checks both groups, validates chunks and correlation, and prints only metadata suitable for a curated passing report. Run it from the approved Tailscale/operator path; CI remains unable to reach the private preview by design.

The check must fail on missing model/tool/Guardrail stages, missing versions or timings, broken chunk hashes, trace/session mismatches, system-prompt content, credential markers, or no evaluable trace. Transaction Search can take about ten minutes after first enablement; ordinary trace ingestion is normally about ten seconds.

## Troubleshooting and cost

- No spans: verify the X-Ray trace-segment destination is `CloudWatchLogs`, Runtime delivery is active, sampling is always-on, and the runtime role can write Logs/X-Ray data.
- Spans but no content: verify `TOLLCHAT_TRACE_LOG_GROUP`, the runtime's scoped Logs write permission, and the `/aws/nova-toll/agentcore/traces` stream.
- Evaluator finds nothing: confirm the queried `session.id` appears in both destinations and the time window includes ingestion delay.
- Incomplete chunks: do not use the trace as evidence; retain the temporary export for local diagnosis only, then delete it.
- Access denied: assume the reviewer role; do not broaden the runtime writer role.

Primary costs are 100% trace ingestion, CloudWatch Logs storage/query scanning, Transaction Search indexing at 1%, KMS requests, and live model calls. Keep queries session- and time-bounded. Revisit sampling only before public launch; changing it weakens the every-invocation promise.
