#!/usr/bin/env bash
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$V2_ROOT/infra/build"
STAGE="$BUILD/timed-checks"
EPOCH="2020-01-01 00:00:00Z"
export TZ=UTC
export UV_MANAGED_PYTHON=1 UV_PYTHON_INSTALL_DIR=/tmp/nova-toll-cpython

uv python install 3.13 >/dev/null
PYTHON_BIN="$(uv python find 3.13)"

rm -rf -- "$STAGE" "$BUILD/timed-checks.zip"
mkdir -p "$STAGE/agent" "$STAGE/agent_tools" "$STAGE/eval" "$STAGE/agent-sops"

cp -- "$V2_ROOT/lambdas/timed_checks/handler.py" "$STAGE/handler.py"
cp -- "$V2_ROOT/timed_checks.py" "$STAGE/timed_checks.py"
cp -- "$V2_ROOT/eval/run_evaluation.py" "$V2_ROOT/eval/test-cases.jsonl" "$STAGE/eval/"
cp -- "$V2_ROOT/agent/__init__.py" "$V2_ROOT/agent/toll_agent.py" "$STAGE/agent/"
cp -- "$V2_ROOT/agent_tools/"*.py "$STAGE/agent_tools/"
cp -- "$V2_ROOT/agent-sops/nova-toll-pricing-assistant.sop.md" "$STAGE/agent-sops/"

uv pip install \
  --python "$PYTHON_BIN" \
  --require-hashes \
  --python-platform x86_64-manylinux_2_28 \
  --python-version 3.13 \
  --only-binary :all: \
  --target "$STAGE" \
  -r "$V2_ROOT/scripts/timed-checks-requirements.txt"

find "$STAGE" -type f -name .lock -delete
if find "$STAGE" \( -type l -o -type d -name '*.pyc' -o -type f \( -name '*.pyc' -o -name '.env' -o -name '.env.*' \) \) | grep -q .; then
  echo "timed-checks stage contains a forbidden entry" >&2
  exit 1
fi

find "$STAGE" -type f ! -name .lock -exec chmod 0644 {} +
find "$STAGE" -type f -name '*.so.*' -exec chmod 0755 {} +
find "$STAGE" -exec touch -d "$EPOCH" {} +

env -i \
  PATH="$PATH" \
  TZ=UTC \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONNOUSERSITE=1 \
  PYTHONPATH="$STAGE" \
  UV_MANAGED_PYTHON=1 \
  UV_PYTHON_INSTALL_DIR=/tmp/nova-toll-cpython \
  uv run --python 3.13 --no-project python - <<'PY'
import os
from pathlib import Path

import agent.toll_agent
import eval.run_evaluation
import handler

assert not any(
    name.startswith(("AWS_", "ACTIONS_", "GITHUB_", "OPENAI_", "CLOUDFLARE_"))
    for name in os.environ
)
assert callable(handler.handler)
assert Path(eval.run_evaluation.__file__).with_name("test-cases.jsonl").is_file()
assert (
    Path(agent.toll_agent.__file__).resolve().parents[1]
    / "agent-sops"
    / "nova-toll-pricing-assistant.sop.md"
).is_file()
PY

find "$STAGE" -type f -name '*.pyc' -delete

(cd "$STAGE" && find . -type f ! -name .lock | LC_ALL=C sort | zip -qX0 "$BUILD/timed-checks.zip" -@)

python3 -m zipfile -t "$BUILD/timed-checks.zip" >/dev/null
if [[ "$(stat -c %s "$BUILD/timed-checks.zip")" -le 0 ]]; then
  echo "timed-checks archive is empty" >&2
  exit 1
fi
if [[ "$(du -sb "$STAGE" | awk '{print $1}')" -gt 262144000 ]]; then
  echo "timed-checks stage exceeds the Lambda 250 MiB limit" >&2
  exit 1
fi

echo "built $BUILD/timed-checks.zip"
