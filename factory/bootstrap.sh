#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.." || exit
work=/tmp/factory-bootstrap
mkdir -p "$work"

if [ "$(git rev-parse --is-shallow-repository)" = true ]; then
  git fetch --quiet --unshallow origin
fi
git fetch --quiet origin main

v2/scripts/setup.sh >"$work/setup.log" 2>&1
setup_status=$?

echo "--- factory bootstrap report"
echo "python3: $(python3 --version 2>&1); node: $(node --version 2>/dev/null || echo missing)"
echo "terraform: $(terraform version 2>/dev/null | head -n 1 || echo missing); uv: $(uv --version 2>/dev/null || echo missing)"
echo "docker: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unreachable); databases: ${PGHOST:-none} and ${RETAINED_PGHOST:-none}"
echo "history: shallow=$(git rev-parse --is-shallow-repository), origin/main=$(git rev-parse --short origin/main 2>/dev/null || echo missing)"
if [ "$setup_status" -eq 0 ]; then
  echo "v2/scripts/setup.sh: ok"
else
  echo "v2/scripts/setup.sh: failed (exit $setup_status); last lines of $work/setup.log:"
  tail -n 20 "$work/setup.log"
fi
echo "you can run every job CI runs: .github/scripts/verify.sh loader origin/main, terraform, database origin/main, and factory"
