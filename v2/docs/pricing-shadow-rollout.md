# Pricing shadow rollout

This rollout is additive. V1 keeps its `public` tables and existing analysis
surfaces, direct S3 notification, loader, roles, and Terraform state. Those
public analysis objects are deliberate compatibility surfaces until v1 is
retired. V2 owns only the `pricing` schema and its separate loader
infrastructure.

```text
VDOT -> v1 fetcher -> S3 raw object
                         |-- direct notification -> v1 loader -> public.*
                         `-- EventBridge --------> v2 loader -> pricing.*
```

## 1. Prepare the database manually

Use the admin connection through Tailscale with TLS verification. For a new
database, review the bootstrap transaction first, then run:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/001_create_pricing_schema.sql
```

Confirm the two target tables are empty. Do not run the backfill yet.

For an existing pricing `1.0.0` database, run the guarded, rerunnable upgrade
instead:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql
```

Then upgrade pricing `1.0.1` to `1.1.0`:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/006_upgrade_pricing_1_0_1_to_1_1_0.sql
```

Then preserve exceptional I-95 schedule diagnostics in pricing `1.1.1`:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/014_upgrade_pricing_1_1_0_to_1_1_1.sql
```

Every future pricing version bump must add its matching numbered upgrade
migration in the same pull request; CI rejects a bump without one and rejects
later edits to released migrations.

After either path, confirm `pricing.schema_version` is exactly `1.1.1` and
`pricing_loader_writer` has only `SELECT`, `INSERT`, and `UPDATE` on the two
target tables.

## 2. Deploy the shadow path

Merge to `main` only after database preparation. CI applies v1 first to enable
S3 EventBridge delivery while retaining the v1 notification. It then connects
as `pricing_reader`, refuses deployment unless pricing 1.1.1 and the writer
grants exist, and applies the isolated `v2/infra` state.

Verify the EventBridge rule and Lambda are enabled, both failure queues are
empty, and new I-95 and I-66 objects produce `V2_LOAD_OBJECT_OK` logs. Compare
new rows across `public` and `pricing`, excluding only `ingested_at` because
each loader stamps it independently.

The loader batches each object and updates an existing interval only when its
`(calculated_at, s3_key)` revision is newer. `V2_LOAD_ROWS` reports the number
of changed rows; `V2_LOAD_OK` and `V2_LOAD_OBJECT_OK` still mark every
successful commit, including an idempotent replay.

## 3. Backfill and prove parity

With the shadow loader still running, execute the idempotent backfill:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/backfill.sql
```

The script copies each feed in its own repeatable-read transaction, upserts on
the production keys, verifies bidirectional row equality, records completion,
and runs a final parity check. It never replaces a newer `pricing` revision
with an older `public` row. If live delivery makes `pricing` temporarily newer,
the parity check rolls back that feed; wait for v1 to catch up and rerun.

## Monitoring

`toll-v2-pricing-loader-errors`, the invoke-failure queue alarm, and the
EventBridge delivery-failure queue alarm cover explicit failures. The
`toll-v2-pricing-freshness-i95` and `toll-v2-pricing-freshness-i66` alarms use
the `NovaToll/V2LoadSuccess` metric derived from `V2_LOAD_OK` and alert through
`nova-toll-alerts` when a feed has no successful v2 load for 30 minutes.

For a freshness alarm, inspect the v2 loader log and both failure queues, then
confirm the matching v1 feed is still loading before replaying any object. Keep
serving the last known good pricing rows while the pipeline is repaired.

## Roll back or clean up

Operational rollback is non-destructive: disable the v2 EventBridge rule and
deploy or remove the v2 Lambda. V1 continues unchanged.

Dropping `pricing` is a separate cleanup after the shadow data is no longer
needed. Disable the rule first, verify parity, and pass the explicit guard:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -v drop_pricing_confirmed=yes \
  -f v2/db/migrations/001_create_pricing_schema.rollback.sql
```
