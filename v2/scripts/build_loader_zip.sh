#!/usr/bin/env bash
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$V2_ROOT/infra/build"
STAGE="$BUILD/loader"
CA_URL="https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
CA_SHA256="e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
EPOCH="2020-01-01 00:00:00Z"

rm -rf "$STAGE" "$BUILD/loader.zip"
mkdir -p "$STAGE"
cp "$V2_ROOT"/lambdas/loader/{handler.py,_bounds.py,parse_csv.py,parse_xml.py} "$STAGE/"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  "$CA_URL" -o "$STAGE/rds-ca-bundle.pem"
echo "$CA_SHA256  $STAGE/rds-ca-bundle.pem" | sha256sum --check --status || {
  echo "RDS CA bundle digest mismatch; review AWS's CA rotation notice." >&2
  exit 1
}
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
(cd "$STAGE" && find . -type f | LC_ALL=C sort | zip -qX "$BUILD/loader.zip" -@)
echo "built $BUILD/loader.zip"
