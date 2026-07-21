# VDOT Toll Poller — Spec

Status: approved design, pre-implementation · Owner: Ryan Prasad · Last updated: 2026-07-21

Cloud poller for the two VDOT SmarterRoads toll pricing feeds, replacing the
home cron (`hermes-agent/tools/va_toll_ingest`). Runs in the dedicated AWS
account **nova-toll-prod (920534282028)**, us-east-1, deployed via Terraform
from this repo.

## Goals

- **Never lose a poll.** The data cannot be re-acquired (no historical API
  access — bulk downloads are WAF-blocked). Fetching is the only unrepeatable
  step and must not depend on anything else working.
- **Live-queryable store.** The future agent queries Postgres directly;
  freshness = last poll (≤10 min).
- **Cost under $25/mo**, expected <$20/mo.
- 24/7 coverage of both feeds at 10-minute cadence (upgrades the home poller's
  weekday-peak-only windows, and adds I-66 which has never been captured).

Non-goals: historical backfill from VDOT (WAF), analytics marts, the agent
itself, CI/CD (manual `terraform apply` for now).

## Architecture

```
EventBridge rule (rate(10 minutes), 24/7)
   │
   ▼
toll-fetcher Lambda        — no VPC (needs internet), Python 3.13, stdlib+boto3
   GET I-95 CSV, GET I-66 XML   (per-feed failure isolation)
   PUT payloads → S3 raw/
   emit CloudWatch metric PollSuccess{feed}
   │
   ▼  S3 ObjectCreated event
toll-loader Lambda         — in VPC (default VPC subnets + S3 gateway endpoint),
   parse → unified schema      Python 3.13 + psycopg
   idempotent upsert → RDS Postgres
```

Why two Lambdas: the loader must sit in the VPC to reach RDS, but an in-VPC
Lambda has no internet without a NAT Gateway (~$32/mo). Splitting keeps the
fetcher on the public Lambda network and gives the loader free S3 access via a
gateway endpoint. Side effect: fetch and parse are fully decoupled — a parser
bug never loses data; re-loading is done by re-touching raw objects (or a
manual replay script) since the upsert is idempotent.

## Data sources

| | I-95/395/495 | I-66 ITB |
|---|---|---|
| URL | `https://data.511-atis-ttrip-prod.iteriscloud.com/smarterRoads/tollRoad/I95/current/tollingTripPricing_I95.csv` | `.../tollRoad/I66/current/tollingTripPricing-I66.xml` |
| Auth | `?token=` (I-95 token) | `?token=` (separate I-66 token) |
| Format | fixed-width-padded CSV | XML, `<opt …/>` attribute rows |
| Rows/poll | ~320 (317 OD pairs) | ~44 zone pairs |
| Timestamps | `DD/MM/YY HH:MM:SS` in America/New_York | ISO-8601 UTC (`…Z`) |

Tokens are per-dataset (the I-95 token 403s on the I-66 path). Only the
iteriscloud host works — the `d2p43lbz0yzc6a.cloudfront.net` host 403s; do not
use it. WAF etiquette is a hard requirement: **one attempt per feed per tick,
no retry loops.** A missed tick costs one 10-minute sample; a retry storm
risks the tokens.

Parser quirks the loader must handle (all observed in production data):

- CSV header typo `CALULCATEDDATETIM` (and truncated `INTERVALENDDATETI`) —
  match exactly, fail loudly on drift.
- Dash separator row after the header; blank lines; cells padded with spaces.
- Blank `STARTZONENAME` (e.g. "PRINCE WILLIAM TO I-395 N") — nullable column.
- `corridor_id` 952 appears under `corridor_name` I-95-NB for five Opitz-bound
  OD pairs — store as-is, never "fix" source data.
- Rate/status independence: rows can be CLOSED with a stale nonzero rate, or
  open with $0.00 (I-66 off-peak is legitimately $0). Availability semantics
  live in `link_status`, never in `rate > 0`.
- I-66 XML has no `ODPAIRID`/`ODPAIRNAME` and no `LINKSTATUS`; it does carry
  `IntervalDateTime` (interval start), which the CSV lacks.
- DST fall-back: the CSV's America/New_York timestamps are ambiguous for one
  hour each November; the parser resolves with `fold=0` (first occurrence).
  Documented so overlap verification doesn't mystery-mismatch that hour.

## S3 layout

Bucket `nova-toll-raw-920534282028`, versioning on, all public access blocked.

```
raw/feed=i95/date=2026-07-21/1440Z.csv
raw/feed=i66/date=2026-07-21/1440Z.xml
```

