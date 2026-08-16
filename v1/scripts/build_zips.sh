#!/usr/bin/env bash
# Build the Lambda and AgentCore deployment zips into infra/build/.
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
CA_URL="https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
CA_SHA256="e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
PY_VERSION="3.13"
PY_PLATFORM="x86_64-manylinux2014"       # Lambda runtime arch
AGENT_PLATFORM="aarch64-manylinux_2_28"  # AgentCore toolkit-compatible fallback
EPOCH="2020-01-01 00:00:00Z"             # deterministic zip mtime

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
   "$REPO/lambdas/loader/_bounds.py" \
   "$REPO/lambdas/loader/parse_csv.py" \
   "$REPO/lambdas/loader/parse_xml.py" \
   "$loader_stage/"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  "$CA_URL" -o "$loader_stage/rds-ca-bundle.pem"
echo "$CA_SHA256  $loader_stage/rds-ca-bundle.pem" | sha256sum --check --status || {
  echo "RDS CA bundle digest mismatch. Review AWS's CA rotation notice, update CA_SHA256, and commit the change." >&2
  exit 1
}
uv pip install \
  --require-hashes \
  --python-platform "$PY_PLATFORM" \
  --python-version "$PY_VERSION" \
  --only-binary :all: \
  --target "$loader_stage" \
  -r "$REPO/scripts/loader-requirements.txt"

# --- chat proxy: locked AWS SDK + private preview page ---
proxy_stage="$BUILD/chat-proxy"
mkdir -p "$proxy_stage/assets"
npm ci --omit=dev --prefix "$REPO/lambdas/chat_proxy"
cp "$REPO/lambdas/chat_proxy/handler.mjs" \
   "$REPO/site/preview.html" \
   "$REPO/site/preview.mjs" \
   "$REPO/site/faq.html" \
   "$proxy_stage/"
cp "$REPO/docs/legal/privacy.md" "$proxy_stage/privacy.txt"
cp "$REPO/docs/legal/terms.md" "$proxy_stage/terms.txt"
cp -R "$REPO/lambdas/chat_proxy/node_modules" "$proxy_stage/"
cp "$REPO/site/assets/chat-markdown-v1.mjs" "$proxy_stage/assets/"
cp "$REPO/site/assets/coverage-map-v2.mjs" "$proxy_stage/assets/"
cp -R "$REPO/site/assets/markdown-it-15.0.0" "$proxy_stage/assets/"
cp -R "$REPO/site/assets/maplibre-gl-6.0.0" "$proxy_stage/assets/"

# --- AgentCore direct code: application + locked ARM64 dependencies ---
agent_stage="$BUILD/agentcore"
mkdir -p "$agent_stage/agent" "$agent_stage/agent_tools" \
  "$agent_stage/oracles" "$agent_stage/agent-sops"
cp "$REPO"/agent/*.py "$agent_stage/agent/"
cp "$REPO"/agent_tools/*.py "$agent_stage/agent_tools/"
cp "$REPO"/oracles/*.json "$agent_stage/oracles/"
cp "$REPO/agent-sops/nova-toll-pricing-assistant.sop.md" "$agent_stage/agent-sops/"
cp "$loader_stage/rds-ca-bundle.pem" "$agent_stage/"
uv export --frozen --no-dev --no-emit-project --no-header --no-annotate \
  --output-file "$BUILD/agentcore-requirements.txt"
uv pip install \
  --python-platform "$AGENT_PLATFORM" \
  --python-version "$PY_VERSION" \
  --only-binary :all: \
  --target "$agent_stage" \
  -r "$BUILD/agentcore-requirements.txt"

# --- zip both, deterministically ---
zip_stage() {  # <stage_dir> <out.zip>
  local stage="$1" out="$2"
  find "$stage" -type f ! -name .lock -exec chmod 0644 {} +
  find "$stage" -type f -name '*.so.*' -exec chmod 0755 {} +
  find "$stage" -exec touch -d "$EPOCH" {} +
  ( cd "$stage" && find . -type f | LC_ALL=C sort | zip -qX "$out" -@ )
}
zip_stage "$fetcher_stage" "$BUILD/fetcher.zip"
zip_stage "$loader_stage" "$BUILD/loader.zip"
zip_stage "$proxy_stage" "$BUILD/chat-proxy.zip"
zip_stage "$agent_stage" "$BUILD/agentcore.zip"

echo "built:"
echo "  $BUILD/fetcher.zip          ($(unzip -l "$BUILD/fetcher.zip" | tail -1 | awk '{print $2}') files)"
echo "  $BUILD/loader.zip           ($(unzip -l "$BUILD/loader.zip"  | tail -1 | awk '{print $2}') files)"
echo "  $BUILD/chat-proxy.zip       ($(unzip -l "$BUILD/chat-proxy.zip" | tail -1 | awk '{print $2}') files)"
echo "  $BUILD/agentcore.zip        ($(unzip -l "$BUILD/agentcore.zip" | tail -1 | awk '{print $2}') files)"
echo
echo "apply with:"
echo "  cd infra && terraform apply \\"
echo "    -var fetcher_package_path=build/fetcher.zip \\"
echo "    -var loader_package_path=build/loader.zip \\"
echo "    -var agentcore_package_path=build/agentcore.zip \\"
echo "    -var chat_proxy_package_path=build/chat-proxy.zip"
