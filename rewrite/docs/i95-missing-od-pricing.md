# Modeled pricing for missing I-95/495 OD IDs

## The data gap

The I-95 route oracle contains 330 distinct origin-destination identifiers,
but VDOT history contains prices for only 314 of them. The missing 16 IDs are
`1374` through `1389`. They occur on 107 of the oracle's 685 routes, chiefly
when a trip crosses from the I-495 Express Lanes onto I-95/395.

The affected routes can begin at the 495 Express Lanes start/George Washington
Memorial Parkway, Route 267, Jones Branch Drive, Westpark Drive, Route 7,
I-66, Lee Highway, or Braddock Road. IDs `1375` through `1377` occur only from
Braddock Road. VDOT has never emitted any of these 16 OD IDs, so widening the
historical lookup window cannot recover their prices.

**Live I-95 pricing is not being retired.** `trip_pricing_i95` remains the
official VDOT source. Retained Transurban rows are inert historical evidence
and are not restored or queried by the rewrite database.

## Proxy model

Each missing OD ID maps to the VDOT-priced OD product that matched it most
closely in the retained Transurban overlap:

| Missing OD | VDOT proxy | Required direction | Destination label |
| ---: | ---: | --- | --- |
| 1374 | 1146 | Northbound | I-395 Near Edsall Road |
| 1375 | 1263 | Northbound | Seminary Road |
| 1376 | 1264 | Northbound | Pentagon/Eads Street |
| 1377 | 1265 | Northbound | Washington D.C. |
| 1378 | 1158 | Southbound | Old Keene Mill Road/Route 644 |
| 1379 | 1159 | Southbound | I-95 Near Backlick Road |
| 1380 | 1160 | Southbound | Franconia-Springfield Parkway/Route 289 |
| 1381 | 1161 | Southbound | US-1 |
| 1382 | 1162 | Southbound | Gordon Boulevard/Route 123 |
| 1383 | 1163 | Southbound | Prince William Parkway/Route 294 |
| 1384 | 1164 | Southbound | I-95 Near Dale Boulevard |
| 1385 | 1165 | Southbound | I-95 Near Dumfries Road/Route 234 |
| 1386 | 1166 | Southbound | I-95 Near Joplin Road/Quantico |
| 1387 | 1167 | Southbound | I-95 Near Garrisonville Road/Route 610 |
| 1388 | 1288 | Southbound | I-95 Near Route 17 |
| 1389 | 1315 | Southbound | Courthouse Road/Route 630 |

The database exposes three related views:

- `i95_modeled_od_proxy` is the auditable mapping above.
- `modeled_trip_pricing_i95` preserves every historical proxy observation but
  returns a null modeled price when the required direction is not fully open.
  Rolling analysis must select the latest row in each time slot before checking
  that the price is present; this prevents fallback to an older open toll.
- `modeled_current_trip_pricing_i95` evaluates the latest VDOT proxy row and
  returns nothing when that row is not fully open. It never falls back to an
  older open price during a direction reversal.

Both pricing views copy the proxy price without adjustment and disclose the
target OD ID, proxy OD ID, source timestamps, link status, `modeled = true`,
and `pricing_method = 'identity_proxy_v1'`. They do not insert synthetic rows
into VDOT history or present estimates as observed prices.

## Validation

The validation set contains 578 retained Transurban captures from July 25–30,
2026. Captures were paired with VDOT's corresponding ten-minute interval,
filtered to the open travel direction, and split chronologically: the first
70% selected the model and the final 30% evaluated it.

Across 1,200 holdout comparisons, copying the proxy price produced:

| Measure | Result |
| --- | ---: |
| Mean absolute error | **$0.106** |
| Comparisons within $0.50 | **96.1%** |
| 95th-percentile absolute error | **$0.00** |
| Maximum absolute error | **$8.05** |

PostgreSQL's `regr_slope`, `regr_intercept`, `regr_r2`, `corr`, and
`percentile_cont` functions were evaluated for calibration and diagnostics.
Ordinary least-squares regression increased holdout mean absolute error to
$0.154 because rare discrepancies pulled the fitted line away from the usual
exact match. Median bias correction selected a $0 adjustment for every
mapping. Statistical aggregates therefore remain an audit tool rather than
part of the production formula.

The result is a **ballpark estimate**, not an operator quote. The five-day
overlap is too short to establish seasonal accuracy, and rare errors were much
larger than the typical zero difference. Callers must preserve the modeled
label and return no estimate when the appropriate view has no row.

## Deferred quantitative objections

An adversarial quantitative review considers this evidence preliminary rather
than independent validation. The identity proxy may remain available as a
provisional ballpark model, but the following objections must be revisited
before making stronger accuracy claims or presenting its output publicly:

- The pooled results can hide a weak OD mapping or traffic regime. Based on the
  rounded holdout rate, about 47 of 1,200 comparisons exceeded $0.50, and the
  $8.05 maximum error is large relative to the $0.106 MAE. Publish per-OD
  sample counts, unique intervals, exact-match rate, signed bias, MAE, RMSE,
  p95, p99, maximum error, and direction/rush-hour strata.
- The comparison rows are clustered within 578 captures over five days, so
  1,200 rows are not 1,200 independent observations. Record the exact split
  timestamp, unique holdout intervals, duplicate-capture handling, and confirm
  that proxy selection used only the training period.
- VDOT republishes the Transurban price series about ten minutes later for
  shared OD IDs; the feeds are not independent evidence. Preserve the pairing
  query and a non-secret input manifest, including the clock shift and S3
  `LastModified` alignment, so the analysis can be reproduced.
- The committed restore contract verifies the mapping constants and SQL
  behavior, not the empirical quality of each mapping. Retain a runnable
  analysis and its per-OD output before calling every mapping validated.
- The [historical pricing contract](historical-pricing-mvp-contract.md) cannot
  yet encode modeled provenance losslessly. Add a modeled source kind plus
  `pricing_method` and `proxy_od_pair_id` per component before consuming these
  estimates through that interface.
- Rejecting pooled ordinary least squares is reasonable, but each mapping
  still needs comparison against identity, mean/median-offset, and simple
  destination-matched baselines.

These are deliberately deferred validation tasks, not evidence that the proxy
model is wrong. Until they are resolved, **provisional ballpark estimate** is
the strongest supported description.

## Restore and query

On an empty AWS RDS PostgreSQL 17 database, apply the schema before the roles:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 -f rewrite/db/schema.sql
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 -f rewrite/db/roles.sql
```

These scripts restore database shape and permissions only. Historical VDOT
rows must be replayed separately from retained raw objects.

```sql
SELECT
    od_pair_id,
    zone_toll_rate_usd,
    interval_end_at,
    proxy_od_pair_id,
    pricing_method
FROM modeled_current_trip_pricing_i95
WHERE od_pair_id = 1385;
```
