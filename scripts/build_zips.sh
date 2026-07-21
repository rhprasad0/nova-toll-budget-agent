#!/usr/bin/env bash
# Build the two Lambda deployment zips into infra/build/.
#
#   fetcher.zip  handler.py only — boto3 ships in the python3.13 runtime.
#   loader.zip   handler.py + parsers + rds-ca-bundle.pem + hash-verified psycopg.
#
# Zips are reproducible: fixed mtimes + sorted entries, so an unchanged build
# produces an identical hash and Terraform sees no diff. Requires network for
# the psycopg wheels (hash-pinned) and the RDS CA bundle.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$REPO/infra/build"
CA_URL="https://truststore.s3.amazonaws.com/global-bundle.pem"
PY_VERSION="3.13"
PY_PLATFORM="x86_64-manylinux2014"  # Lambda runtime arch
EPOCH="2020-01-01 00:00:00Z"        # deterministic zip mtime

rm -rf "$BUILD"
mkdir -p "$BUILD"

# --- fetcher: single file, stdlib + boto3(runtime-provided) ---
fetcher_stage="$BUILD/fetcher"
mkdir -p "$fetcher_stage"
cp "$REPO/lambdas/fetcher/handler.py" "$fetcher_stage/"

# --- loader: code + CA bundle + hash-verified psycopg for the Lambda arch ---
loader_stage="$BUILD/loader"
mkdir -p "$loader_stage"
cp "$REPO/lambdas/loader/handler.py" \
   "$REPO/lambdas/loader/parse_csv.py" \
   "$REPO/lambdas/loader/parse_xml.py" \
   "$loader_stage/"
curl -fsSL "$CA_URL" -o "$loader_stage/rds-ca-bundle.pem"
uv pip install \
  --require-hashes \
  --python-platform "$PY_PLATFORM" \
  --python-version "$PY_VERSION" \
  --only-binary :all: \
  --target "$loader_stage" \
  -r "$REPO/scripts/loader-requirements.txt"

# --- zip both, deterministically ---
zip_stage() {  # <stage_dir> <out.zip>
  local stage="$1" out="$2"
  find "$stage" -exec touch -d "$EPOCH" {} +
  ( cd "$stage" && find . -type f | LC_ALL=C sort | zip -qX "$out" -@ )
}
zip_stage "$fetcher_stage" "$BUILD/fetcher.zip"
zip_stage "$loader_stage" "$BUILD/loader.zip"

echo "built:"
echo "  $BUILD/fetcher.zip  ($(unzip -l "$BUILD/fetcher.zip" | tail -1 | awk '{print $2}') files)"
echo "  $BUILD/loader.zip   ($(unzip -l "$BUILD/loader.zip"  | tail -1 | awk '{print $2}') files)"
echo
echo "apply with (handler entrypoint is handler.handler, not the placeholder default):"
echo "  cd infra && terraform apply \\"
echo "    -var fetcher_package_path=build/fetcher.zip -var fetcher_handler=handler.handler \\"
echo "    -var loader_package_path=build/loader.zip   -var loader_handler=handler.handler \\"
echo "    -var home_ip=<your.ip>"
