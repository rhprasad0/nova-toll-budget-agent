#!/usr/bin/env bash
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=v2/scripts/build_loader_zip.sh
source "$V2_ROOT/scripts/build_loader_zip.sh"
BUILD="$V2_ROOT/infra/build"
STAGE="$BUILD/publisher"
EPOCH="2020-01-01 00:00:00Z"
export TZ=UTC
export UV_MANAGED_PYTHON=1 UV_PYTHON_INSTALL_DIR=/tmp/nova-toll-cpython
uv python install 3.13 >/dev/null

rm -rf "$STAGE" "$BUILD/publisher.zip"
mkdir -p "$STAGE/agent_tools"
cp "$V2_ROOT/lambdas/publisher/handler.py" "$V2_ROOT/lambdas/publisher/costs.py" "$STAGE/"
cp "$V2_ROOT/agent_tools/current_price_domain.py" \
  "$V2_ROOT/agent_tools/validate_toll_route.py" "$STAGE/agent_tools/"
download_rds_ca_bundle "$STAGE/rds-ca-bundle.pem"
uv pip install \
  --require-hashes \
  --python-platform x86_64-manylinux2014 \
  --python-version 3.13 \
  --only-binary :all: \
  --target "$STAGE" \
  -r "$V2_ROOT/scripts/publisher-requirements.txt"

find "$STAGE" -type f ! -name .lock -exec chmod 0644 {} +
find "$STAGE" -type f -name '*.so.*' -exec chmod 0755 {} +
find "$STAGE" -exec touch -d "$EPOCH" {} +
(cd "$STAGE" && find . -type f | LC_ALL=C sort | zip -qX0 "$BUILD/publisher.zip" -@)
echo "built $BUILD/publisher.zip"
