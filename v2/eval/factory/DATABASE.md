# Development data for eval authoring

The container includes AWS CLI 2.36.32, `psql`, `jq`, Tailscale 1.102.4, and
`proxychains4`. Development reads help author realistic frozen fixtures.
Calibration and application evaluations continue to replay fixtures and never
query a deployed database.

## Login and transport

The devcontainer starts its own Tailscale daemon in
[userspace networking mode](https://tailscale.com/docs/features/userspace-networking).
This works with rootless Docker: `--network=host` would still be inside the
rootless daemon's namespace and cannot inherit the host's site-1 route. The
daemon uses a container-local SOCKS5 listener at `127.0.0.1:1055`; no host
credentials/socket, TUN device, host networking, or added capability is needed.
Log this container into your existing tailnet as yourself:

```sh
tailscale --socket=/private/agent-state/tailscale/tailscaled.sock up \
  --accept-routes --hostname=tollchat-eval-factory
```

Open the printed login link on your host. The device must have access to the
existing development site-1 subnet route; follow the tailnet's normal device
approval process if needed. Do not change ACLs or provision a new subnet router.
State persists under `/private/agent-state/tailscale/`, so normal rebuilds do not
need a new login. The startup hook detaches the daemon from VS Code's terminal
and waits up to ten seconds for its local API. Plain `tailscale status` uses the
same socket through the image's standard socket symlink. To check or restart a
daemon that has exited, run:

```sh
sh /opt/factory/v2/eval/factory/start-tailscale.sh
tailscale status
```

`proxychains4` routes only the recipe's `psql` process through
this SOCKS listener; other model/AWS traffic uses ordinary container networking.

Inside the container, configure and authenticate your development SSO identity:

```sh
aws configure sso --profile nova-toll-dev --use-device-code --no-browser
aws sso login --profile nova-toll-dev --use-device-code --no-browser
```

Enter your development SSO portal/session details, choose account
`903859731897`, an existing role with development reader access, and default
region `us-east-1`. Use the printed browser link and code on your host. Configure
once; repeat `aws sso login` when the session expires. See the official
[AWS SSO setup guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html).

`AWS_CONFIG_FILE` and `AWS_SHARED_CREDENTIALS_FILE` point under
`/private/agent-state/aws/`; login caches stay under
`/private/agent-state/home/.aws/`. The same private volume preserves them across
rebuilds, and factory backups exclude all of these locations. Log in separately
to AWS and Tailscale after restoring into a fresh volume. Do not copy host
authentication caches, place credentials in the workspace, or ask for
credentials in agent chat.

## Fixed read boundary

Use only profile `nova-toll-dev`, region `us-east-1`, account `903859731897`, RDS
instance `nova-toll-db`, database `nova_toll_development`, and database login
`pricing_reader_development`. Stop on an identity, reader-grant, route, TLS, or
query error. Do not substitute production, an administrator, a migration role,
or a deployed password, and do not change IAM or database grants.

The kit includes committed schema references under
`/opt/factory/v2/eval/factory/database/`, with their commit and file hashes in
`manifest.json`. Read those definitions and the frozen tool schemas before
querying. They are documentation, not SQL to execute. If observed schemas differ,
inspect bounded `information_schema` metadata and report the difference.
Use the bundled prompt-point catalog when the reader cannot access oracle data;
do not elevate its privileges.

Run one bounded `SELECT`, read-only `WITH`, or non-executing `EXPLAIN` of a SELECT
per connection, using explicit columns, stable ordering, and `LIMIT 100` for row
results. Bound inputs to collecting aggregates to 100 rows. Avoid application
conversations, stored eval cases/results, writes, DDL, `COPY`, `CALL`, `DO`,
`EXPLAIN ANALYZE`, and user-defined functions whose checked-in definitions do not
establish appropriate read-only behavior.

## Connection recipe

This adapts the repository's development connectivity verification to the
container's userspace transport: discover only the fixed private instance,
derive the site-1 4via6 address, require a connected Tailscale peer serving that
route, check the pinned RDS CA, and generate a short-lived reader IAM token.
No endpoint, route, or token is printed. First run the identity SELECT
below; require the expected database and reader before authoring queries.
For each later query, replace only that SELECT with the bounded query you need.
Run the recipe with Bash even if your terminal is `/bin/sh`.

```sh
bash <<'SH'
set -euo pipefail
set +x
ca_file=$(mktemp)
trap 'unset DB_TOKEN PGPASSWORD; rm -f "$ca_file"' EXIT
trap 'printf "Development read failed; check login, reader access, route, TLS, or SQL.\n" >&2' ERR

account=$(aws sts get-caller-identity --profile nova-toll-dev --region us-east-1 \
  --query Account --output text 2>/dev/null)
test "$account" = 903859731897
instance=$(aws rds describe-db-instances --db-instance-identifier nova-toll-db \
  --profile nova-toll-dev --region us-east-1 --output json 2>/dev/null)
PGHOST=$(jq -er '.DBInstances | if length == 1 and .[0].DBInstanceStatus == "available" and .[0].PubliclyAccessible == false and .[0].Engine == "postgres" then .[0].Endpoint.Address else empty end' <<<"$instance")
case "$PGHOST" in nova-toll-db.*.us-east-1.rds.amazonaws.com) ;; *) exit 1 ;; esac
tailnet=$(tailscale --socket=/private/agent-state/tailscale/tailscaled.sock status --json 2>/dev/null)
PGHOSTADDR=$(python - "$PGHOST" "$tailnet" <<'PY'
import ipaddress
import json
import socket
import sys

status = json.loads(sys.argv[2])
if status.get("BackendState") != "Running":
    raise SystemExit(1)
addresses = {info[4][0] for info in socket.getaddrinfo(sys.argv[1], 5432, socket.AF_INET, socket.SOCK_STREAM)}
if len(addresses) != 1:
    raise SystemExit(1)
address = ipaddress.ip_address(addresses.pop())
if not address.is_private:
    raise SystemExit(1)
transport = ipaddress.ip_address(int(ipaddress.ip_network("fd7a:115c:a1e0:b1a::/64").network_address) | (1 << 32) | int(address))
development = ipaddress.ip_network("fd7a:115c:a1e0:b1a:0:1:ac1f:0/112")
if transport not in development or not any(
    peer.get("Online") and str(development) in peer.get("PrimaryRoutes", [])
    for peer in status.get("Peer", {}).values()
):
    raise SystemExit(1)
print(transport)
PY
)
curl --fail --silent --location --proto '=https' --tlsv1.2 \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o "$ca_file"
printf '%s  %s\n' fe45bbebf92ad3e27a583bbb2ddd1553c521ed4d49af5514dc0a40372ea5395c "$ca_file" \
  | sha256sum --check --status
export PGHOST PGHOSTADDR PGPORT=5432 PGDATABASE=nova_toll_development
export PGUSER=pricing_reader_development PGSSLMODE=verify-full PGSSLROOTCERT="$ca_file"
export PGCONNECT_TIMEOUT=5
DB_TOKEN=$(aws rds generate-db-auth-token --hostname "$PGHOST" --port 5432 \
  --username pricing_reader_development --profile nova-toll-dev --region us-east-1 2>/dev/null)
PGPASSWORD="$DB_TOKEN" timeout 25s proxychains4 -q -f /etc/factory-proxychains.conf \
  psql -X --set=ON_ERROR_STOP=1 --tuples-only --no-align \
  --command="BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '2s';
SET LOCAL idle_in_transaction_session_timeout = '20s';
SELECT current_database(), current_user;
ROLLBACK;" 2>/dev/null
SH
```

Interpret only the bounded result. Record the observation's UTC retrieval time
and relevant filters while authoring fixtures. Reconcile amounts and label
generated fixtures as synthetic; do not claim a hand-authored fixture was a
captured tool response. Keep raw observations and connection details out of
published artifacts. Freeze all case evidence before calibration; no live reads
belong in a frozen reference, actor, or application trial.
