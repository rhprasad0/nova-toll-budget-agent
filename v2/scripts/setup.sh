#!/usr/bin/env bash
# Set up a clone or a new worktree: locked dependencies, the pinned checkers,
# and the Git hooks. Safe to re-run. Needs Node.js, uv and (for the checkers) Linux.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

uv sync --locked --project v2
npm ci --ignore-scripts --prefix v2
npm ci --ignore-scripts --prefix v2/lambdas/chat_proxy
export PATH="$HOME/.local/bin:$PATH"
for tool in shellcheck actionlint gitleaks; do
  if ! command -v "$tool" >/dev/null; then
    v2/scripts/install_check_tools.sh
    break
  fi
done
# Without the providers, the tests that plan v2/infra skip.
if command -v terraform >/dev/null; then
  terraform -chdir=v2/infra init -backend=false -input=false >/dev/null
fi
git config core.hooksPath .githooks
python3 v2/scripts/check_repository.py
