#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/v2/scripts/build_loader_zip.sh"
BUILD="$ROOT/infra/build"
STAGE="$BUILD/factory-dashboard"
EPOCH="2020-01-01 00:00:00Z"
export TZ=UTC
export UV_MANAGED_PYTHON=1 UV_PYTHON_INSTALL_DIR=/tmp/nova-toll-cpython
unset VIRTUAL_ENV
uv python install 3.13 >/dev/null

rm -rf "$STAGE" "$BUILD/factory-dashboard.zip"
mkdir -p "$STAGE/dashboard/migrations"
cp "$ROOT"/dashboard/*.py "$STAGE/dashboard/"
cp "$ROOT"/dashboard/migrations/*.sql "$STAGE/dashboard/migrations/"
download_rds_ca_bundle "$STAGE/rds-ca-bundle.pem"
uv pip install \
  --require-hashes \
  --python-platform x86_64-manylinux2014 \
  --python-version 3.13 \
  --only-binary :all: \
  --target "$STAGE" \
  -r "$ROOT/dashboard/lambda-requirements.txt"

find "$STAGE" -type f -exec chmod 0644 {} +
find "$STAGE" -type f -name '*.so*' -exec chmod 0755 {} +
find "$STAGE" -exec touch -d "$EPOCH" {} +
(cd "$STAGE" && find . -type f | LC_ALL=C sort | zip -qX0 "$BUILD/factory-dashboard.zip" -@)
echo "built $BUILD/factory-dashboard.zip"
