# Manual production releases

This directory contains the operator instructions and recovery-capture script.
Production deployment follows the [guarded release flow](../RUNBOOK.md#guarded-production-release).

## 1. Choose the candidate

Choose the exact commit on `main` whose CI and development delivery succeeded.
Confirm its retained release bundle, readiness, and canary evidence are available.
Choose a new stable `vX.Y.Z` tag pointing to that commit.

## 2. Check schemas before publishing

On the exact candidate checkout, run the credential-free source preflight:

```bash
(cd v2 && uv run pytest -q tests/test_development_migrations.py -k production_release_schema_preflight)
```

This checks the migration scripts' release-manifest checksums, compares the
canonical schema versions to the production migration cap, and
executes the wrapper's schema gate with those versions. It also verifies that
unapproved future migrations and mismatched schema versions are rejected. A green
development deployment alone does not establish production schema readiness.

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

For this release, production advances through **033**, targeting pricing **1.4.0**
and Oracle **1.15.0**. Migration 033 adds `pricing.evaluation_runs` and its writer
permissions. Complete and verify the [fixed production writer prerequisite](../runbooks/eval-dashboard.md#fixed-production-role-prerequisite)
before publishing. A missing writer causes the migration transaction to roll back.
Do not run migration 033 manually or use the administrator to bypass the protected
migration workflow.

Stop if any check fails. Correct the source through a reviewed PR, complete
its development delivery, then choose the new verified commit for release.

## 3. Capture the current production routing

Requirements: Bash, AWS CLI, `jq`, Python 3, and an authenticated
`nova-toll-prod` profile for account `920534282028`. The script uses `us-east-1`.

Run the following from the repository root (the worktree root while these changes
are unmerged). Replace the example tag with the intended release tag:

```bash
release_tag='v1.0.12'
mkdir -p -m 700 "$HOME/tollchat-releases"
RELEASE_EVIDENCE="$HOME/tollchat-releases/${release_tag}-recovery.txt" \
  bash v2/manual-releases/capture_production_recovery.sh
```

Run the entire block in one shell invocation; separate command submissions may
not preserve variables. Use `bash`, rather than sourcing the script with `.`.
The recovery directory must be owned by you and not group- or world-writable.
Keep it outside the checkout so removing the worktree does not remove your recovery evidence.

The script reads the fixed Lambda `live` alias and AgentCore `preview` endpoint.
It changes no AWS resources and creates a private file containing only their
current versions. Success exits zero without output. After success, inspect it
(substitute the same release tag):

```bash
cat "$HOME/tollchat-releases/v1.0.12-recovery.txt"
```

Keep this original record through deployment and recovery. Never overwrite it
or recapture it after a failed deployment.

If capture fails, stop before publishing:

- `record-path`: check that `RELEASE_EVIDENCE` is supplied to the script and nonempty, its
  parent directory exists with the required ownership/permissions, and the
  destination does not already exist. An existing record is never overwritten.
- `account-identity`: check authentication and the production profile/account.
- `lambda-validate` or `agentcore-validate`: the read failed or routing was not
  in the expected stable state. Investigate before continuing.
- `record-write`: the private record could not be safely written. Treat any
  file left by a failed capture as incomplete; investigate before retrying.

## 4. Publish and review

Publish a stable GitHub Release with the chosen tag pointing to the exact
verified commit. It must not be a draft or prerelease.

Wait for `v2-production-plan` to verify the candidate and save its production
plan. Require a zero-change foundation plan and review every application action.
Stop on unexplained actions or replacements. The saved plan is valid for 24 hours.

Approve the protected `production` job only after reviewing that plan. Automation
then revalidates the release, runs fixed migrations, applies the exact saved
plan, and checks readiness and one canary. Confirm the final release evidence
reports success.

## 5. If delivery fails

Stop delivery and inspect the failed stage. A failed canary requires a human
decision; rollback is not automatic. Use the original recovery record and the
[manual routing restore procedure](../RUNBOOK.md#production-canary-failure-human-stop-and-manual-routing-restore).
This directory does not provide a direct deploy or automatic restore command.
