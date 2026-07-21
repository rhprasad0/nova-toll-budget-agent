#!/usr/bin/env bash
set -euo pipefail

input=$(cat)
command=$(jq -r '.tool_input.command // empty' <<<"$input")

# Only act on commands that create a commit
[[ "$command" == *"git commit"* ]] || exit 0

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "gitleaks not installed locally; skipping (CI will still catch it)" >&2
  exit 0
fi

if ! gitleaks protect --staged --redact -v; then
  echo "BLOCKED: gitleaks found secrets in staged changes. Fix or unstage, then retry." >&2
  exit 2
fi
