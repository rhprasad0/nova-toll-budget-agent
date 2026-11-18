#!/usr/bin/env bash
set -euo pipefail
DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
export DOCKER_HOST
cutoff="$(date -d '12 hours ago' +%s)"
docker ps --all --quiet | while read -r id; do
  created="$(docker inspect --format '{{.Created}}' "$id")"
  if [[ "$(date -d "$created" +%s)" -lt "$cutoff" ]]; then
    docker rm --force --volumes "$id" >/dev/null
  fi
done
docker volume prune --all --force >/dev/null
docker network prune --force >/dev/null
docker image prune --force >/dev/null
docker builder prune --force >/dev/null
docker run --rm --volume "$HOME/sessions:/sessions" --entrypoint find factory-sandbox:latest \
  /sessions -mindepth 1 -maxdepth 1 -mtime +1 -exec rm -rf {} +
