#!/usr/bin/env bash
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
common="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"
image="$(grep -om1 'ghcr\.io/rhprasad0/nova-toll-budget-agent/toolchain@sha256:[0-9a-f]\{64\}' \
  "$root/.github/workflows/ci.yml")"
socket="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
socket="${socket#unix://}"

if docker info --format '{{.SecurityOptions}}' | grep -q rootless; then
  user=(--user 0:0)
else
  user=(--user "$(id -u):$(id -g)" --group-add "$(stat -c %g "$socket")")
fi

mounts=(--volume "$root:$root" --volume "$socket:/var/run/docker.sock")
if [[ "$common" != "$root" ]]; then
  mounts+=(--volume "$common:$common")
fi
if [[ -d "$HOME/.aws" ]]; then
  mounts+=(--volume "$HOME/.aws:/aws:ro" --env AWS_CONFIG_FILE=/aws/config
    --env AWS_SHARED_CREDENTIALS_FILE=/aws/credentials)
fi

tty=()
if [[ -t 0 && -t 1 ]]; then
  tty=(--interactive --tty)
fi

exec docker run --rm "${tty[@]}" "${user[@]}" "${mounts[@]}" --network host \
  --env UV_PROJECT_ENVIRONMENT="$root/v2/.venv-toolchain" \
  --workdir "$PWD" "$image" "${@:-bash}"
