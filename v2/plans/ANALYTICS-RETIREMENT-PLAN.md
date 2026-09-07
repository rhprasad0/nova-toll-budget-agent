# Analytics Retirement Plan

Status: **unapplied design**. This document grants no AWS, Terraform, CI,
archive, deletion, or key-management authority and contains no live inventory.

Scope: retire the two source-stopped analytics families—public usage counting /
publication and agent-route analytics—while preserving active sessions, public
report publication, WAF enforcement, and independent security logging.

## Preconditions and boundaries

The following are source-derived identities, not proof that a resource exists.
Before either record can execute, an independently reviewed operator must
reconcile the live account, region, state object, deployed code/configuration,
physical resource, object/version, and producer relationships. Missing live
inventory, VersionIds, dynamic Athena view/partition state, archive destination,
or archive CMK blocks execution; it does not block this documentation.

| Record | Account / region | Application state key | Source-derived measurement identity |
| --- | --- | --- | --- |
| Current development | `903859731897` / `us-east-1` | `nova-toll/v2/development/terraform.tfstate` | `aws-waf-logs-tollchat-agent-reports-903859731897-dev`; `tollchat_agent_reports_development` / `tollchat-agent-reports-dev` |
| Current production | `920534282028` / `us-east-1` | `nova-toll/v2/terraform.tfstate` | `aws-waf-logs-tollchat-agent-reports-920534282028`; `tollchat_agent_reports` / `tollchat-agent-reports` |

The production-account `legacy-development` deployment is a third, #333-owned
scope. Its state, old `-dev` physical names, frozen inventories, migration
recovery, and [runbook procedure](../RUNBOOK.md) are excluded from both records.
There is no development-to-production AWS read path ([account contract](../../infra/account-contract.json)).

The default retention choice is **preserve**. A human must record either
preserve or irreversible delete for every separately named target. Ordinary
development delivery and the production `delivery_proof` planner remain
unchanged; neither is retirement authority ([IAM contract](../../infra/iam.tf),
[development workflow](../../.github/workflows/v2-development-delivery.yml),
[production planner](../../.github/workflows/v2-production-plan.yml)).

## Source-derived inventory

### Public usage: exact targets only

In each environment, the data operation may address only:

