#!/usr/bin/env bash
# Run the MCP server e2e suite against throwaway PostGIS and DynamoDB Local containers.
set -euo pipefail

CRATE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V2="$(cd "$CRATE/../.." && pwd)"
PG_PORT="${MCP_E2E_PG_PORT:-55432}"
DDB_PORT="${MCP_E2E_DDB_PORT:-58000}"

containers=()
trap 'docker rm --force "${containers[@]}" >/dev/null 2>&1 || true' EXIT
containers+=("$(docker run --detach --rm --env POSTGRES_HOST_AUTH_METHOD=trust \
  --publish "127.0.0.1:$PG_PORT:5432" postgis/postgis:17-3.5)")
pg="${containers[0]}"
containers+=("$(docker run --detach --rm --publish "127.0.0.1:$DDB_PORT:8000" \
  amazon/dynamodb-local@sha256:ff89bd48ff32cd8d9be5fee8873b65b8854dc408f1afe881be6eb00247bc0dab \
  -jar DynamoDBLocal.jar -inMemory)")

# Retry for up to a minute, then run once more so a failure shows its error.
wait_for() {
  for _ in $(seq 60); do
    "$@" >/dev/null 2>&1 && return
    sleep 1
  done
  "$@"
}
# TCP readiness: the image's temporary init server listens only on its socket.
wait_for docker exec "$pg" pg_isready --host 127.0.0.1 --username postgres --quiet
wait_for curl --silent --output /dev/null "http://127.0.0.1:$DDB_PORT"

# Same disposable oracle database as v2/scripts/run_db_tests.sh, with its real least-privilege roles.
docker cp "$V2/db" "$pg:/db"
docker exec "$pg" psql --username postgres --set ON_ERROR_STOP=1 --quiet \
  --command 'CREATE ROLE rds_iam' --command 'CREATE DATABASE nova_toll_mcp_e2e TEMPLATE template0'
for migration in 001_create_pricing_schema.sql 003_create_oracle_schema.sql; do
  docker exec "$pg" psql --username postgres --dbname nova_toll_mcp_e2e --set ON_ERROR_STOP=1 \
    --quiet --file "/db/migrations/$migration" >/dev/null
done

MCP_E2E_PG_PORT="$PG_PORT" MCP_E2E_DDB_PORT="$DDB_PORT" cargo test --locked --manifest-path "$CRATE/Cargo.toml" "$@"
