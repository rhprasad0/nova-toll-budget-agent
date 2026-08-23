#!/usr/bin/env bash
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$V2_ROOT/infra/build"
AGENT_STAGE="$BUILD/agentcore"
PROXY_STAGE="$BUILD/chat-proxy"
CA_URL="https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
CA_SHA256="e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
EPOCH="2020-01-01 00:00:00Z"

rm -rf "$AGENT_STAGE" "$PROXY_STAGE" \
  "$BUILD/agentcore.zip" "$BUILD/chat-proxy.zip" "$BUILD/AGENTCORE_SHA256SUMS"
mkdir -p "$AGENT_STAGE/agent" "$AGENT_STAGE/agent_tools" \
  "$AGENT_STAGE/agent-sops" "$PROXY_STAGE"

cp "$V2_ROOT"/agent/{__init__.py,agentcore_entrypoint.py,toll_agent.py} \
  "$AGENT_STAGE/agent/"
cp "$V2_ROOT"/agent_tools/*.py "$AGENT_STAGE/agent_tools/"
cp "$V2_ROOT/agent-sops/nova-toll-pricing-assistant.sop.md" \
  "$AGENT_STAGE/agent-sops/"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  "$CA_URL" -o "$AGENT_STAGE/rds-ca-bundle.pem"
echo "$CA_SHA256  $AGENT_STAGE/rds-ca-bundle.pem" | \
  sha256sum --check --status || {
    echo "RDS CA bundle digest mismatch; review AWS's CA rotation notice." >&2
    exit 1
  }

uv export --directory "$V2_ROOT" --frozen --no-dev --no-emit-project \
  --no-header --no-annotate --output-file "$BUILD/agentcore-requirements.txt"
uv pip install \
  --python-platform aarch64-manylinux_2_28 \
  --python-version 3.13 \
  --only-binary :all: \
  --target "$AGENT_STAGE" \
  -r "$BUILD/agentcore-requirements.txt"

npm ci --omit=dev --prefix "$V2_ROOT/lambdas/chat_proxy"
cp "$V2_ROOT/lambdas/chat_proxy/handler.mjs" "$PROXY_STAGE/"
cp -R "$V2_ROOT/lambdas/chat_proxy/node_modules" "$PROXY_STAGE/"

zip_stage() {
  local stage="$1" out="$2"
  find "$stage" -type f ! -name .lock -exec chmod 0644 {} +
  find "$stage" -type f -name '*.so.*' -exec chmod 0755 {} +
  find "$stage" -exec touch -d "$EPOCH" {} +
  (cd "$stage" && find . -type f | LC_ALL=C sort | zip -qX "$out" -@)
}

zip_stage "$AGENT_STAGE" "$BUILD/agentcore.zip"
zip_stage "$PROXY_STAGE" "$BUILD/chat-proxy.zip"
(cd "$BUILD" && sha256sum agentcore.zip chat-proxy.zip > AGENTCORE_SHA256SUMS)
echo "built $BUILD/agentcore.zip and $BUILD/chat-proxy.zip"
