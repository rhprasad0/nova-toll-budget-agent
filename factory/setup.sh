#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

state="$HOME/.local/state/factory"
mkdir -p "$state/certs" "$state/flows" "$state/jobs"
[[ -f "$state/current-job" ]] || echo none >"$state/current-job"

if [[ ! -f "$state/certs/mitmproxy-ca-cert.pem" ]]; then
  docker run --rm --user "$(id -u):$(id -g)" -v "$state/certs:/certs" mitmproxy/mitmproxy:12.2.3 \
    sh -c 'timeout 5 mitmdump --set confdir=/certs >/dev/null 2>&1; true'
fi
test -f "$state/certs/mitmproxy-ca-cert.pem"

env_file="$HOME/.config/factory/factory.env"
test -f "$env_file" || { echo "missing $env_file (see compose.yaml)" >&2; exit 1; }

if [[ ! -f "$state/rds-ca.pem" ]]; then
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o "$state/rds-ca.pem.new"
  echo "90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b  $state/rds-ca.pem.new" |
    sha256sum --check || { echo "RDS CA bundle changed upstream; see v2/RUNBOOK.md" >&2; exit 1; }
  mv "$state/rds-ca.pem.new" "$state/rds-ca.pem"
fi

CLAUDE_CODE_OAUTH_TOKEN="$(AWS_PROFILE=factory aws ssm get-parameter \
  --name /nova-toll/factory/claude-code-oauth-token --with-decryption \
  --query Parameter.Value --output text)"
export CLAUDE_CODE_OAUTH_TOKEN
docker compose --env-file "$env_file" up -d --build
unset CLAUDE_CODE_OAUTH_TOKEN
echo "ok: factory images built, proxy and trace stack up"
