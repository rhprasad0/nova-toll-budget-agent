#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.." || exit

node_version=22.22.1
node_sha256=9a6bc82f9b491279147219f6a18add1e18424dce90d41d2a5fcd69d4924ba3aa
terraform_version=1.15.8
terraform_sha256=d25ce7b6902013ad905db3d2eab0be4cd905887fe88b81a6171b8d5503c31f3d
work=/tmp/factory-bootstrap
mkdir -p "$work"
as_root=$([ -w /usr/local/bin ] || echo sudo)

download() {
  curl -fsSL --proto '=https' --tlsv1.2 -o "$3" "$1" && echo "$2  $3" | sha256sum --check --status
}

for name in python python3; do
  $as_root ln -sf /usr/bin/python3.13 "/usr/local/bin/$name"
done
hash -r

if [ "$(node --version 2>/dev/null)" != "v$node_version" ]; then
  archive="$work/node.tar.xz"
  if download "https://nodejs.org/dist/v$node_version/node-v$node_version-linux-x64.tar.xz" "$node_sha256" "$archive"; then
    $as_root tar -xJf "$archive" -C /usr/local --strip-components=1
  fi
  hash -r
fi

if ! terraform version 2>/dev/null | grep -qx "Terraform v$terraform_version"; then
  archive="$work/terraform.zip"
  if download "https://releases.hashicorp.com/terraform/$terraform_version/terraform_${terraform_version}_linux_amd64.zip" "$terraform_sha256" "$archive"; then
    unzip -oq "$archive" terraform -d "$work" && $as_root install -m 755 "$work/terraform" /usr/local/bin/terraform
  fi
  hash -r
fi

if [ "$(git rev-parse --is-shallow-repository)" = true ]; then
  git fetch --quiet --unshallow origin
fi
git fetch --quiet origin main

v2/scripts/setup.sh >"$work/setup.log" 2>&1
setup_status=$?

echo "--- factory bootstrap report"
echo "python3: $(python3 --version 2>&1) at $(command -v python3)"
echo "node: $(node --version 2>/dev/null || echo missing) (want v$node_version)"
echo "terraform: $(terraform version 2>/dev/null | head -n 1 || echo missing) (want v$terraform_version)"
echo "uv: $(uv --version 2>/dev/null || echo missing)"
echo "gh: $(gh --version 2>/dev/null | head -n 1 || echo missing)"
for tool in jq xxd zip unzip; do
  command -v "$tool" >/dev/null || echo "$tool: missing"
done
echo "history: shallow=$(git rev-parse --is-shallow-repository), origin/main=$(git rev-parse --short origin/main 2>/dev/null || echo missing)"
if [ "$setup_status" -eq 0 ]; then
  echo "v2/scripts/setup.sh: ok"
else
  echo "v2/scripts/setup.sh: failed (exit $setup_status); last lines of $work/setup.log:"
  tail -n 20 "$work/setup.log"
fi
echo "run with: export PATH=\"\$HOME/.local/bin:\$PATH\""
echo "you can run: .github/scripts/verify.sh terraform; .github/scripts/verify.sh loader origin/main through its pytest step; .github/scripts/verify.sh factory, where the tests that build Docker images fail"
echo "CI alone runs: the database and mcp jobs, the Docker image tests, and the package builds and their digests; no Docker daemon runs here"
