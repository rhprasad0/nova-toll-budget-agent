# AWS Q Implementation Brief: TollChat Dev and Production Delivery

This revised plan is self-contained because you have no repository or internet
access. Prefer the smallest safe change. Do not add Kubernetes, a third
environment, HCP Terraform, or a custom deployment service.

## System and goal

TollChat is a public AI agent for Northern Virginia tolls. It runs in one AWS
account in `us-east-1`. It has a VPC, one deletion-protected IAM-authenticated
PostgreSQL RDS instance `nova-toll-db`, encrypted/versioned S3, KMS, SSM, IAM,
SNS, Tailscale, and an S3 Terraform backend. Production uses `nova_toll` with
schemas `pricing` and `oracle` and seven-day RDS backups.

The application uses CloudFront, ACM, WAF, private S3, an IAM-only Lambda URL
behind CloudFront OAC, Cloudflare DNS, Lambda, AgentCore, DynamoDB, SQS,
EventBridge, CloudWatch, and PostgreSQL.

Create persistent development at `dev.tollchat.ai`; keep production at
`tollchat.ai`. A merge to `main` deploys development. A published allowed `v*`
GitHub Release promotes the exact development-proven commit and artifacts to
production after migration, eval, and human approval gates.

## Environment and Terraform design

Keep shared foundations in Terraform root/state `infra/` at
`nova-toll/terraform.tfstate`. Use one application root `v2/infra/` with
explicit backend configs, not CLI workspaces:

- prod: preserve `nova-toll/v2/terraform.tfstate` and all current names;
- dev: `nova-toll/v2/development/terraform.tfstate` and explicit dev affixes.

Add only environment, domain, name affix, database, concurrency, retention, and
alarm inputs. Before creating dev, the refactored prod plan must show zero
changes.

Share VPC/endpoints, RDS host, raw pricing, backend/artifact buckets, and
production alert foundation. Isolate the edge/site; runtime, queues, schedules,
logs, alarms, IAM/KMS; DynamoDB; and PostgreSQL databases/roles. Terraform
enforces zero dev provisioned concurrency and bounded log retention. Dev alarms
use a non-paging topic or no action; a shared SNS topic fans out to everyone.

Create `nova_toll_dev` and initial roles through one approved administrator SQL
bootstrap. Do not add a PostgreSQL Terraform provider or `null_resource`.

Do not sequence the edge with `terraform apply -target`; preserve Terraform's
dependency graph. Before initial DNS/canary, verify CloudFront is `Deployed`,
WAF/OAC are effective, and the Lambda URL requires IAM. A future new hostname
may use a separate normal saved plan with a DNS-enable input. Prod DNS stays.

New/materially changed WAF rules run in COUNT in dev and a prod observation
release before BLOCK; unchanged rules do not repeat this each release.

## OIDC, IAM, networking, and secrets

Use GitHub OIDC and no long-lived AWS keys. Create:

1. trusted planner/plan writer;
2. development deploy;
3. production deploy;
4. `tollchat-db-migrator-dev`;
5. `tollchat-db-migrator-prod`.

Do not give plan-write access to untrusted PR CI. Every role requires
`aud = sts.amazonaws.com` and the exact immutable repository `sub`. Dev deploy
and migration require `ref:refs/heads/main`. Prod roles require the protected
`production` environment plus exact reusable `job_workflow_ref`, pinned to its
path/ref. This claim supplements, not replaces, `sub` and `aud`.

The planner gets discovery reads plus only state-lock and unique plan writes.
Use an allow-list and permissions boundary, not a brittle mutation deny list.
Do not allow `sts:TagSession` or trust unverified principal tags.

Scope state access twice, in IAM and bucket policy: dev only under
`nova-toll/v2/development/`; prod only the existing state object and lockfile.
Use `s3:prefix` on list operations. Dev raw-pricing access is Get-only on
required `raw/` prefixes, with no write/delete. Use exact KMS key ARNs and
verify dev principals are absent from prod key policies/grants. A key alias
does not grant access.

Use `tag:ci-dev` and `tag:ci-prod` in Tailscale ACLs and test workflow network
reachability. Security groups cannot match Tailscale tags. Both databases share
one endpoint, so PostgreSQL permissions are the real boundary.

Cloudflare write tokens stay in SSM and become available only inside approved
apply jobs. No credentials, decrypted parameters, plans, or tokens enter public
artifacts or summaries.

## Database boundary and migrations

The shared RDS instance is a cost tradeoff, not an instance-level security
boundary. Never use the master user or any `rds_superuser` identity in CI,
migration, or runtime. Use distinct dev/prod login and migrator roles. Revoke
`CONNECT` on both databases from `PUBLIC`, then grant it only to named roles for
that environment; scope schema/object grants likewise.

