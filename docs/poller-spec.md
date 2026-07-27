# VDOT Toll Poller — Spec

Status: live in prod since 2026-07-21 · Owner: Ryan Prasad · Last updated: 2026-07-25

Cloud poller for the two VDOT SmarterRoads toll pricing feeds, replacing the
home cron (`hermes-agent/tools/va_toll_ingest`). Runs in the dedicated AWS
account **nova-toll-prod (920534282028)**, us-east-1, deployed via Terraform
from this repo.

## Goals

- **Never lose a poll.** Recovering a missed sample is manual and painful (no
  historical API access — bulk downloads are WAF-blocked), so treat fetching as
  effectively unrepeatable: it is the one step that must not depend on anything
  else working.
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
   parse → per-feed schema     Python 3.13 + psycopg
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

RDS Postgres 17, **two tables, one per feed** — `trip_pricing_i95` and
`trip_pricing_i66`. Originally this was a single shared `trip_pricing` table
(ported from the home poller's `trip_pricing`,
`hermes-agent/tools/va_toll_ingest/va_toll_ingest/db.py`/`normalize.py`) with
a `feed` discriminator and a pile of per-feed-only nullable columns; that
shape existed to serve a generic agent query/route-graph tool. That tool was
deleted (see `docs/oracle-findings.md`), and with it gone the two
structurally different feeds are better served by two purpose-built tables
than one shared one.

```sql
CREATE TABLE trip_pricing_i95 (
    interval_end_at    timestamptz NOT NULL,
    current_at         timestamptz NOT NULL,
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    od_pair_id         integer NOT NULL,
    od_pair_name       text NOT NULL,
    start_zone_id      integer NOT NULL,
    start_zone_name    text,                      -- blank for some Prince William OD pairs
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    link_status        text NOT NULL,
    s3_key             text NOT NULL,              -- raw object provenance
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id, od_pair_id)
);

CREATE TABLE trip_pricing_i66 (
    interval_start_at  timestamptz NOT NULL,
    interval_end_at    timestamptz NOT NULL,
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    start_zone_id      integer NOT NULL,
    start_zone_name    text,                      -- nullable, same reason as i95
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    s3_key             text NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id)
);

CREATE TABLE trip_pricing_i95_live (
    observed_at        timestamptz NOT NULL,
    od_pair_id         integer NOT NULL,
    price_usd          numeric(10,2) NOT NULL,
    status             text,                      -- Transurban's own vocabulary; never mapped onto link_status
    road               text,                      -- "395"/"495"/"95", or NULL
    direction          text,                      -- "N"/"S", or NULL
    s3_key             text NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (observed_at, od_pair_id)
);

CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i66_zone_lookup_idx
    ON trip_pricing_i66 (start_zone_id, end_zone_id, interval_end_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i95_od_lookup_idx
    ON trip_pricing_i95 (od_pair_id, interval_end_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS trip_pricing_i95_live_od_lookup_idx
    ON trip_pricing_i95_live (od_pair_id, observed_at DESC);
```

