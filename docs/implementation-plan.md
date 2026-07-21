# VDOT Toll Poller — Implementation Plan

Status: ready to execute · Companion to [poller-spec.md](poller-spec.md) ·
Last updated: 2026-07-21

How to build the poller with an **orchestrator** session dispatching
**parallel subagents**. The spec is the single source of truth for every
design decision; this document only sequences the work. Subagents never edit
the spec — contract questions go back to the orchestrator, which either
answers from the spec or escalates to Ryan.

## Ground rules

- **Contracts are frozen in the spec** and consumed read-only by every WP:
  S3 key layout (§S3 layout), metric namespace and names
  (`NovaToll/PollSuccess` emitted by the fetcher, `NovaToll/LoadSuccess` via
  log metric filter, dimension `feed`), DDL and upsert key (§Database
  schema), the IAM-auth + `verify-full` connection recipe (§Lambda details),
  and WAF etiquette (§Data sources: one attempt per feed per tick, never a
  retry loop).
- **Env var names** (WP1 sets them, WP2/WP3 consume them):
  fetcher — `I95_TOKEN_PARAM`, `I66_TOKEN_PARAM`, `RAW_BUCKET`;
  loader — `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`.
- Each WP owns a **disjoint file set**; subagents stay inside theirs.
- Python 3.13 both Lambdas; fetcher is stdlib+boto3 only; loader adds only
  pinned, hash-verified `psycopg[binary]`.
- Account hygiene (one-time, human, before WP4): root MFA on nova-toll-prod;
  short-lived creds (SSO) for the `nova-toll` profile — that profile can read
  every secret in the account.

## Dependency graph

```
WP1 (Terraform)  ─┐
WP2 (fetcher)    ─┼──► WP4 (package, apply*, smoke) ──► WP5 (backfill, cutover*)
WP3 (loader+DDL) ─┘         *human gates
```

WP1–3 run as parallel subagents. WP4–5 are sequential, orchestrator-driven.

## Work packages

### WP1 — Terraform root module

- **Files:** `infra/` (single root module; no submodules until a second
  environment exists).
- **Scope:** every resource in spec §Terraform, §RDS, §Observability, plus
  Lambda function definitions with placeholder zips. Home IP and tokens'
  parameter names as variables; token *values* never appear (entered
  out-of-band per spec). Provider `default_tags` uses lowercase
  `project = nova-toll-budget-agent` — matches the already-activated cost
  allocation tag key (case-sensitive; see spec §Terraform).
- **Done when:** `terraform fmt -check`, `terraform validate`, and
  `terraform plan` against an empty state produce a clean plan containing
  every spec resource. **No apply** — that is WP4's human gate.

### WP2 — Fetcher Lambda

- **Files:** `lambdas/fetcher/` (`handler.py`, `tests/`).
- **Scope:** spec §Lambda details (toll-fetcher). Per-feed isolation, 30 s
  timeout, single attempt, 5 MB read cap, token scrubbing on every error
  path, `PollSuccess` metric, S3 key layout from §S3 layout.
- **Done when:** `pytest` passes with stubbed urllib/boto3 covering: one feed
  failing doesn't block the other's PUT; the token never appears in any log
  line or raised exception text (assert on captured logs); key format matches
  the spec examples exactly.

### WP3 — Loader Lambda + schema

- **Files:** `lambdas/loader/` (`handler.py`, `parse_csv.py`,
  `parse_xml.py`, `tests/`), `db/schema.sql`, `db/roles.sql`.
- **Scope:** port `normalize.py` and the upsert from
  `~/hermes-agent/tools/va_toll_ingest/va_toll_ingest/` (adapting to the
  zone-based upsert key), new ElementTree XML parser, IAM-auth +
  `verify-full` connection, space-delimited `LOAD_OK <feed>` post-commit log
  line (metric-filter dimensions require JSON or space-delimited patterns).
  `schema.sql` = spec DDL verbatim; `roles.sql` = `loader_writer` with
  `GRANT rds_iam` and no password.
- **Done when:** `pytest` parses both files in `vdot_sample_data/` completely
  (317 CSV rows, 44 XML rows) and covers every quirk in spec §Data sources:
  header typo matched exactly (drift fails loudly), dash/blank rows, blank
  `STARTZONENAME`, corridor 952 stored as-is, CLOSED-with-rate and
  open-with-$0 rows, DST `fold=0`. DB layer tested against the upsert SQL
  text (no live DB needed pre-deploy).

### WP4 — Package, deploy, smoke *(human gate)*

- **Files:** `scripts/build_zips.sh`, `scripts/smoke.sh`.
- **Scope:** reproducible zip builds (loader with hashed `psycopg` + RDS CA
  bundle), then **stop and hand Ryan the plan output for `terraform
  apply`**. Post-apply: apply `schema.sql`/`roles.sql` as master, enter
  token values out-of-band, send the SNS test message.
- **Done when:** one full tick traces end-to-end — EventBridge fire → two
  objects in `raw/` → `LOAD_OK` in loader logs → rows in Postgres →
  `LoadSuccess` visible in CloudWatch → all five alarms in OK, SNS email
  confirmed received.

### WP5 — Backfill + cutover *(human gate)*

- **Files:** `scripts/backfill.py`, `scripts/verify_overlap.sql`.
- **Scope:** one-time merge of the ~1.02M-row local archive per spec
  §Migration (idempotent upsert; `s3_key='backfill/local-archive'`), overlap
  verification queries, then walk spec §Migration steps 4–6. Disabling the
  home cron is Ryan's call — the orchestrator presents the overlap evidence
  and stops.
- **Done when:** ≥1-week overlap shows matching row counts and spot-checked
  rates; cron disabled; budget alarm raised to $25.

## Orchestrator runbook

1. Dispatch WP1, WP2, WP3 as three parallel subagents, each prompt carrying:
   its WP section, the ground rules, and a pointer to the spec. Worktree
   isolation optional — file sets are disjoint.
2. On completion, run each WP's verification yourself before accepting it;
   subagent claims are not done-criteria.
3. Commit per WP after verification.
4. Run WP4 and WP5 in the main session — both contain human gates
   (`terraform apply`, cron disable) where the orchestrator stops and asks.
5. Anything a subagent wants to change in the spec is a finding, not an
   edit — bring it back to Ryan.
