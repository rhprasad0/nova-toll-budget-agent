#!/usr/bin/env bash
set -euo pipefail

ANTHROPIC_WORK_SECRET="$(jq -r '.secret // empty')"
export ANTHROPIC_WORK_SECRET
name="work-$ANTHROPIC_WORK_ID"
workdir="$HOME/sessions/$ANTHROPIC_SESSION_ID"
socket="${DOCKER_HOST#unix://}"
image=factory-sandbox:latest
repo="${FACTORY_REPO:-rhprasad0/nova-toll-budget-agent}"
clone="$workdir/${repo#*/}"
lab="${name,,}"
proxy=(--env "HTTPS_PROXY=$FACTORY_PROXY" --env "HTTP_PROXY=$FACTORY_PROXY"
  --env "https_proxy=$FACTORY_PROXY" --env "http_proxy=$FACTORY_PROXY")

cleanup() {
  docker rm --force --volumes "$name" "$name-postgres" "$name-retained" >/dev/null 2>&1 || true
  docker network rm "$name" >/dev/null 2>&1 || true
  if [[ -n "${FACTORY_LAB:-}" ]]; then
    docker compose -p "$lab" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
}

mkdir -p "$workdir"
exec 9>"$workdir.lock"
flock --nonblock 9 || {
  echo "factory-spawn: session $ANTHROPIC_SESSION_ID is already running here" >&2
  exit 1
}
cleanup
trap cleanup EXIT
if [[ ! -d "$clone/.git" ]]; then
  docker run --rm "${proxy[@]}" --volume "$workdir:/workspace" --entrypoint git "$image" \
    clone --quiet "https://github.com/$repo" "/workspace/${repo#*/}"
fi
lab_env=()
if [[ -n "${FACTORY_LAB:-}" ]]; then
  docker compose -f "$clone/$FACTORY_LAB" -p "$lab" up --detach --wait --quiet-pull >/dev/null
  lab_env=(--env "LAB_PROJECT=$lab")
fi

docker network create "$name" >/dev/null
for database in postgres retained; do
  alias="postgres"
  [[ "$database" == retained ]] && alias="postgres-retained"
  docker run --detach --name "$name-$database" --network "$name" --network-alias "$alias" \
    --env POSTGRES_HOST_AUTH_METHOD=trust postgis/postgis:17-3.5 >/dev/null
done

docker run --rm --init --name "$name" --network "$name" \
  --cap-drop ALL --security-opt no-new-privileges \
  --volume "$workdir:/workspace" --volume "$socket:/var/run/docker.sock" \
  --env ANTHROPIC_SESSION_ID --env ANTHROPIC_WORK_ID --env ANTHROPIC_ENVIRONMENT_ID \
  --env ANTHROPIC_ENVIRONMENT_KEY --env ANTHROPIC_WORK_SECRET --env ANTHROPIC_BASE_URL \
  "${proxy[@]}" \
  --env GH_TOKEN=replaced-by-the-proxy \
  --env PGHOST=postgres --env PGPORT=5432 --env PGUSER=postgres \
  --env RETAINED_PGHOST=postgres-retained --env RETAINED_PGPORT=5432 \
  --env FACTORY_SANDBOX_DATABASE_URL \
  --env POSTGRES_CONTAINER_ID="$name-postgres" \
  --env RETAINED_POSTGRES_CONTAINER_ID="$name-retained" \
  --env DISPOSABLE_DOCKER_NETWORK="container:$name" \
  "${lab_env[@]}" \
  "$image"
