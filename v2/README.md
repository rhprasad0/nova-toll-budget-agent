# TollChat v2

This directory contains TollChat's deployed application, tests, evals, and
application infrastructure. Shared production foundations live in `../infra`.

## Shared foundation changes

Run these commands from the repository root. Build and review the real fetcher
package for every root `infra/` plan. The current development foundation handoff
is the authorized #327/#333 replacement in the
[development foundation replacement runbook](runbooks/development-foundation-replacement.md).
Do not use a generic plan display or unbounded apply command; application
release remains a separately approved follow-on operation.

```sh
v2/scripts/build_fetcher_zip.sh
AWS_PROFILE=nova-toll-dev terraform -chdir=infra init -backend=false -input=false
AWS_PROFILE=nova-toll-dev terraform -chdir=infra validate
```

Pull-request checks remain credential-free. Load any runtime-only credentials
from SSM into the process environment; never place them in Terraform variables,
plans, state evidence, or documentation.

## Runtime boundaries

- [Current-price tool](agent_tools/get_current_toll_price.py) and its
  [deterministic pricing domain](agent_tools/current_price_domain.py)
- [Annual toll-commute affordability tool](agent_tools/get_annual_toll_ballpark.py)
- [Directed routing contract](db/oracle/CONTRACT.md),
  [schema](db/oracle/schema.sql), and
  [reviewed source-data builder](oracle/build_oracle_data.py)
- [Agent-facing route validation](agent_tools/validate_toll_route.py)

## Database bootstrap

- [PostgreSQL schema](db/schema.sql)
- [IAM-authenticated database roles](db/roles.sql)
- [Missing I-95/495 OD validation](eval/results/i95-missing-od-pricing.md) and
  [production proxy mapping and pricing views](db/analysis.sql)

The independently deployable `pricing` application schema is at **1.3.0**. Its
version is stored in `pricing.schema_version`; CI tests
the bootstrap, privileges, analytics, cleanup guard, and monotonic SemVer policy
on PostgreSQL 17.9.

The development-only bootstrap also creates the short-lived
`schema_migrator_development` IAM login, the `pricing_owner_development` stable
owner, and private `tollchat_migration.schema_history` metadata seeded with the
1.3.0 pricing and 1.14.1 Oracle canonical baselines. It remains
canonical-schema-only: no released application migration is applied by the
bootstrap, and this groundwork does not make hard-coded-owner migrations
portable to development.

The independently versioned `oracle` schema is at **1.14.1**. It installs
core PostGIS 3.5.x inside `oracle`, loads the directed toll-access graph, and
exposes route validation plus bounded prompt-point retrieval to `tollchat_agent`
and internal pricing operations to `pricing_caller`.
Regenerate and verify its checked-in SQL seed and frontend coverage snapshot with:

```sh
uv run python oracle/build_oracle_data.py
uv run python oracle/build_oracle_data.py --check
```

For a disposable or local database, install pricing before oracle:

```sh
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/001_create_pricing_schema.sql
psql "$NOVA_TOLL_URL" -v ON_ERROR_STOP=1 \
  -f v2/db/migrations/003_create_oracle_schema.sql
```

