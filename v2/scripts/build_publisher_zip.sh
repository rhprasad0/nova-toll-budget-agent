#!/usr/bin/env bash
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$V2_ROOT/infra/build"
STAGE="$BUILD/publisher"
EPOCH="2020-01-01 00:00:00Z"
export TZ=UTC

rm -rf "$STAGE" "$BUILD/publisher.zip"
mkdir -p "$STAGE"
cp "$V2_ROOT/lambdas/publisher/costs.py" "$STAGE/"

find "$STAGE" -type f -exec chmod 0644 {} +
find "$STAGE" -exec touch -d "$EPOCH" {} +
(cd "$STAGE" && find . -type f | LC_ALL=C sort | zip -qX0 "$BUILD/publisher.zip" -@)
echo "built $BUILD/publisher.zip"