- the DynamoDB item whose partition key is exactly `credential_hash = usage#all`
  in the shared session table (source resource:
  [`tollchat_sessions`](../infra/agentcore.tf#L127-L145)); and
- the exact `usage.json` object in that environment's site bucket (source
  object and retained lifecycle: [`site.tf`](../infra/site.tf#L89-L100)).

The source-derived candidates are `tollchat-v2-anonymous-sessions-dev` /
`tollchat-v2-anonymous-sessions`, `tollchat-site-903859731897-dev` /
`tollchat-site-920534282028`, and `usage.json`; live reconciliation decides
which physical identity belongs to each record. Do not select ordinary session
rows, the shared session table, the site bucket, the site KMS key, a wildcard,
or the active report publisher. The retained log group
`/aws/lambda/tollchat-v2-usage-publisher${suffix}` ([source](../infra/site.tf#L167-L170))
is a separately named historical target with its own archive/delete approval;
it is never part of the exact item/object operation.

The proxy now uses only session `PutItem` and conditional `UpdateItem`
operations ([handler](../lambdas/chat_proxy/handler.mjs#L121-L198)); absence of a
current counter writer does not prove deployed producers stopped.

### Agent-route analytics: retained data and metadata

For each current account record, reconcile the source-derived measurement
bucket and every separately approved scope below:

- S3 prefixes `AWSLogs/`, `registry/agent_registry.ndjson`, `generations/`,
  `rollups/usage/`, `rollups/completions/`, and `athena-results/`;
- Glue database named in the record's identity table and tables
  `agent_report_waf_logs`, `agent_registry`, `agent_report_generations`,
  `agent_report_rollups`, and `agent_report_rollup_completions`;
- any deployed `latest_agent_report_usage` view and partitions, Athena
  workgroup/history/results, and the historical log group
  `/aws/lambda/tollchat-v2-agent-usage-rollup${suffix}`;
- the analytics KMS key resource `aws_kms_key.agent_measurement` and alias
  `alias/tollchat-v2-agent-measurement${suffix}`.

The bucket, private-access/encryption controls, key/alias, lifecycle, registry,
catalog, workgroup, and log group are declared in
[`agent_measurement.tf`](../infra/agent_measurement.tf#L1-L43),
[`agent_measurement.tf`](../infra/agent_measurement.tf#L45-L116), and
[`agent_measurement.tf`](../infra/agent_measurement.tf#L118-L324). Dynamic
views, partitions, query history, and results are live-reconciliation items,
not assertions that source still deploys them. The existing seven-day
`AWSLogs/` and `athena-results/` expiration remains in force unless a separate
retention decision is approved. The rollup log group is separately
archive/delete-approved, not an implicit consequence of deleting bucket data.

The active publisher is not a retirement target: `handler` calls
`_publish_streamed` and writes public route report objects, index, sitemap, and
manifest ([handler.py](../lambdas/publisher/handler.py); symbols
`_publish_streamed` and `handler`). Preserve report publication, freshness, and
output contracts. Preserve independent WAF
enforcement and security logging; if live logging still targets a listed
location, map that dependency before any deletion and do not disable it as an
analytics stop.

## Execution records

### Record D — current development

- **Fixed identity:** account `903859731897`, region `us-east-1`, state key
  `nova-toll/v2/development/terraform.tfstate` ([backend](../infra/backend.development.hcl)).
- **Public usage:** exact reconciled `usage#all` item in the development shared
  session table and exact reconciled `usage.json` object in the development
  site bucket; the usage-publisher log group is a separate target and decision.
- **Route analytics:** exact reconciled development measurement bucket,
  prefixes, Glue database/tables, dynamic view/partitions, Athena
  workgroup/history/results, rollup log group, and analytics key/alias listed
  above. No production or #333 legacy identity may appear in this record.
- **Execution gate:** obtain authority and attach the fresh initial
  account/state/resource/version inventory before maintenance; attach
  freeze-and-drain proof and a final inventory before archive or deletion; add
  sanitized archive evidence after verified archive, or deletion evidence after
  verified deletion.

### Record P — current production

- **Fixed identity:** account `920534282028`, region `us-east-1`, state key
  `nova-toll/v2/terraform.tfstate` ([backend](../infra/backend.production.hcl)).
- **Public usage:** exact reconciled `usage#all` item in the production shared
  session table and exact reconciled `usage.json` object in the production
  site bucket; the usage-publisher log group is a separate target and decision.
- **Route analytics:** exact reconciled production measurement bucket,
  prefixes, Glue database/tables, dynamic view/partitions, Athena
  workgroup/history/results, rollup log group, and analytics key/alias listed
  above. Do not include the production-account `legacy-development` state,
  `-dev` physical names, or #333 procedure.
- **Execution gate:** obtain authority and attach the fresh initial
  account/state/resource/version inventory before maintenance; attach
  freeze-and-drain proof and a final inventory before archive or deletion; add
  sanitized archive evidence after verified archive, or deletion evidence after
  verified deletion.

## Required producer-stop proof

Per record, a separately bounded maintenance authorization must verify that the
deployed proxy version is counter-free and the deployed report publisher
version is marker-free, then review and remove only obsolete analytics write
IAM. It must also review the exact old usage-publisher and agent-usage-rollup
code/configuration versions, schedules, EventBridge targets and invoke
permissions, Lambda retry/concurrency settings, queued and in-flight work, and
WAF ACL and logging configuration. Stopping only dedicated schedules is not
enough if an active function still contains an analytics writer. The operator
may disable or remove only the reviewed retired producer targets and invoke
permissions, preserve active session/report/WAF/security grants, wait the
bounded retry/drain period, and prove no new writes from retired producers
before taking the final data inventory. Source removal, a Terraform plan, a
stale state address, or a routine CI result is not deployed stop proof.

The active report publisher, current session path, WAF enforcement, and
independent security logging must remain available and distinguishable. Any
ongoing independent security-log writer is reconciled and protected rather
than silently treated as a retired analytics producer. Both retained log
groups named above require their own stop/retention evidence and approval.

## Preservation and deletion evidence

Preserve is the default and may simply leave retained source data and metadata
managed under the existing controls; keeping it does not require a redundant
archive. If preservation is selected together with later source deletion,
archive only the exact approved data and control metadata to a private,
versioned, environment-specific destination encrypted with an independently
scoped archive CMK (one destination and CMK for D, one for P). The archive CMK
must remain independently readable without the source analytics key, which may
be retired later. Record only sanitized evidence: source bucket/key or
table/item identity; source VersionId or explicit unversioned marker;
destination VersionId; ETag, size, and content SHA-256; relevant
metadata/tags; archive CMK ARN; and verification time. Independently read the
archive and recompute the digest before any source delete; ETag alone is not
proof. Do not put raw WAF logs, sessions, state, credentials, or archive bodies
in this repository.

If irreversible deletion is selected, require explicit informed human approval
that it is without archive. Delete only the separately authorized exact
`usage#all` item, exact `usage.json` object, individually named analytics
prefixes, catalog/view/partition/workgroup/history/result metadata, and
historical log target. The final inventory must include source object versions,
delete markers, multipart-upload leftovers, and any data/control references.
No wildcard cleanup, unreviewed prefix expansion, `terraform state rm`,
`force_destroy`, automatic writer restoration, or blanket key/table/bucket
deletion is allowed. Preserve the seven-day lifecycle absent a separate
retention approval; if data is to be preserved elsewhere, archive it before
that seven-day expiry rather than treating the lifecycle as indefinite.

## Fixed ordering

1. Reconcile each record's account, region, state key, physical identities, and
   obtain exact producer-maintenance and archive-or-delete authority.
2. Freeze only reviewed retired producers, prove retry/queue drain and no new
   retired-producer writes, then take the final data and metadata inventory.
3. If preservation is selected with source deletion, archive exact
   data/control metadata and verify private readability, checksums, metadata,
   and source/destination versions; if data remains managed in place, record
   that retention decision and preserve its controls; otherwise obtain explicit
   approval for irreversible deletion without archive.
4. Delete only exact approved usage item/object, analytics prefixes/metadata,
   and separately approved historical log targets.
5. Verify absence and retained session, publisher, WAF, security, encryption,
   and lifecycle controls.
6. Remove an empty dedicated analytics storage resource only with separate
   approval.
7. Remove the analytics alias/key last, after no data, metadata, storage, or
   recovery evidence references it. Never restore a retired writer as an
   automatic rollback.

## Explicit non-goals

This plan does not change application behavior, report publication, session
rows/table, site bucket/KMS key, WAF enforcement/security logging, IAM delivery
authority, `delivery_proof`, CI workflows, Terraform, the frozen #333
materials, or live resources. It introduces no replacement analytics pipeline,
archive automation, migration, `force_destroy`, wildcard cleanup, HA/rollout/
rollback machinery, or new maintenance mechanism.
