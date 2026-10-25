#!/usr/bin/env bash
# Build mcp-server.zip inside the pinned Amazon Linux 2023 image that provided.al2023 runs.
# Fixed in-container paths and pinned image, rustup and toolchain make the binary reproducible.
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=v2/scripts/build_loader_zip.sh
source "$V2_ROOT/scripts/build_loader_zip.sh"
# Outside v2/infra/build, which holds exactly the release-delivered packages.
BUILD="$V2_ROOT/lambdas/mcp_server/target/lambda"
STAGE="$BUILD/mcp-server"
EPOCH="2020-01-01 00:00:00Z"
IMAGE="public.ecr.aws/amazonlinux/amazonlinux@sha256:06da5a3362eda00c5114227ac81abe56dd9b943395553b7c64a310457f4d9e2b" # 2023.12.20260918.0
RUSTUP_URL="https://static.rust-lang.org/rustup/archive/1.29.1/x86_64-unknown-linux-gnu/rustup-init"
RUSTUP_SHA256="dda7234360b7f578ca8b0ddcb80145646fa61a67c1720a5abc7051b35c9fcb71"
export TZ=UTC

rm -rf -- "$STAGE" "$BUILD/mcp-server.zip"
mkdir -p "$STAGE"
docker run --rm --env RUSTUP_URL="$RUSTUP_URL" --env RUSTUP_SHA256="$RUSTUP_SHA256" \
  --volume "$V2_ROOT/lambdas/mcp_server:/src:ro" --volume "$STAGE:/out" \
  "$IMAGE" bash -euo pipefail -c '
dnf install --assumeyes --quiet --setopt=install_weak_deps=False gcc >/dev/null
curl --fail --silent --show-error --location --proto =https --tlsv1.2 -o /tmp/rustup-init "$RUSTUP_URL"
echo "$RUSTUP_SHA256  /tmp/rustup-init" | sha256sum --check --status
chmod 0755 /tmp/rustup-init
/tmp/rustup-init -y --quiet --profile minimal --default-toolchain none >/dev/null
cd /src
/root/.cargo/bin/cargo build --release --locked --bin mcp_server --target-dir /tmp/target
install -m 0755 /tmp/target/release/mcp_server /out/bootstrap
chown --reference=/out /out/bootstrap
'
download_rds_ca_bundle "$STAGE/rds-ca-bundle.pem"
chmod 0644 "$STAGE/rds-ca-bundle.pem"
find "$STAGE" -exec touch -d "$EPOCH" {} +
(cd "$STAGE" && find . -type f | LC_ALL=C sort | zip -qX0 "$BUILD/mcp-server.zip" -@)

python3 -m zipfile -t "$BUILD/mcp-server.zip" >/dev/null
echo "built $BUILD/mcp-server.zip"
