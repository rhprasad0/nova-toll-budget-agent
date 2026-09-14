# PII protection for AgentCore telemetry

Apply a separate, versioned Bedrock Guardrail to telemetry copies before the
existing ADOT span and log exporters send them to AWS. The guardrail anonymizes
all 31 supported PII entity types and the existing credential patterns. Agent
inputs, tools, model configuration, and responses remain unchanged.

This follows AWS's recommendation to protect observability separately from
inference. See [Agentic AI Lens AGENTSEC05-BP01](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentsec05-bp01.html)
and [ApplyGuardrail](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ApplyGuardrail.html).
Detection is probabilistic: names, addresses, uncommon formats, and credentials
can be missed. The public page, FAQ, and privacy notice disclose that limitation.

CloudWatch data protection is an additional layer. It masks supported findings
in queries and subscription delivery, including Firehose's S3 archive. It does
**not** remove CloudWatch's underlying originals, and privileged `logs:Unmask`
readers can recover them. The added roles do not grant that permission. See
[CloudWatch sensitive log data protection](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/mask-sensitive-log-data.html).

## Export boundary

`agent/telemetry.py` initializes before the application. It wraps sampled and
unsampled span exporters and the AWS log batch exporter's two references, using
the pinned ADOT 0.19.0 / OpenTelemetry SDK 1.44.0 processor layout. Upgrade those
versions together with the wiring tests. Unknown layouts stop startup.

Attributes are scanned together as JSON, including dynamic keys. Bodies, span
names, events, links, status descriptions, and instrumentation scope content
are scanned. Deployment resource metadata, random session UUIDs, token counts,
and the three system-prompt version/hash fields remain useful for diagnosis.
The original in-memory records are never modified.

Each batch has a bounded, ephemeral cache and a 30-second budget. Text over
10,000 characters, malformed responses, timeouts, denied access, and exhausted
budgets produce an omission marker. There is no raw fallback. Requests have
five-second connect/read timeouts and no retry. Guardrail calls suppress their
own instrumentation. Ordinary console messages and exceptions become static
markers; the separate metrics exporter is disabled. Token usage remains in spans.

CloudWatch metric filters count redaction omissions/errors and export failures.
Alarms also watch CloudWatch's PII findings after application redaction. Only
static diagnostics may be used while investigating; do not log failed content.

## Delivery sequence

1. Merge the prerequisite PR: additive foundation guardrail and account-local
   IAM policies, optional guardrail handoff, and exact application-plan validator
   contracts. Required CI still runs against trusted `main`.
2. From the merged checkout, prepare a private saved foundation plan in each
   fixed account: development `903859731897` / `nova-toll-dev`, then production
   `920534282028` / `nova-toll-prod`, both in `us-east-1`. Use each checked-in
   backend. Preserve the existing budget recipient, fetcher artifact, route
   advertisement setting, and development final-snapshot identifier in memory.
   Keep state, plan JSON, and command logs private.
3. Review the full plan. Only the telemetry guardrail/version, additive telemetry
   IAM policies/attachments, production Firehose/log delivery roles, and the
   foundation output may change. Stop on replacements, deletes, or unrelated
   changes. Recheck account and saved-plan digest; apply that exact plan. Require
   a zero-change follow-up foundation plan. No database migration is needed.
4. Merge the activation PR with the exporter, CloudWatch policies, both archive
   destinations, and notices. Use the existing protected development delivery,
   then the protected production release/plan/apply sequence in `RUNBOOK.md`.
   Do not bypass environment review or exact artifact/plan checks.
5. Use a fresh synthetic session per environment with a fabricated name, email,
   phone, address, and dummy credential. Verify the user response still works.
   Inspect only that session/time window: CloudWatch spans and log events, the
   resulting Firehose S3 records, and the corresponding Athena rows. Require
   observed redaction markers, no seeded raw values, and preserved trace IDs,
   timings, tool labels, and token counts. Do not treat an empty query as success.
   Check metrics for omissions and any downstream PII findings.

Development CloudWatch retention stays seven days; production stays one day.
Both trace archives expire after seven days, with asynchronous S3 lifecycle
deletion. Existing development traces are not rewritten or purged. New chat
does not delete retained diagnostic records.

If startup or live verification fails, hold the release and fix the exporter or
guardrail configuration. Do not restore a runtime that exports raw payloads as
a privacy-preserving rollback. Retain CloudWatch masking during recovery.

## Local checks

Run `uv run --directory v2 pytest tests/test_telemetry_redaction.py`, the relevant
infrastructure contract tests, `python3 -m unittest infra.test_delivery_plan_validator
infra.test_release_manifest`, `python3 infra/test_delivery_identities.py`, Ruff,
Pyright, and Terraform validation for both roots. Tests serialize actual OTLP
records and exercise real ADOT startup and both AWS batch export paths offline.
