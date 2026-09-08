#!/usr/bin/env bash
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$V2_ROOT/.." && pwd)"
BUILD="$V2_ROOT/infra/build"
RELEASE="$BUILD/release"
HEAD="$(git -C "$ROOT" rev-parse HEAD)"
if [[ -n "${GITHUB_SHA:-}" && "$GITHUB_SHA" != "$HEAD" ]]; then
  echo "GITHUB_SHA does not match the checked-out commit" >&2
  exit 1
fi
COMMIT="$HEAD"

if [[ ! "$COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "GITHUB_SHA must be a full lowercase commit SHA" >&2
  exit 1
fi

rm -rf -- "$RELEASE"
mkdir -p "$BUILD"
"$V2_ROOT/scripts/build_loader_zip.sh"
"$V2_ROOT/scripts/build_publisher_zip.sh"
"$V2_ROOT/scripts/build_agentcore_zips.sh"

for package in loader publisher agentcore chat-proxy; do
  test -s "$BUILD/$package.zip"
  python3 -m zipfile -t "$BUILD/$package.zip" >/dev/null
  if unzip -Z1 "$BUILD/$package.zip" | grep -E '(^|/)\.env($|/)' >/dev/null; then
    echo "package contains a .env entry: $package.zip" >&2
    exit 1
  fi
done

(cd "$BUILD" && sha256sum loader.zip publisher.zip agentcore.zip chat-proxy.zip > DEPLOYMENT_SHA256SUMS)

python3 "$V2_ROOT/scripts/verify_release_bundle.py" create \
  --root "$ROOT" --release "$RELEASE" --commit "$COMMIT"
echo "built immutable release bundle at $RELEASE"
