#!/bin/sh
set -eu
ini=/tmp/pgbouncer.ini
: "${RELAY_USER:?}" "${RELAY_PORT:?}" "${RELAY_CONNECTIONS:?}" "${RELAY_DATABASE:=factory_sandbox}"
printf '"%s" ""\n' "$RELAY_USER" >/tmp/userlist.txt

render() {
  token="$(aws rds generate-db-auth-token --region us-east-1 --hostname "$FACTORY_RDS_HOST" \
    --port 5432 --username "$RELAY_USER")"
  umask 077
  cat >"$ini.new" <<EOF
[databases]
$RELAY_DATABASE = host=$FACTORY_RDS_HOST port=5432 dbname=$RELAY_DATABASE user=$RELAY_USER password='$token'

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = $RELAY_PORT
unix_socket_dir =
auth_type = trust
auth_file = /tmp/userlist.txt
pool_mode = session
max_db_connections = $RELAY_CONNECTIONS
max_client_conn = 100
server_tls_sslmode = verify-full
server_tls_ca_file = /rds/rds-ca.pem
EOF
  mv "$ini.new" "$ini"
}

render
pgbouncer "$ini" &
pid=$!
trap 'kill -TERM "$pid"' TERM INT
(while sleep "${RELAY_REFRESH_SECONDS:-600}"; do render && kill -HUP "$pid"; done) &
wait "$pid"
