#!/bin/sh
set -eu
ini=/tmp/pgbouncer.ini

render() {
  token="$(aws rds generate-db-auth-token --region us-east-1 --hostname "$FACTORY_RDS_HOST" \
    --port 5432 --username factory_sandbox)"
  umask 077
  cat >"$ini.new" <<EOF
[databases]
factory_sandbox = host=$FACTORY_RDS_HOST port=5432 dbname=factory_sandbox user=factory_sandbox password='$token'

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
unix_socket_dir =
auth_type = trust
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = session
max_db_connections = 15
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
