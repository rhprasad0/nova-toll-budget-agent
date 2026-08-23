#!/usr/bin/env bash
# Build the sole retained v1 deployment package.
set -euo pipefail

V1_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$V1_ROOT/infra/build"
STAGE="$BUILD/fetcher"

rm -rf "$STAGE" "$BUILD/fetcher.zip"
mkdir -p "$STAGE"
cp "$V1_ROOT/lambdas/fetcher/handler.py" "$STAGE/"
find "$STAGE" -type f -exec chmod 0644 {} +
find "$STAGE" -exec touch -d '2020-01-01 00:00:00Z' {} +
(cd "$STAGE" && find . -type f | LC_ALL=C sort | zip -qX "$BUILD/fetcher.zip" -@)

echo "built $BUILD/fetcher.zip"
