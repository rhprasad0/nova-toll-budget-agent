# Feed cadence & convergence — task checklist

Status: in progress · Owner: Ryan Prasad · Started 2026-07-28

Measures how often each price source actually updates, and how long VDOT's
published price takes to converge on Transurban's live one. Closes the two
"never rigorously confirmed" admissions in `docs/poller-spec.md`'s "Secondary
live source" section and puts a measured number on `docs/oracle-findings.md`
§7's loose "10–20 minutes".

Plan of record: `~/.claude/plans/glowing-wandering-lightning.md`.

## Findings established while scoping (2026-07-28)

Measured over retained raw S3 objects in `nova-toll-raw-920534282028` — 273
`i95-live` objects (07-25 → 07-28) and 208 `i95` objects (07-27 → 07-28) — plus
prod RDS. No new requests to either source.

- VDOT publishes a new interval every 10 min, on the mark: 207/207 consecutive
  objects carry a distinct `interval_end_at`, and 208/208 match their own tick
  bucket exactly.
- `calculated_at` is exactly 10 min before `interval_end_at` (min = max = avg =
  10.0 over 7 days in RDS).
- Our own poll lands at ~`HH:M3:31`, 3m31s after each 10-minute boundary
  (`rate(10 minutes)` floats free of the wall clock).
- Therefore a VDOT price is **13.5 min stale at capture**, ageing to 23.5 min
  before the next tick replaces it.
- Transurban's payload changes **every tick, around the clock**: 0 of 272
  tick-to-tick comparisons showed zero change; median 185 of 347 od pairs change
  per tick; the quietest hour (06Z ≈ 02:00 ET) still medians 92.
- Transurban's `time` field is hourly and never advances mid-hour (0
  counterexamples in 273 objects).

**The `#cache.max-age: 3600` inference in the spec is wrong** — the data moves
every 10 minutes while its label stays pinned to the hour.

### Consequence: `trip_pricing_i95_live` discards 5 of every 6 polls

`UPSERT_I95_LIVE_SQL` keys on `(observed_at, od_pair_id)` with
`DO UPDATE SET price_usd = EXCLUDED.price_usd`. Hourly `observed_at` + data that
changes every 10 min = each hour's six polls overwrite one another, last writer
wins. Confirmed in prod: 59 stored snapshots across ~59 hours of coverage.

Nothing is lost permanently — every raw payload is retained in S3 (no lifecycle
expiry) — but the table is not the record it claims to be. Fix is deferred to
the follow-up section below, by decision, not oversight.

## Tasks

- [ ] 1. `scripts/feed_cadence.py archive` — per-tick change counts by UTC hour,
      VDOT interval-integrity check, and the convergence-lag search over the
      shared od pairs. Reuses `lambdas/loader/parse_csv.py` and
      `parse_express_lanes.py`; no reimplementation of either format.
- [ ] 2. `scripts/feed_cadence.py watch` — bounded 60s poll of Transurban's
      unauthenticated endpoint with `If-None-Match`, to resolve the sub-10-minute
      cadence the archive's 10-min floor cannot see.
- [ ] 3. Pin the EventBridge tick (`infra/triggers.tf`: `rate(10 minutes)` →
      `cron(0/10 * * * ? *)`) and re-read the archive to find where inside the
      3.5-minute window VDOT's publish actually lands. Step the offset up only if
      the label lags. Leave it pinned at the winning offset — never back to
      `rate()`.
- [ ] 4. Write up: `docs/oracle-findings.md` §9, corrections to
      `docs/poller-spec.md`, `lambdas/express_fetcher/handler.py` and
      `lambdas/loader/parse_express_lanes.py` docstrings.

## Follow-up (not this task file's scope)

- [ ] Preserve every live poll: add the fetcher's own wall clock to
      `trip_pricing_i95_live`'s key so the six polls per hour stop overwriting
      each other, leaving the source's `time` field's meaning untouched.
      Backfill from the retained raw objects.
- [ ] Value-agreement test (VDOT stored vs Transurban live as pass/fail). Blocked
      on task 1's convergence-lag output — §7 explains why a tolerance set
      without it would be a guess.