RDS IAM policies use exact
`dbuser:DB_RESOURCE_ID/DATABASE_USER` ARNs, never wildcards. The ARN does not
contain a database name, so PostgreSQL `CONNECT`, membership, and object grants
enforce database selection. Assert runtime/migrator users are not members of
`pg_monitor`, `rds_superuser`, `rdsadmin`, `rds_replication`, or
`rds_extension`. Dev gets no `dblink`, `postgres_fdw`, cross-database
credentials, extension installs, or `pg_cron`. Negative-test both boundaries.

PRs use disposable PostgreSQL 17/PostGIS. They reject changed released
migrations, apply new migrations from declared prior versions, test
atomicity/reruns, and compare with bootstrap. PRs never touch deployed DBs.

One reviewed runner handles dev/prod using the environment migrator, RDS IAM,
a PostgreSQL advisory lock, expected installed versions, a contiguous pending
chain, fatal errors, post-apply version/schema verification, and a non-secret
report.

Every migration is reviewed metadata-classified as `expansion` or `contract`.
Expansion must support the old app and may run before deployment. Contract is a
separate release; the runner refuses it unless the deployment manifest proves
the compatible app is live and evidence proves the old path unused. No
automatic down-migrations.

Before non-trivial prod migrations verify latest restorable time. A destructive
contract release needs a snapshot decision and tested recovery. RDS PITR
restores the entire instance; single-database recovery means restore to another
instance, then export/import `nova_toll`.

## Immutable plan and artifact promotion

Build Lambda/AgentCore packages once per commit into encrypted, versioned S3
keys identified by commit and SHA-256. Dev and prod consume identical objects.

PRs publish sanitized plan summaries only. For prod, upload the exact binary
plan to a unique private S3 key with the exact SSE-KMS key, S3 SHA-256 checksum,
local plaintext SHA-256, versioning, and Object Lock Compliance retention.
Record object key/version, both checksums, KMS ARN, timestamp, and Terraform
state serial. Approval eligibility is 24 hours, retention is 48 hours, and
lifecycle expiry is three days. Do not use an SSE-KMS ETag as a digest.

The writer can Put only its unique plan key and gets encryption/data-key
permissions; the prod applier can Get/GetVersion only the recorded version and
decrypt it. Neither can overwrite/delete versions or alter retention. Deny
insecure transport and missing/wrong encryption. No CI role gets `kms:*`.
Before apply, re-download the exact version and verify checksums, KMS key, age,
state serial, artifact digests, and schema baseline.

## Workflows and eval gates

Pull request: run tests, disposable migrations, security/offline evaluator
checks, deterministic builds, and read-only dev/prod plans. Expose no apply or
deployed-database credentials.

Merge to `main`: wait for CI; build/upload once; migrate dev; plan/apply dev;
wait for edge/runtime readiness; run endpoint smoke plus a small live agent
eval; record a GitHub development deployment. Serialize and never cancel an
active migration/apply.

Published release: require allowed tag and successful dev deployment; resolve
the identical artifacts; run the controlled repeated release eval; create
migration preflight and immutable saved plan; show non-secret evidence; require
the protected production approval; apply expansion migrations; verify/apply
the exact plan; run bounded canaries. A later contract release verifies the
compatible app is healthy, applies the contract, and canaries again. Serialize
production and never cancel active mutations.

Keep deterministic graders for routes, tool calls, money, safety, and required
disclosures. PR self-checks make no model calls. Dev runs small live smoke;
schedules retain time-window integration evals. Release runs the exact candidate
against versioned recorded tool outputs, three times per critical case with
`pass^3`. Prod runs only one or two bounded canaries. Record dataset, commit and
artifact hashes, model/prompt/renderer/tool versions, calls, turns, tokens,
latency, and estimated cost. Infrastructure failures and agent failures both
block, but are reported separately. Add no LLM judge without a subjective need.

## Evidence, rollback, and cost guardrails

Store one encrypted JSON manifest per deployment in S3; no DynamoDB manifest
table. Record environment/URL, commit/tag, artifact versions/digests, Terraform
state and plan identity, schema versions, eval identity/results, timestamps,
Lambda alias/version, and current/prior AgentCore runtime ARN, endpoint ARN,
live version, and target version. Show only non-secret fields in GitHub.

On failure after compatible expansion, retain/repoint the prior Lambda alias
and update the AgentCore endpoint to the recorded prior runtime version, then
roll infrastructure/schema forward. The runbook must test both reverts.

Use account AWS Budget notifications at 80% forecast/actual and 100% actual.
Defer Intelligent-Tiering until measurements show savings, and a parameterized
dashboard until duplicate dashboards exist.
