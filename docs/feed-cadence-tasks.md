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

- [x] 1. `scripts/feed_cadence.py archive` — per-tick change counts by UTC hour,
      fetch-offset-by-day, VDOT interval-integrity check, and the convergence-lag
      search over the shared od pairs. Reuses `lambdas/loader/parse_csv.py` and
      `parse_express_lanes.py`; no reimplementation of either format.
- [x] 2. `scripts/feed_cadence.py watch` — bounded 60s poll of Transurban's
      unauthenticated endpoint, to resolve the sub-10-minute cadence the
      archive's 10-min floor cannot see. **Still needs a long run**: a 4-minute
      smoke run at 30s showed 8 identical responses, consistent with a
      10-minute cadence but far short of proving it. Run
      `feed_cadence.py watch --duration 360` and read the inter-change gaps.
- [x] 3. Pinned the EventBridge tick (`infra/triggers.tf`: `rate(10 minutes)` →
      `cron(0/10 * * * ? *)`). **Applies on merge to main**, then needs ≥24h
      before re-reading. If `feed_cadence.py archive` then reports interval/tick
      mismatches, VDOT's publish lands after the boundary — step to
      `cron(1/10 ...)`, `cron(2/10 ...)` to find it. Leave it pinned at the
      winning offset, never back to `rate()`.
- [x] 4. Write up: `docs/oracle-findings.md` §9, corrections to
      `docs/poller-spec.md`, `lambdas/express_fetcher/handler.py` and
      `lambdas/loader/parse_express_lanes.py` docstrings.

## The headline result

**VDOT does not publish an independent price. It republishes Transurban's, ten
minutes later.** Comparing VDOT's capture at tick *t* against Transurban's at
*t-10min*, over 250 shared od pairs: **100.0% of 59,217 comparisons identical
to the cent** (p90 |diff| $0.00). Every other offset sits at 30-36% exact match
with a p90 of $1.15-$2.90. The same answer holds on two disjoint date
sub-ranges, and was hand-checked through prod RDS.

Stress-tested against the "prices just don't move much" objection: no shared od
pair is flat (median 84 distinct values each), and restricting to only the
`(od, tick)` cases where Transurban's price changed at that tick keeps -10 min
at **100.0% of 31,732** while +0 min falls to **0.0% of 31,939**. VDOT never
matches the concurrent capture in the moment a price moves, and always matches
the one ten minutes prior.

Consequence for `tests/test_expresslanes_crosscheck.py`: cross-checking these
two sources validates transport, not pricing. Once aligned they agree by
construction, so a value-agreement tolerance between *these two* would measure
the delay and nothing else. That retires the follow-up below rather than
unblocking it.

## Found 2026-07-28 while checking vai66tolls.com: we under-sample I-66

`trip_pricing_i66` is not on the same cadence as `trip_pricing_i95` and never
was. Measured over the last 2 days in prod:

- `interval_end_at` spacing is **6 minutes** (345 gaps), not 10.
- `interval_end_at - interval_start_at` is a real 6-minute window (I-95 carries
  no `interval_start_at` at all).
- `calculated_at` trails by a *variable* 1:52-3:47, not I-95's fixed 10:00.

Our EventBridge tick polls every 10 minutes, so each poll captures whichever
single snapshot is current and the rest are never seen: 53 of the observed gaps
are 12 minutes, i.e. an interval published and missed. We are storing roughly
6 of every 10 I-66 intervals. Not a loss of anything already captured, and not
a correctness bug in what is stored -- but `trip_pricing_i66` is a sample of
the I-66 series, not the series.

- [x] **Fixed 2026-07-28**: I-66 now has its own `toll-poll-tick-i66` rule at
      `cron(0/6 * * * ? *)`. Each rule names its feed in the target input, and
      `FEEDS[feed]["tick_minutes"]` sets both the poll cadence and the S3 key's
      bucket width so two polls of one feed can't overwrite each other. The
      historical gap stays permanent -- the fetcher never fetched those
      snapshots, so there is nothing to backfill from.
      **Verify after merge**: `raw/feed=i66/` should show 10 objects per hour
      on 6-minute keys (…0000Z, 0006Z, 0012Z), and consecutive
      `interval_end_at` values in `trip_pricing_i66` should be 6 minutes apart
      with no 12-minute gaps.

## Follow-up (not this task file's scope)

- [ ] Preserve every live poll: add the fetcher's own wall clock to
      `trip_pricing_i95_live`'s key so the six polls per hour stop overwriting
      each other, leaving the source's `time` field's meaning untouched.
      Backfill from the retained raw objects.
- [x] ~~Value-agreement test (VDOT stored vs Transurban live as pass/fail).~~
      **Dropped, not deferred**: task 1 showed the two sources are one series
      published twice, so a tolerance between them would assert the 10-minute
      delay, not price correctness. A genuine value check needs a third source
      (a driver-facing quote or a billed statement), which this repo has no
      access to. `test_overlap_price_sanity` correctly stays a `>= 0` check.
