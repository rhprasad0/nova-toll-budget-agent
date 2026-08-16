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

Use the admin connection through Tailscale with TLS verification. Review the
transaction first, then run:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/001_create_pricing_schema.sql
```

Confirm `pricing.schema_version` is exactly `1.0.0`, the two target tables are
empty, and `pricing_loader_writer` has only `SELECT`, `INSERT`, and `UPDATE` on
those tables. Do not run the backfill yet.

## 2. Deploy the shadow path

Merge to `main` only after database preparation. CI applies v1 first to enable
S3 EventBridge delivery while retaining the v1 notification. It then connects
as `pricing_reader`, refuses deployment unless pricing 1.0.0 and the writer
grants exist, and applies the isolated `v2/infra` state.

Verify the EventBridge rule and Lambda are enabled, both failure queues are
empty, and new I-95 and I-66 objects produce `V2_LOAD_OBJECT_OK` logs. Compare
new rows across `public` and `pricing`, excluding only `ingested_at` because
each loader stamps it independently.

## 3. Backfill and prove parity

With the shadow loader still running, execute the idempotent backfill:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/backfill.sql
```

The script copies each feed in its own repeatable-read transaction, upserts on
the production keys, verifies bidirectional row equality, records completion,
and runs a final parity check. It can be rerun safely if live arrivals briefly
race the snapshot.

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
