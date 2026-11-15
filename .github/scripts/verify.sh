#!/usr/bin/env bash
# The credential-free checks behind the required CI jobs, runnable anywhere.
#
#   .github/scripts/verify.sh [loader|terraform|database|factory|mcp|all|quick] [BASE_GIT_REF]
#
# ci.yml and terraform.yml call this, so a local or sandbox run checks what CI
# checks. Setup (toolchains, the pinned checkers, PostGIS for `database`) is the
# caller's: see "Verify the build" in v2/README.md. Only the ci.yml jobs listed in
# test_ci_jobs_run_verify run elsewhere. `quick` is the pre-push hook's subset.
#
# It lives under .github/ because that path is closed to the factory, so a work
# order cannot drop a check from this list. `database` and `mcp` need Docker.
# `all` leaves out `factory` and `mcp`: the factory runs `all` in a sandbox that
# cannot reach the ports mcp's e2e.sh publishes on the host.
set -euo pipefail

job="${1:-all}"
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
base="${2:-}"
# Pull requests build the packages; main delivery owns the release bundle.
event="${GITHUB_EVENT_NAME:-pull_request}"

# Only loader and database compare against a base; terraform.yml's shallow
# checkout has no main to find one in.
need_base() {
  # In CI a missing base is a workflow bug; guessing one would compare HEAD with itself.
  if [[ -z "$base" && -n "${GITHUB_ACTIONS:-}" ]]; then
    echo 'verify: CI must pass BASE_GIT_REF' >&2
    exit 2
  fi
  base="${base:-$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main)}" || {
    echo 'verify: no main branch to compare against; pass BASE_GIT_REF' >&2
    exit 2
  }
}

step() {
  echo "::group::$*"
  local status=0
  "$@" || status=$?
  echo "::endgroup::"
  if ((status)); then
    echo "verify: FAILED ($status): $*" >&2
    exit "$status"
  fi
}

no_em_dashes() {
  ! git grep -n '—' -- \
    'agent/*.html' 'agent/*.mjs' 'agent/*.js' 'agent/*.json' 'agent/*.txt' \
    ':(exclude)agent/assets/LICENSE.txt' \
    ':(exclude)agent/assets/markdown-it.esm.min.mjs' \
    ':(exclude)agent/assets/maplibre-gl-6.0.0/**' ||
    {
      echo 'Front-end copy must not contain em dashes.' >&2
      return 1
    }
}

corpus() {
  uv run --locked python -m eval.golden --allow-uninitialized || {
    echo 'If corpus inputs or protected sources changed, freeze each split, from v2:' >&2
    echo '  uv run python -m eval.corpus freeze --corpus eval/active/SPLIT --split SPLIT --version NEWER' >&2
    return 1
  }
}

# The trusted development plan rejects a stale package digest, but it needs AWS;
# this catches it here, straight after the builds.
package_digests() {
  local sums
  sums="$(mktemp)"
  (cd infra/build && sha256sum agentcore.zip chat-proxy.zip loader.zip publisher.zip timed-checks.zip) >"$sums"
  python3 scripts/update_release_manifest.py --check "$sums"
}

# The few-second checks: the pre-push hook runs these alone, and loader runs them too.
quick_checks() {
  step corpus
  step uv run --locked python scripts/check_tool_contract_versions.py "$base"
  step uv run --locked python -m scripts.check_agent_contract_versions "$base"
  step uv run --locked python oracle/build_oracle_data.py --check
}

quick() (
  need_base
  cd v2
  quick_checks
)

loader() (
  need_base
  cd v2
  step no_em_dashes
  step uv sync --locked
  step npm ci --ignore-scripts
  step npm ci --ignore-scripts --prefix lambdas/chat_proxy
  step python3 scripts/check_repository.py
  quick_checks
  # Provider schemas let the cost-dashboard mock-plan tests run instead of skip.
  step terraform -chdir=infra init -backend=false -input=false
  # Delivery rejects a shared-resource change only after merge; this catches it here.
  step python3 scripts/infrastructure_plan.py "$base"
  step uv run coverage run -m pytest --durations=30 --durations-min=1
  step uv run coverage report
  step node --test tests/*.mjs
  if [[ "$event" != pull_request ]]; then
    step npm ci --prefix lambdas/chat_proxy
  fi
  if [[ "$event" == pull_request ]]; then
    step ./scripts/build_fetcher_zip.sh
    step ./scripts/build_loader_zip.sh
    step ./scripts/build_publisher_zip.sh
    step ./scripts/build_agentcore_zips.sh
  fi
  step npm test --prefix lambdas/chat_proxy
  if [[ "$event" == pull_request ]]; then
    step ./scripts/build_timed_checks_zip.sh
    step package_digests
  fi
)

terraform_checks() {
  local directory
  for directory in infra v2/infra org-circuit-breaker; do
    step terraform -chdir="$directory" fmt -check -recursive
    step terraform -chdir="$directory" init -backend=false -input=false
    step terraform -chdir="$directory" validate
  done
  step python3 -m unittest infra.test_delivery_plan_validator
  step python3 -m unittest infra.test_release_manifest
  step python3 infra/test_delivery_identities.py
}

# Needs two empty postgis/postgis:17-3.5 containers: POSTGRES_CONTAINER_ID on
# PGPORT and RETAINED_POSTGRES_CONTAINER_ID on 5433.
database_contracts() {
  if [[ "$DATABASE_PROFILE" == full ]]; then
    local log retained_pid status=0
    log="$(mktemp)"
    PGPORT=5433 POSTGRES_CONTAINER_ID="$RETAINED_POSTGRES_CONTAINER_ID" \
      DB_CONTRACT_IDENTITY=retained \
      v2/scripts/run_db_tests.sh "$base" --profile "$DATABASE_PROFILE" \
      >"$log" 2>&1 &
    retained_pid=$!
    DB_CONTRACT_IDENTITY=candidate \
      v2/scripts/run_db_tests.sh "$base" --profile "$DATABASE_PROFILE" || status=$?
    wait "$retained_pid" || status=$?
    cat "$log"
    return "$status"
  fi
  DB_CONTRACT_IDENTITY=all v2/scripts/run_db_tests.sh "$base" --profile "$DATABASE_PROFILE"
}

database() {
  need_base
  step python3 v2/scripts/check_schema_versions.py "$base"
  DATABASE_PROFILE="${DATABASE_PROFILE:-$(python3 v2/scripts/select_db_test_profile.py \
    --event "$event" --ref "${GITHUB_REF:-}" --base "$base" --head "${GITHUB_SHA:-HEAD}")}"
  export DATABASE_PROFILE
  step database_contracts
}

factory() {
  step uv run --project v2 --locked pytest factory
}

# The crate's rust-toolchain.toml pins the toolchain rustup installs.
mcp() (
  cd v2/lambdas/mcp_server
  step cargo fmt --check
  step cargo clippy --locked --all-targets -- -D warnings
  step ./e2e.sh
)

case "$job" in
  loader) loader ;;
  terraform) terraform_checks ;;
  database) database ;;
  factory) factory ;;
  mcp) mcp ;;
  quick) quick ;;
  all)
    loader
    terraform_checks
    database
    ;;
  *)
    echo "usage: $0 [loader|terraform|database|factory|mcp|all|quick] [BASE_GIT_REF]" >&2
    exit 2
    ;;
esac
echo "verify: $job passed"