For a disposable or local existing database, read both `schema_version` tables
and apply only the matching guarded [`*_upgrade_*` migrations](db/migrations/)
in dependency and version order. Never edit or skip a released migration. Do
not point these direct commands at a deployed database: development migrations
use the protected workflow described below. Production delivery is configured
to use the [protected production migration component](RUNBOOK.md#protected-production-migration-component-issue-304-slice-4).
The only separately authorized manual production migration remains the
[Oracle migration 030 procedure](RUNBOOK.md#manual-oracle-migration-030).

## Verify the build

The unapplied [analytics retirement plan](plans/ANALYTICS-RETIREMENT-PLAN.md)
documents the source-retired usage and agent-route analytics scopes without
granting execution authority.

Install Node.js 22.22.1 and uv, then set up the locked development tools from
the repository root (Linux amd64/arm64):

```sh
uv sync --locked --project v2
npm ci --ignore-scripts --prefix v2
npm ci --ignore-scripts --prefix v2/lambdas/chat_proxy
v2/scripts/install_check_tools.sh
export PATH="$HOME/.local/bin:$PATH"
git config core.hooksPath .githooks
python3 v2/scripts/check_repository.py
```

The installer verifies pinned release checksums for ShellCheck 0.11.0,
actionlint 1.7.12 and Gitleaks 8.30.1. On other platforms install those same
versions yourself. Python dependencies are locked in `uv.lock`; ESLint and
TypeScript are development dependencies locked in `package-lock.json`. No
JavaScript compilation is required.

Fresh clones need this setup: Git does not automatically enable repository hooks.
**CI is the authoritative gate** because local hooks can be bypassed. The hook
requires Gitleaks on every commit and checks each affected language group in full.
Checker/configuration changes select every group; additions, renames and deletions
count. It rejects index/working-copy differences in checked inputs, including
partially staged files. Resolve or stage those changes before committing; the hook
never stashes, rewrites, restages, installs packages, or runs behavioral tests.

The full runner checks authored Python, JavaScript, shell and workflows, including
tests. It uses explicit configurations and resolves paths independently of the
invocation directory. Only dependency/build/worktree directories and the named
upstream Markdown/MapLibre distributions are excluded. Narrow external-tool
exceptions must remain useful; blanket and unused suppressions fail. Terraform
formatting/validation and disposable database contracts retain their existing CI
jobs, and behavioral checks run after the shared static gate.

From `v2/`, run the offline tests and deterministic release builds:

```sh
uv sync --locked
python3 scripts/check_repository.py
uv run python eval/run_evaluation.py --check
uv run coverage run -m pytest
uv run coverage report
node --test tests/*.mjs
npm ci --prefix lambdas/chat_proxy
npm test --prefix lambdas/chat_proxy
uv run python oracle/build_oracle_data.py --check
./scripts/build_loader_zip.sh
./scripts/build_publisher_zip.sh
./scripts/build_agentcore_zips.sh
(cd infra/build && sha256sum --check AGENTCORE_SHA256SUMS)
```

Database contract and migration checks require PostgreSQL 17 with PostGIS 3.5.
From the repository root, use a disposable container (the script independently
checks that its configured target is this empty container, so never point it at
a deployed server):

```sh
container_id="$(docker run -d --rm -e POSTGRES_HOST_AUTH_METHOD=trust \
  -p 127.0.0.1::5432 postgis/postgis:17-3.5)"
trap 'docker rm --force "$container_id" >/dev/null' EXIT
export POSTGRES_CONTAINER_ID="$container_id"
export PGHOST=127.0.0.1
export PGPORT="$(docker port "$container_id" 5432/tcp | sed 's/.*://')"
export PGUSER=postgres
until docker logs "$container_id" 2>&1 | grep -q 'PostgreSQL init process complete'; do sleep 1; done
until docker exec "$container_id" pg_isready --username "$PGUSER" --dbname postgres >/dev/null; do sleep 1; done
v2/scripts/run_db_tests.sh "$(git rev-parse HEAD^)"
```

The default `--profile full` preserves all exhaustive assertions. Use
`--profile fast` for targeted route and report fixtures while retaining database
bootstrap, migration, rollback, privilege, retirement, and adoption checks. Both
profiles require the same empty disposable cluster. Contract logs identify the
profile, retained/candidate version, elapsed seconds, and outcome. Identical
retained and candidate contracts run once; changed versions both run.

The required `v2-database` CI job selects full coverage for PR/merge-group changes
under `v2/db/`, `v2/oracle/`, `v2/tests/`, `v2/scripts/`, either infrastructure
directory, `.github/`, or the Python project/lock files. Ordinary PRs and main
pushes use fast coverage; tags and uncertain comparisons use full coverage.
Every development delivery independently runs full validation on its exact
commit in the credential-free package-build job, before packaging or uploading
the release. Failure blocks the privileged deployment and is recorded through
the existing release result. Production retains its successful-development and
full tag-validation requirements.

Credential-free PR CI never runs `terraform plan` or `apply`. The protected
production sequence is verified development bundle, stable `vX.Y.Z` admission
and claim, exact candidate validation before planner credentials, one encrypted
versioned/checksummed 24-hour saved plan, reviewer approval of the protected
job, repeated plan/state validation before fixed migration and re-assumed deploy
apply, fixed readiness, then one bounded canary. Guards fail closed before later
stages and terminal evidence remains sanitized. Before approval, capture the
fixed routing targets; a canary failure requires the human-operated manual
restore in the [runbook](RUNBOOK.md#production-canary-failure-human-stop-and-manual-routing-restore),
never an automatic rollback.

Development delivery reports an explicit `development-release` GitHub result
only after exact-version readiness and bounded static/API/two-session agent
smokes pass. The result includes immutable artifact/commit/schema identity;
native OIDC environment records alone are not release proof. PR checks use
fakes, and a live demonstration remains separately authorized.

Each successful result also retains `v2-development-evidence-<run-id>-<attempt>`
for 90 days. Operators retrieve that exact artifact to inspect the versioned,
sanitized release identity; it contains no plans, credentials, or private logs.

After merge, only human-reviewed backward-compatible development migrations use
the protected exact-release delivery sequence: artifact/checkout verification,
one saved private Terraform plan and gate, fixed-role migration, delivery-role
re-assumption, and application of that same plan. The protected, manually
dispatched [development migration workflow](../.github/workflows/v2-development-migrations.yml)
remains a main-only recovery path after the foundation and fresh-bootstrap gates in
the [protected development migration runbook](runbooks/development-foundation-replacement.md#protected-development-migration-workflow-305-slice-3).
Both paths accept no arbitrary target, role, or migration-path input and emit
sanitized evidence. This is separate from disposable local/PR checks and does
not authorize production schema changes. Production uses its own
[protected migration component](RUNBOOK.md#protected-production-migration-component-issue-304-slice-4)
for the registered migration set; manual production migration remains limited
to the [Oracle migration 030 procedure](RUNBOOK.md#manual-oracle-migration-030).

The public interface at `tollchat.ai` uses a private S3 origin for the v2 site
and an IAM-authenticated streaming Lambda URL behind CloudFront and WAF. The
same proxy and AgentCore runtime remain available through the private preview.

Chat streams guardrail-checked text snapshots as well as tool activity. The first
complete sentence is checked promptly; subsequent batches target 200 characters,
falling back to whole-word boundaries around 400 characters for long sentences.
Each check includes the current assistant message's accumulated text for context.
This follows AWS's [ApplyGuardrail streaming pattern](https://aws.amazon.com/blogs/machine-learning/use-the-applyguardrail-api-with-long-context-inputs-and-streaming-outputs-in-amazon-bedrock/),
favoring earlier feedback over its cost-efficient 1,000-character batches. Small
batches and repeated prefixes increase guardrail usage. The final answer still
passes a full output check and supplies the disclaimer; a later block replaces
the visible answer but cannot retract text already read. The local dev console
continues to expose raw Strands events for debugging.

The `get_current_toll_price` Strands tool accepts stable origin and destination
point IDs plus the supported pricing profile. It validates the route through
the oracle and prices I-66 from current observations during its published
tolling windows and at $0 outside them, I-95/I-495 from current observations,
and Dulles Greenway and Dulles Toll Road from their published schedules. I-95/I-495
components use 10-minute bins and retain recent movement, prior-week context,
and the provisional `identity_proxy_v1` label for modeled OD prices. Mixed
facility trips preserve route order and return one summed total. Callers do not
submit route plans or pricing components.

Its generated input, output, progress-event, and safe-error schemas are locked
by `agent_tools/contract-manifest.json`. Contract changes require a new,
increasing SemVer release and digest; CI rejects rewrites of published releases.

The primary `get_annual_toll_ballpark` experience helps job seekers estimate
how the tolled portion of a commute affects income. It combines recent
same-date P25/P50/P90 toll scenarios with gross annual income, a fixed one-third
tax assumption, and a fixed TollChat assumption of `$0.685` per straight-line
priced-leg mile. It excludes
untolled commute segments and remains a rough starting point rather than a
quote, tax calculation, forecast, or financial plan. Current-price lookup is
the secondary experience.

The v2 Strands agent in `agent/` loads the bounded entry/exit labels, aliases,
and coordinates from RDS once at startup, then exposes exactly the current-price
and annual-affordability tools. It fails startup if that prompt data is unavailable
or invalid.

Its final system-prompt assembly and prompt-point renderer/input contract are
independently locked by `agent/contract-manifest.json` and reported in traces as
`tollchat.system_prompt_version` and `tollchat.system_prompt_renderer_version`.
Each request also reports `tollchat.system_prompt_sha256` for the exact rendered
prompt, including its date and RDS points. Contract changes require a new,
increasing SemVer release and digest; CI rejects rewrites of published releases.
Use patch releases for corrections that preserve behavior, minor releases for
compatible behavior changes, and major releases for incompatible changes.

### Local agent console

The loopback-only browser frontend streams the v2 agent's Markdown replies,
emoji, tool activity, metrics, and raw Strands events without browser analytics
or on-disk conversation storage. It also serves the FAQ and a checked-in map of
supported toll-road access points beneath four annual toll ballparks to
Washington. From `v2/`, configure the
same AWS and database environment used by the live agent tests, then run:

```sh
AWS_PROFILE=nova-toll AWS_DEFAULT_REGION=us-east-1 \
  uv run python -m agent.dev_chat
```

Open <http://127.0.0.1:8000>. The agent reads its OpenAI credential from SSM;
the Boto3 login provider refreshes the `nova-toll` profile's temporary
credentials without writing them to a project file. Run `aws login --profile
nova-toll` again when its login session expires after up to 12 hours. Required
database variables are `DB_HOST`, `DB_PORT`, `DB_NAME`, and
`DB_CA_BUNDLE_PATH`. If needed, `scripts/build_loader_zip.sh` creates the
verified RDS CA bundle at `infra/build/loader/rds-ca-bundle.pem`.

Its stable developer prompt uses OpenAI's explicit provider-managed prompt cache
with a 30-minute TTL. Strands exposes cache reuse through
`AgentResult.metrics.accumulated_usage` as `cacheReadInputTokens` and
`cacheWriteInputTokens`; toll prices, annual ballparks, final answers, and RDS
prompt-point queries are not application-cached.

The v2 loader under `v2/lambdas/loader` is the sole pricing loader. Native S3
events reach it through EventBridge; the retired loader has no trigger or
deployed function.
