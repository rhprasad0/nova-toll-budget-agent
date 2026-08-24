#!/usr/bin/env bash
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$V2_ROOT/../infra/build"
STAGE="$BUILD/fetcher"

rm -rf "$STAGE" "$BUILD/fetcher.zip"
mkdir -p "$STAGE"
cp "$V2_ROOT/lambdas/fetcher/handler.py" "$STAGE/"
find "$STAGE" -type f -exec chmod 0644 {} +
find "$STAGE" -exec touch -d '2020-01-01 00:00:00Z' {} +
(cd "$STAGE" && find . -type f | LC_ALL=C sort | zip -qX "$BUILD/fetcher.zip" -@)

echo "built $BUILD/fetcher.zip"
