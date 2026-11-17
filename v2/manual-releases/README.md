# Manual production releases

This directory contains the operator instructions, recovery-capture script, and
[fixed production role bootstrap](bootstrap_production_eval_writer.sql).
Production deployment follows the [guarded release flow](../RUNBOOK.md#guarded-production-release).

## 1. Choose the candidate

Choose the exact commit on `main` whose CI and development delivery succeeded.
Confirm its retained release bundle, readiness, and canary evidence are available.
Choose a new stable `vX.Y.Z` tag pointing to that commit.

## 2. Check schemas before publishing

On the exact candidate checkout, run the credential-free source preflight:

```bash
(cd v2 && TOLLCHAT_PRODUCTION_PREFLIGHT=1 uv run pytest -q tests/test_development_migrations.py \
  -k 'production_migration_gate_matches_cap or production_release_schema_preflight')
```

This checks the migration scripts' release-manifest checksums, compares the
canonical schema versions to the production migration cap, and
executes the wrapper's schema gate with those versions. It also verifies that
unapproved future migrations and mismatched schema versions are rejected. A green
development deployment alone does not establish production schema readiness.
Require both selected tests to pass; a skipped readiness test is not approval.
Ordinary CI checks the production wrapper against the approved migration cap,
but skips canonical-versus-production equality so development can advance first.

Confirm all of the following before creating the release:

- The development release evidence's declared and installed schema versions match
  the candidate's canonical versions and the production preflight.
- Every pending migration has been reviewed for backward compatibility and is
  within `PRODUCTION_MAX_MIGRATION_NUMBER`. Do not raise the cap automatically.
- The installed production versions have a registered upgrade path to the
  candidate. Use the existing verified production TLS connection for this
  read-only query; the source preflight does not connect to production:

  ```sql
  SELECT 'pricing' AS schema_name, version FROM pricing.schema_version WHERE singleton
  UNION ALL
  SELECT 'oracle', version FROM oracle.schema_version WHERE singleton;
  SELECT to_regrole('eval_writer') IS NOT NULL AS evaluation_writer_exists;
  ```

Production advances through `PRODUCTION_MAX_MIGRATION_NUMBER` in
`v2/scripts/run_development_migrations.py`, to the versions
`v2/scripts/run_production_migrations_workflow.sh` expects. Migration 034 updates 24 route labels and aliases while
preserving route connections and all other point fields. Migration 035 advances the
production version without changing data or permissions;
its catalog-reader grants apply only in development. Migration 033 adds
`pricing.evaluation_runs` and its writer permissions. Complete and verify the [fixed production writer prerequisite](#fixed-production-role-prerequisite)
before publishing. A missing writer causes the migration transaction to roll back.
Do not run migration 033 manually or use the administrator to bypass the protected
migration workflow.

Stop if any check fails. Correct the source through a reviewed PR, complete
its development delivery, then choose the new verified commit for release.

## 3. Publish and review preparation

Confirm the separately reviewed production blue-green bootstrap is complete and
`PRODUCTION_BLUE_GREEN_BOOTSTRAPPED` is enabled. Publish a stable GitHub Release
with the chosen tag pointing to the exact verified commit, not a draft or prerelease.

Wait for `v2-production-plan` to verify the candidate and save its preparation
plan. Require a zero-change foundation plan and review every application action.
Stop on unexplained actions or replacements. The saved plan is valid for 24 hours.
Approve the protected `production` job only after reviewing it. Automation
revalidates the release, runs fixed compatible migrations, applies that exact
plan to the inactive slot, and validates the candidate. Ordinary traffic stays
on the active slot.

## 4. Approve cutover and observe

Inspect the preparation evidence and test the candidate using the
[blue-green procedure](../runbooks/blue-green-deployments.md#production-cutover-approval).
Approve the separate `production-cutover` gate only when the candidate is ready.
The resumed protected job may also require `production` approval. It revalidates
the prepared record and state, runs fresh checks, and gates a new routing-only
plan before switching traffic; it does not rerun migrations or preparation.

Confirm post-cutover observation and final release evidence report success.
Delivery retains the previous slot and a private, versioned recovery record.
The legacy local capture below is not required for blue-green releases.

## 5. If delivery fails

A candidate validation failure blocks promotion and leaves ordinary traffic
unchanged. During post-cutover observation, two consecutive failures trigger
one routing restoration attempt. Recovery success does not turn deployment
failure into success.

After the observation window, cancellation, or runner loss, follow the
[protected recovery procedure](../runbooks/blue-green-deployments.md).
Dispatch `v2-production-recovery.yml` from `main` with the original numeric
`claim_id`, exact private recovery `record_version`, and reviewed
`expected_state_sha256`; approve its protected `production` environment.

## Fixed production role prerequisite

This is a separate, human-reviewed administrator bootstrap before publishing the
release. Verify AWS account `920534282028`, the fixed `nova-toll-db` instance,
`nova_toll` database, and the existing TLS-verified administrator connection.
Do not run development bootstrap SQL here or give CREATEROLE to the migrator.

Run the checked-in [fixed role bootstrap](bootstrap_production_eval_writer.sql)
from the repository root using that administrator connection. Set `PGHOST` to
the verified production endpoint, `PGPORT=5432`, and `PGSSLROOTCERT` to the pinned
RDS CA bundle. Obtain the administrator credential through the existing managed
secret path; keep it in process memory and never put it in a command or file.

```bash
PGDATABASE=nova_toll PGUSER=nova_toll_admin PGSSLMODE=verify-full \
  psql -X --set ON_ERROR_STOP=1 --file v2/manual-releases/bootstrap_production_eval_writer.sql
```

The SQL checks the database name/comment and both administrator identities before
creating the fixed role, then checks its attributes and membership before commit.
It runs as one transaction and refuses an existing role. A failed command must
stop release preparation; verify read-only state before any retry.

If the role already exists, stop and inspect its attributes and memberships;
do not silently reuse or replace an unknown role. Verify LOGIN, NOINHERIT,
NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS, the production
comment, `rds_iam` membership only, and CONNECT on `nova_toll`. This bootstrap
creates no application tables and runs no schema migration. Migration 033 grants
only schema usage and SELECT/INSERT/UPDATE on `pricing.evaluation_runs` through
the protected release workflow.