Object key timestamp = fetch time UTC, rounded to the schedule tick. No
lifecycle rules; objects are kept forever (~3 GB/year in Standard is pennies).
The most recent object per feed is the future agent's "current toll" read path.

~8 MB/day across both feeds; ~3 GB/year.

## Database schema

RDS Postgres 17, single table, evolved from the home poller's `trip_pricing`
(`hermes-agent/tools/va_toll_ingest/va_toll_ingest/db.py` is the port source
for the upsert; `normalize.py` for the CSV parser).

```sql
CREATE TABLE trip_pricing (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feed               text NOT NULL CHECK (feed IN ('i95', 'i66')),
    interval_start_at  timestamptz,              -- i66 only
    interval_end_at    timestamptz NOT NULL,
    current_at         timestamptz,              -- i95 only
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    od_pair_id         integer,                  -- i95 only
    od_pair_name       text,                     -- i95 only
    start_zone_id      integer NOT NULL,
    start_zone_name    text,
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    link_status        text NOT NULL DEFAULT 'NOT_APPLICABLE',  -- i66 has none
    s3_key             text NOT NULL,            -- raw object provenance
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (feed, interval_end_at, start_zone_id, end_zone_id)  -- upsert key
);
```

Raw payloads live in S3 (`s3_key` is the provenance); no raw copy in the row.
The source URL is derivable from `feed`. Secondary indexes wait until the
agent exists and a query is measurably slow.

Upsert: `ON CONFLICT (feed, interval_end_at, start_zone_id, end_zone_id)
DO UPDATE` — port of the existing `UPSERT_SQL` with the zone-based key (both
feeds carry zone ids natively; no synthesized I-66 OD pair id). Re-delivered
S3 events and replays are therefore harmless.

**Roles:**

| Role | Grants | Used by |
|---|---|---|
| master (RDS-managed, Secrets Manager) | superuser-ish | schema migrations, admin |
| `loader_writer` (IAM auth: `GRANT rds_iam`, no password set) | SELECT/INSERT/UPDATE on `trip_pricing` | toll-loader Lambda |

(An `agent_readonly` role ships in the same PR as the agent, not before.)

## Lambda details

**toll-fetcher** — no VPC. Env: SSM parameter names + bucket name. Reads both
tokens from SSM (SecureString) at cold start. For each feed independently:
GET (30 s timeout, single attempt, response read capped at 5 MB) →
`put_object` → `put_metric_data` (`NovaToll/PollSuccess`, dimension `feed`).
One feed failing must not prevent the other's PUT. Every error path scrubs
the token from URLs before logging or raising — it rides in the query string
and would otherwise land in CloudWatch. Async retry: `MaximumRetryAttempts =
1` on the function's event-invoke config — the retry knob lives on Lambda,
not EventBridge (a re-fetch a minute later is normal client behavior, not a
storm).

**toll-loader** — VPC (default VPC subnets; S3 gateway endpoint added), SG
egress to RDS SG only. Triggered per raw object. Routes on `feed=` prefix:
CSV → ported `parse_trip_pricing_csv`; XML → new `parse_trip_pricing_xml`
(ElementTree over `<opt>` attributes — XXE-safe on 3.13; entity-expansion DoS
is accepted risk given HTTPS to VDOT, no defusedxml). Connects as
`loader_writer` via **RDS IAM auth**: the SDK signs the token locally — no
secret, no Secrets Manager API call, and therefore no VPC interface endpoint
or NAT (an in-VPC Lambda has no internet; its only AWS API needs, S3, is the
free gateway endpoint). `sslmode=verify-full` with the RDS CA bundle in the
zip — `require` encrypts but doesn't authenticate the server, which would
hand the 15-min IAM token to a MITM. After commit, logs the space-delimited
line `LOAD_OK <feed>`; a CloudWatch Logs metric filter turns these into
`NovaToll/LoadSuccess{feed}` — filter dimensions only work with JSON or
space-delimited patterns, hence the plain format (in-VPC Lambda can't call
`put_metric_data`; log-based metrics ride Lambda's own log pipeline for free). Reserved concurrency 5: a mass replay queues
instead of stampeding t4g.micro's ~85 connections. On parse failure: log,
alarm, exit nonzero — the raw object is safe and the exhausted event lands in
the `OnFailure` SQS queue for replay after the fix. Dependency packaging:
`psycopg[binary]` pinned and hash-verified (`pip install --require-hashes`)
in the deployment zip.

## Terraform

Lives in `infra/` in this repo. Terraform ≥ 1.10, AWS provider pinned.
Backend: dedicated state bucket `nova-toll-tfstate-920534282028` with native
S3 locking (`use_lockfile`, no DynamoDB). Provider: `profile = "nova-toll"`,
`region = "us-east-1"`, default tags `project = nova-toll-budget-agent`
(lowercase `project` — it must match the cost allocation tag key already
activated in the org management account; tag keys are case-sensitive in
billing).

Resources: raw bucket (+versioning, public-access block), state bucket (same
hardening: versioning, public-access block, SSE; bootstrap manually or
separate min-config), both Lambda functions + execution roles (least
privilege: fetcher = put_object on `raw/*`, SSM read, metrics; loader =
get_object, `rds-db:connect`, VPC ENI), loader `OnFailure` SQS queue, both
functions' event-invoke configs (fetcher `MaximumRetryAttempts = 1`; loader's
OnFailure destination), EventBridge rule + permission, S3 → Lambda notification (prefix `raw/` —
anything else landing in the bucket must not invoke the loader), log metric
filters for `LoadSuccess`, S3 gateway endpoint in the default VPC,
RDS instance + subnet group + SGs, SSM SecureString params for the two tokens
(**values entered out-of-band via CLI, never in Terraform state**), SNS topic +
subscription + CloudWatch alarms, log groups (30-day retention).

