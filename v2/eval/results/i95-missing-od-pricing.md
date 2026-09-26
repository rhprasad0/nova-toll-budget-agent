# Modeled pricing for missing I-95/495 OD IDs

`identity_proxy_v1` supplies provisional ballpark prices for missing I-95/I-495
OD IDs 1374–1389. Live pricing still uses `pricing.trip_pricing_i95` from VDOT.
Retained Transurban rows are historical evidence and are not restored or queried
by the rewrite database.

The [experiment journal](../EXPERIMENT_JOURNAL.md#i-95i-495-identity-proxy-validation)
records the data gap, historical validation, measured error and unresolved limits.

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

- `pricing.i95_modeled_od_proxy` is the auditable mapping above.
- `pricing.modeled_trip_pricing_i95` preserves every historical proxy observation but
  returns a null modeled price when the required direction is not fully open.
  Rolling analysis must select the latest row in each time slot before checking
  that the price is present; this prevents fallback to an older open toll.
- `pricing.modeled_current_trip_pricing_i95` evaluates the latest VDOT proxy row and
  returns nothing when that row is not fully open. It never falls back to an
  older open price during a direction reversal.

Both pricing views copy the proxy price without adjustment and disclose the
target OD ID, proxy OD ID, source timestamps, link status, `modeled = true`,
and `pricing_method = 'identity_proxy_v1'`. They do not insert synthetic rows
into VDOT history or present estimates as observed prices.

Treat each modeled price as a **provisional ballpark estimate**. Callers must
preserve the modeled label and return no estimate when the appropriate view has
no row. The historical study does not establish seasonal accuracy or independently
validate every mapping; its limitations are recorded in the journal above.

## Restore and query

On an empty AWS RDS PostgreSQL 17 database, apply the schema before the roles:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 -f v2/db/schema.sql
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 -f v2/db/roles.sql
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
FROM pricing.modeled_current_trip_pricing_i95
WHERE od_pair_id = 1385;
```
