#!/usr/bin/env bash
# Idempotent setup on the factory machine: state directory, proxy CA, images,
# and the proxy. Run from the dispatcher's checkout of main.
set -euo pipefail
cd "$(dirname "$0")"

state="$HOME/.local/state/factory"
mkdir -p "$state/certs" "$state/flows" "$state/jobs"

if [[ ! -f "$state/certs/mitmproxy-ca-cert.pem" ]]; then
  docker run --rm --user "$(id -u):$(id -g)" -v "$state/certs:/certs" mitmproxy/mitmproxy:12.2.3 \
    sh -c 'timeout 5 mitmdump --set confdir=/certs >/dev/null 2>&1; true'
fi
test -f "$state/certs/mitmproxy-ca-cert.pem"

docker pull -q postgis/postgis:17-3.5 >/dev/null
docker build -q -t factory-agent:dev -f agent/Dockerfile \
  --build-context "certs=$state/certs" .. >/dev/null
docker compose up -d --build proxy
echo "ok: factory images built, proxy up"