## RDS

`db.t4g.micro`, Postgres 17, 20 GB gp3 with `max_allocated_storage = 40`
(plus a `FreeStorageSpace` alarm — a full disk stops writes and the freshness
alarm alone wouldn't say why), single-AZ, 7-day automated snapshots, deletion
protection **on**, `storage_encrypted = true` (creation-time-only flag —
retrofitting means a snapshot-copy-restore dance), `manage_master_user_password
= true` (password lives only in Secrets Manager, never in state),
`iam_database_authentication_enabled = true` (loader connects with locally
signed tokens; no per-Lambda secret exists). All clients — loader and home
psql alike — connect with `sslmode=verify-full` + the RDS CA bundle.

**Network posture (accepted tradeoff):** `publicly_accessible = true`, with
the security group allowing 5432 from (a) Ryan's home IP /32 and (b) the
loader Lambda's SG only. Chosen for solo-dev ergonomics (direct psql,
pg_restore migration) at zero extra cost. Upgrade path if posture needs to
tighten: flip to private subnets + t4g.nano bastion with SSM port forwarding.
Home IP is a Terraform variable — expect it to change occasionally.

## Observability

SNS topic → email `rhprasad@outlook.com`. The account budget alarm points at
the same topic. Alarms:

1. `toll-fetcher` Errors ≥ 1 (5-min period).
2. `toll-loader` Errors ≥ 1 (5-min period).
3. **Freshness:** `NovaToll/LoadSuccess` missing for 30 min per feed,
   treat-missing-data-as-breaching. Derived from the loader's post-commit
   `LOAD_OK` log lines via a metric filter, so it covers fetch, S3 event
   delivery, and load end-to-end. This is the "we are silently losing
   irreplaceable data" alarm and the most important one. `PollSuccess` stays
   for diagnosis — it localizes a failure to fetch vs load.
4. Loader `OnFailure` SQS queue visible messages ≥ 1 — async S3 events that
   exhaust their retries land there for replay instead of vanishing silently.
5. RDS `FreeStorageSpace` < 2 GB.

## Migration & cutover

1. `terraform apply`; confirm both feeds landing in S3 and RDS, and send a
   test SNS message — an unconfirmed email subscription silently mutes every
   alarm.
2. **Home poller keeps running in parallel** — do not touch the cron yet.
3. One-time merge of the local archive (~1.02M rows, 2026-04-17 →) into RDS:
   `pg_dump` → transform (`feed='i95'`, `s3_key='backfill/local-archive'`,
   `interval_start_at=NULL`) → idempotent upsert.
4. Verify a ≥1-week overlap window: row counts and spot-checked rates match
   between local and RDS for identical intervals.
5. Disable the home cron; local Postgres becomes a cold spare.
6. Follow-up: raise the account budget alarm from $10 to $25.

I-66 history starts at cloud go-live — no earlier data exists anywhere.

## Cost

| Item | $/mo |
|---|---|
| RDS db.t4g.micro + 20 GB gp3 | ~15–17 |
| S3 (raw + state + requests) | <0.50 |
| Lambda (2 × ~4.4k invocations/mo) | <0.10 |
| SNS, CloudWatch, SSM | <0.50 |
| **Total** | **<$20** (budget alarm $25) |
