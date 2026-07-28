# Feed cadence & convergence

Status: done, one item outstanding · Owner: Ryan Prasad · 2026-07-28

Measured how often each price source updates and how far VDOT trails
Transurban. Closes the two "never rigorously confirmed" admissions in
`docs/poller-spec.md`'s "Secondary live source" and puts a number on
`docs/oracle-findings.md` §7's "10–20 minutes". Tool: `scripts/feed_cadence.py`.

## Headline: VDOT republishes Transurban's price, 10 minutes later

Comparing VDOT's capture at tick *t* against Transurban's at *t-10min*, over
250 shared od pairs: **100.0% of 59,217 comparisons identical to the cent**
(p90 |diff| $0.00). Every other offset sits at 30–36%. Holds on two disjoint
sub-ranges and hand-checked through prod RDS.

Not an artifact of flat prices: no shared od pair is flat (median 84 distinct
values each), and restricting to ticks where Transurban's price *changed* keeps
-10 min at **100.0% of 31,732** while +0 min falls to **0.0%**.

So cross-checking these two sources validates transport, not pricing. That
**retires** the proposed value-agreement test rather than unblocking it — a
real check needs a third source this repo has no access to.

## Cadence facts

| | measured |
|---|---|
| VDOT I-95 | new interval every 10 min, on the mark; `calculated_at` exactly 10 min prior |
| VDOT I-66 | every **6** min, real 6-min `interval_start_at` window, variable 1:52–3:47 lag |
| Transurban | changes every tick, 24/7 — 0 of 272 comparisons unchanged, median 185 of 347 od pairs |
| Transurban `time` | hourly, never advances mid-hour (0 counterexamples in 273 objects) |

The `#cache.max-age: 3600` the spec inferred an hourly refresh from is not in
the response at all; the origin sends `no-cache`, no ETag, no Age.

## Fixed

- [x] **I-95 tick pinned** to `cron(0/10)`. Applied 2026-07-28 11:43Z. VDOT's
      interval-*t* payload is ready at the boundary, so no offset stepping was
      needed. Fetch moved :03:32 → :00:40, capture staleness 13m32s → 10m40s;
      the residual 10 min is VDOT's own `calculated_at` lag.
- [x] **I-66 given its own `cron(0/6)` rule.** We were storing ~6 of every 10
      intervals. Fires 11:48:36, 11:54:32, 12:00:37, 12:06:36, 12:12:32 —
      phase-stable across the hour boundary, uniform 6-min spacing with zero
      misses, against a 12-min gap in the same window the previous day. The
      historical gap is permanent; the fetcher never fetched those snapshots.
- [x] **`trip_pricing_i95_live` re-keyed on `captured_at`** (schema 4.0.0),
      the tick from each raw object's own S3 key. Was keyed on the hourly
      `observed_at`, so each hour's six captures overwrote one another — 59
      stored snapshots for ~59 hours where 284 were captured. Forward-only:
      the pre-migration period stays an hourly sample, though the raw payloads
      remain in S3.
      Rollout is `db/add_captured_at_to_i95_live.sql` then the loader deploy,
      back to back — the window between is a hard failure, since the deployed
      loader's `ON CONFLICT` names the old key and no ordering satisfies both.
      Sequence in `docs/poller-spec.md`.

## Outstanding

- [ ] Run `feed_cadence.py watch --duration 360` to pin Transurban's
      sub-10-minute cadence. A 4-minute smoke run showed 8 identical responses
      — consistent with 10 minutes, far short of proving it. ~360 requests to a
      third party, so it's a deliberate decision, not a default.
