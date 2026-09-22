#!/usr/bin/env bash

download_rds_ca_bundle() {
  local destination="$1"
  local ca_url="https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
  local ca_sha256="e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "$ca_url" -o "$destination" || return
  echo "$ca_sha256  $destination" | sha256sum --check --status || {
    echo "RDS CA bundle digest mismatch; review AWS's CA rotation notice." >&2
    return 1
  }
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$V2_ROOT/infra/build"
STAGE="$BUILD/loader"
EPOCH="2020-01-01 00:00:00Z"
export TZ=UTC
export UV_MANAGED_PYTHON=1 UV_PYTHON_INSTALL_DIR=/tmp/nova-toll-cpython
uv python install 3.13 >/dev/null

rm -rf "$STAGE" "$BUILD/loader.zip"
mkdir -p "$STAGE"
cp "$V2_ROOT"/lambdas/loader/{handler.py,_bounds.py,parse_csv.py,parse_xml.py} "$STAGE/"
download_rds_ca_bundle "$STAGE/rds-ca-bundle.pem"
uv pip install \
  --require-hashes \
  --python-platform x86_64-manylinux2014 \
  --python-version 3.13 \
  --only-binary :all: \
  --target "$STAGE" \
  -r "$V2_ROOT/scripts/loader-requirements.txt"

find "$STAGE" -type f ! -name .lock -exec chmod 0644 {} +
find "$STAGE" -type f -name '*.so.*' -exec chmod 0755 {} +
find "$STAGE" -exec touch -d "$EPOCH" {} +
(cd "$STAGE" && find . -type f | LC_ALL=C sort | zip -qX0 "$BUILD/loader.zip" -@)
echo "built $BUILD/loader.zip"