**Schema version: 3.2.0** (semver; bump *major* on an upsert-key or
column-meaning change, *minor* on an additive column/index, *patch* on
comments/formatting). Kept in sync with `db/schema.sql` and enforced by
`lambdas/loader/tests/test_schema_contract.py`. Bumped from 2.3.0 → 3.0.0 for
the table split: both tables' keys and column sets changed. Bumped 3.0.0 →
3.1.0 for the addition of `trip_pricing_i95_live` (see "Secondary live
source" below) — purely additive, no existing table's keys or columns
changed, so *minor*. Bumped 3.1.0 → 3.2.0 for the three pricing-lookup
indexes below (`db/add_pricing_read_indexes.sql`) — also purely additive.

Raw payloads live in S3 (`s3_key` is the provenance); no raw copy in the row.
The source URL is derivable from the table itself, which is now the feed
discriminator (`feed` column and its CHECK are gone). Three read-path indexes
once existed on the old shared table for the agent's query tools; they were
dropped along with the agent (see `db/drop_agent_surface.sql`). The three
indexes above are their replacement, added when `agent_tools/i66_route.py`/
`i95_route.py`/`i495_route.py` (`docs/oracle-tools-spec.md`) became a real
read pattern:
without them, a per-key price lookup was a full scan of that key's entire
history, since neither table's primary key leads with the lookup column.

Upsert keys: `trip_pricing_i95` — `(interval_end_at, start_zone_id,
end_zone_id, od_pair_id)`. `od_pair_id` is part of the key because multiple
I-95 OD pairs legitimately traverse the same start/end zone at different
rates; a zone-only key would silently collapse them and drop distinct prices.
`trip_pricing_i66` — `(interval_end_at, start_zone_id, end_zone_id)`; I-66 has
no OD pairs, and since every key column is now `NOT NULL`, no `NULLS NOT
DISTINCT` is needed (unlike the old shared table, which needed it to make
i66's always-NULL `od_pair_id` dedup correctly). Both keys are `PRIMARY KEY`
now rather than a separate `UNIQUE` + surrogate `id` — nothing references the
old surrogate `id` now that the agent surface is gone. Re-delivered S3 events
and replays remain harmless either way.

**Roles:**

| Role | Grants | Used by |
|---|---|---|
| master (RDS-managed, Secrets Manager) | superuser-ish | schema migrations, admin |
| `loader_writer` (IAM auth: `GRANT rds_iam`, no password set) | SELECT/INSERT/UPDATE on `trip_pricing_i95`, `trip_pricing_i66`, `trip_pricing_i95_live` | toll-loader Lambda |
| `pricing_reader` (IAM auth: `GRANT rds_iam`, no password set) | SELECT only on `trip_pricing_i95`, `trip_pricing_i66`, `trip_pricing_i95_live` | `agent_tools/i66_route.py`/`i95_route.py`/`i495_route.py` (`docs/oracle-tools-spec.md`) |

The original `agent_readonly` role was abandoned along with the free-form
SQL agent surface it served; see `docs/oracle-findings.md`. `pricing_reader`
is a new, narrower role for the pricing-aware route tools — SELECT-only
on the same three tables `loader_writer` writes, nothing else.

## Secondary live source: Transurban Express Lanes

`trip_pricing_i95` has zero rows for 16 `od_pair_id`s (1374–1389) that
Transurban's own Express Lanes network bills but VDOT's feed has never
published (`docs/oracle-findings.md` section 2). Transurban publishes its own
live, **unauthenticated** snapshot at
`https://www.expresslanes.com/maps-api/infra-price-confirmed-all`, which
`toll-express-fetcher`/`toll-loader` capture into the separate
`trip_pricing_i95_live` table (see "Database schema" above) — not merged into
`trip_pricing_i95`, since this source can't supply that table's
`corridor_id`/`corridor_name`/`od_pair_name`/`start_zone_id`/`end_zone_id`/
`*_name` columns at all, just an opaque `od_XXXX` id.

**Hard limitations, by design, not bugs:**
- **No history.** The endpoint is a live current-snapshot only (confirmed:
  no pagination, no other history endpoint found). Ingesting it only
  captures "price from now on" — it does **not** backfill the 16 gap ids'
  past intervals, which are permanently unrecoverable.
- **No zone/corridor identity.** Just `od_pair_id`, `price`, `status`,
  `road`, `direction` — `status` is Transurban's own open/closed/null
  vocabulary and is never mapped onto `link_status`, a different concept
  from a different source.
- **One shared timestamp per pull.** Confirmed empirically across three live
  samples spanning two different hours (2026-07-25 18:xx and 19:xx ET,
  including one during deploy verification): the `time` field is always
  America/New_York, truncated to the hour, unchanged across each hour's
  samples. **Not directly confirmed:** that the underlying price *data*
  itself only refreshes once an hour — that's an inference from the
  response's own `#cache.max-age: 3600` header, not a held-open observation
  across a full hour boundary. Rather than tune a separate poll cadence
  around an unconfirmed assumption, `toll-express-fetcher` shares
  `toll-fetcher`'s own EventBridge rule (`rate(10 minutes)`, "EventBridge tick
  → toll-fetcher" in `infra/triggers.tf`) as a second target — one schedule,
  both fetchers fire together, nothing to keep in sync by hand. Whatever the
  source's real refresh rate turns out to be, polling faster just means more
  frequent free idempotent no-ops via `(observed_at, od_pair_id)` and
  `ON CONFLICT` — never a correctness issue.
- **Some ids are only priceable when their lane direction is actually
  open.** At capture time, the 4 gap ids on the then-open direction (495 N)
  had distinct, plausible prices; the 12 on the then-closed direction
  (395 S) mostly shared one identical placeholder-looking price. Rows are
  stored faithfully regardless of `status` — never inferred or dropped
  based on a guess — so a consumer's query decides what to trust.

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
CSV → ported `parse_trip_pricing_csv`; XML → `parse_trip_pricing_xml`
using `defusedxml`, with explicit row, field-length, identifier, and toll-rate
limits across all three feed parsers. Connects as
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

**toll-express-fetcher** — no VPC, same shape as toll-fetcher but simpler: a
single unauthenticated URL, no SSM token lookup. GET (30 s timeout, single
attempt, response capped at 5 MB) → `put_object` (`raw/feed=i95-live/...`) →
`put_metric_data` (`NovaToll/PollSuccess`, dimension `feed=i95-live`). Same
WAF-etiquette single-attempt policy as toll-fetcher even though this endpoint
isn't known to be blocked — it sits behind the same CDN/WAF class. Triggered
by the same `toll-poll-tick` EventBridge rule as toll-fetcher (`rate(10
minutes)`) rather than its own schedule — see "Secondary live source" above
for why. Async retry: `MaximumRetryAttempts = 0` — unlike VDOT's feeds, a
missed poll here costs nothing (no history to lose; the next tick
re-establishes "current"), so there's no reason to retry at all. Feeds into
`toll-loader` via the same `_FEED_CONFIG` dispatch as the other two feeds
(`parse_express_lanes.py` → `UPSERT_I95_LIVE_SQL`); no loader code needed a
new Lambda or new RDS IAM role.

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
separate min-config), all three Lambda functions + execution roles (least
privilege: fetcher = put_object on `raw/*`, SSM read, metrics; loader =
get_object, `rds-db:connect`, VPC ENI; express-fetcher = put_object scoped to
`raw/feed=i95-live/*` only, metrics — no SSM statement, no token to read),
loader `OnFailure` SQS queue, all three functions' event-invoke configs
(fetcher `MaximumRetryAttempts = 1`; express-fetcher `MaximumRetryAttempts =
0`; loader's OnFailure destination), one EventBridge rule (`rate(10
minutes)`) with two targets (fetcher and express-fetcher both fire on the
same tick — no second schedule to keep in sync) + permissions, S3 →
Lambda notification (prefix `raw/` — bucket-wide, so it covers all three
feeds including `i95-live` with no notification-config change), log metric
filters for `LoadSuccess`, S3 gateway endpoint in the default VPC,
RDS instance + subnet group + SGs, SSM SecureString params for the two VDOT
tokens (**values entered out-of-band via CLI, never in Terraform state** —
express-fetcher needs none, its source is unauthenticated), SNS topic +
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

**Network posture:** `publicly_accessible = false`. The security group
allows 5432 only from (a) the loader Lambda's SG and (b) a Tailscale subnet
router SG (`infra/tailscale.tf`) — a `t4g.nano` in the same default VPC that
bridges the tailnet to RDS. That one box gives GitHub Actions CI (via the
`nova-toll-github-ci` OIDC role and the `tailscale/github-action`, see
`.github/workflows/ci.yml`), the dev laptop, and Tailscale exit-node use on
public wifi a path in, without RDS ever being publicly addressable. Auth
key, ACL policy, and route approval are managed out-of-band in the
Tailscale admin console, same "seed a placeholder, set via CLI" spirit as
the SSM feed tokens above.

## Observability

SNS topic → email `bills@ryanprasad.ai`. The account budget alarm points at
the same topic. Alarms:

1. `toll-fetcher` Errors ≥ 1 (5-min period).
2. `toll-loader` Errors ≥ 1 (5-min period).
2b. `toll-express-fetcher` Errors ≥ 1 (5-min period). **Deliberately no
    freshness alarm for `i95-live`** (unlike #3 below, which is per-feed for
    `i95`/`i66` only) — a missed poll of this source costs nothing to catch
    up on next tick, so an Errors alarm alone is proportionate; a freshness
    alarm would just be more moving parts for a source where staleness isn't
    an incident.
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

### Table-split cutover (`trip_pricing` → `trip_pricing_i95`/`trip_pricing_i66`)

**Completed 2026-07-25** (commit `e90d981`). Migrated ~1.2M i95 rows + ~12.7k
i66 rows out of the shared `trip_pricing` table via `db/split_trip_pricing.sql`,
deployed the new loader, and verified it live. `trip_pricing` itself is
intentionally left in place per step 6 below, pending the soak-period rename.
No maintenance window was needed: the upsert was already idempotent, so a
two-pass backfill closed the gap instead. Sequence as run:

1. Create both new tables + grant `loader_writer` on them, in one transaction
   (tables without grants even briefly would 403 the next poll).
2. Backfill pass 1 (`INSERT ... SELECT ... ON CONFLICT DO NOTHING` per feed),
   run before the loader deploy — plain `SELECT` against `trip_pricing`, no
   lock contention with the still-running old loader.
3. Deploy the new loader zip (writes only to the two new tables from here).
4. Backfill pass 2 — re-run the identical block to sweep up any rows the old
   loader wrote between pass 1 and deploy.
5. Verify: row counts match per feed, freshness alarm stays green through a
   few poll cycles, spot-check rows.
6. `trip_pricing` is intentionally left in place (not renamed/dropped) so
   rollback is a plain redeploy of the old zip. Rename to
   `trip_pricing_legacy` after a soak period once the new tables are proven
   healthy; drop later still — both as separate one-shot files.

### Express Lanes live-source rollout

No backfill pass needed — `trip_pricing_i95_live` is a brand new table with
no prior data to migrate. Sequence:

1. Run `db/add_trip_pricing_i95_live.sql` against live RDS (creates the table
   + grants `loader_writer` in one transaction).
2. `./scripts/build_zips.sh`, then `terraform apply` with all three
   `*_package_path`/`*_handler` vars set — deploys `toll-express-fetcher` and
   the updated `toll-loader` zip (now including `parse_express_lanes.py`) together.
3. Confirm `trip_pricing_i95_live` gets rows within the first couple of
   10-minute poll cycles, and that at least one of the 16 known gap ids
   (1374–1389) appears.

## Cost

| Item | $/mo |
|---|---|
| RDS db.t4g.micro + 20 GB gp3 | ~15–17 |
| S3 (raw + state + requests) | <0.50 |
| Lambda (3 × ~4.4k invocations/mo) | <0.10 |
| SNS, CloudWatch, SSM | <0.50 |
| **Total** | **<$20** (budget alarm $25) |
