#!/usr/bin/env bash
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
git_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
image="$(grep -om1 'ghcr\.io/rhprasad0/nova-toll-budget-agent/toolchain@sha256:[0-9a-f]\{64\}' \
  "$root/.github/workflows/ci.yml")" || {
  echo "toolchain: no toolchain image digest in .github/workflows/ci.yml" >&2
  exit 1
}
endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
if [[ "$endpoint" != unix://* ]]; then
  echo "toolchain: needs a local Unix socket Docker context, not $endpoint" >&2
  exit 1
fi
socket="${endpoint#unix://}"

if docker info --format '{{.SecurityOptions}}' | grep -q rootless; then
  user=(--user 0:0)
else
  user=(--user "$(id -u):$(id -g)" --group-add "$(stat -c %g "$socket")")
fi

cache="${XDG_CACHE_HOME:-$HOME/.cache}/nova-toll-toolchain"
mkdir -p "$root/v2/.venv" "$root/v2/.venv-toolchain" "$cache" "$HOME/.aws"
mounts=(
  --volume "$root:$root"
  --volume "$root/v2/.venv-toolchain:$root/v2/.venv"
  --volume "$socket:/var/run/docker.sock"
  --mount "type=tmpfs,destination=$HOME,tmpfs-mode=1777"
  --volume "$cache:$HOME/.cache"
  --volume "$HOME/.aws:$HOME/.aws"
)
if [[ "$git_dir" != "$root/.git" ]]; then
  mounts+=(--volume "$git_dir:$git_dir")
fi

terminal=(--interactive)
if [[ -t 0 && -t 1 ]]; then
  terminal+=(--tty)
fi

exec docker run --rm --init "${terminal[@]}" "${user[@]}" "${mounts[@]}" \
  --network host --env HOME="$HOME" --env AWS_PROFILE --env AWS_REGION \
  --env AWS_DEFAULT_REGION --workdir "$(pwd -P)" "$image" "${@:-bash}"
