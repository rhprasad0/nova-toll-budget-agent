#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 || -z "${SUDO_USER:-}" ]]; then
  echo "run as: sudo factory/sandbox/setup.sh" >&2
  exit 1
fi
here="$(cd "$(dirname "$0")" && pwd)"
owner="$SUDO_USER"
owner_home="$(getent passwd "$owner" | cut -d: -f6)"
state="$owner_home/.local/state/factory-sandbox"
read_token="$owner_home/.config/factory/github-read-token"
declare -A ports=([factory-read]=18080 [factory-write]=18081)

if [[ ! -s "$read_token" ]]; then
  echo "missing $read_token: a fine-grained PAT for this repository with read-only" >&2
  echo "contents, issues and pull requests, mode 0600" >&2
  exit 1
fi

as_owner() { sudo -u "$owner" -H "$@"; }
as_user() {
  local user="$1" uid
  shift
  uid="$(id -u "$user")"
  sudo -u "$user" -H env XDG_RUNTIME_DIR="/run/user/$uid" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
    DOCKER_HOST="unix:///run/user/$uid/docker.sock" "$@"
}
subuids() { awk -F: -v user="$1" '$1 == user { printf "%s-%s", $2, $2 + $3 - 1 }' /etc/subuid; }

apt-get update -qq
apt-get install -y -qq uidmap passt jq nftables util-linux >/dev/null

install -m 644 "$here/systemd/50-factory0.netdev" "$here/systemd/50-factory0.network" \
  /etc/systemd/network/
networkctl reload
for _ in {1..20}; do
  ip -4 addr show factory0 2>/dev/null | grep -q 10.249.0.1 && break
  sleep 1
done
ip -4 addr show factory0 | grep -q 10.249.0.1

if [[ -f /etc/apparmor.d/usr.bin.rootlesskit ]]; then
  apparmor_parser -R /etc/apparmor.d/usr.bin.rootlesskit || true
  rm -f /etc/apparmor.d/usr.bin.rootlesskit
fi
apparmor_parser -r /etc/apparmor.d/rootlesskit

ant_version="$(sed -n 's/^ARG ANT_VERSION=//p' "$here/Dockerfile")"
ant_sha256="$(sed -n 's/^ARG ANT_SHA256=//p' "$here/Dockerfile")"
if [[ "$(/usr/local/bin/ant --version 2>/dev/null)" != *"$ant_version"* ]]; then
  archive="$(mktemp)"
  curl -fsSLo "$archive" \
    "https://github.com/anthropics/anthropic-cli/releases/download/v${ant_version}/ant_${ant_version}_linux_amd64.tar.gz"
  echo "$ant_sha256  $archive" | sha256sum --check --quiet
  tar -xzf "$archive" -C /usr/local/bin ant
  rm -f "$archive"
fi
install -D -m 755 -o root -g root "$here/spawn.sh" /usr/local/libexec/factory-spawn
install -D -m 755 -o root -g root "$here/clean.sh" /usr/local/libexec/factory-clean

for user in "${!ports[@]}"; do
  getent passwd "$user" >/dev/null || useradd --create-home --shell /bin/bash "$user"
  grep -q "^$user:" /etc/subuid || usermod --add-subuids "$(($(id -u "$user") * 65536))-$(($(id -u "$user") * 65536 + 65535))" "$user"
  grep -q "^$user:" /etc/subgid || usermod --add-subgids "$(($(id -u "$user") * 65536))-$(($(id -u "$user") * 65536 + 65535))" "$user"
done
install -d -m 755 /etc/factory-sandbox
sed -e "s/@READ_UIDS@/$(id -u factory-read), $(subuids factory-read)/" \
  -e "s/@WRITE_UIDS@/$(id -u factory-write), $(subuids factory-write)/" \
  "$here/egress.nft" >/etc/factory-sandbox/egress.nft
chmod 644 /etc/factory-sandbox/egress.nft
install -m 644 "$here/systemd/factory-egress.service" \
  "$here/systemd/factory-sessions-clean@.service" "$here/systemd/factory-sessions-clean@.timer" \
  /etc/systemd/system/
systemctl daemon-reload
systemctl enable factory-egress.service
nft -f /etc/factory-sandbox/egress.nft
systemctl start factory-egress.service

as_owner mkdir -p "$state/certs" "$state/flows-read" "$state/flows-write"
if [[ ! -f "$state/certs/mitmproxy-ca-cert.pem" ]]; then
  as_owner docker run --rm --user "$(id -u "$owner"):$(id -g "$owner")" \
    -v "$state/certs:/certs" mitmproxy/mitmproxy:12.2.3 \
    sh -c 'timeout 5 mitmdump --set confdir=/certs >/dev/null 2>&1; true'
fi
install -m 644 "$state/certs/mitmproxy-ca-cert.pem" /etc/factory-sandbox/mitm-ca.pem
cat /etc/ssl/certs/ca-certificates.crt /etc/factory-sandbox/mitm-ca.pem \
  >/etc/factory-sandbox/ca-bundle.pem
chmod 644 /etc/factory-sandbox/ca-bundle.pem
GITHUB_TOKEN="$(as_owner gh auth token)"
GITHUB_API_TOKEN="$(cat "$read_token")"
export GITHUB_TOKEN GITHUB_API_TOKEN
(cd "$here" && sudo --preserve-env=GITHUB_TOKEN,GITHUB_API_TOKEN -u "$owner" -H \
  docker compose up --detach --build --quiet-pull)
unset GITHUB_TOKEN GITHUB_API_TOKEN

for user in "${!ports[@]}"; do
  home="$(getent passwd "$user" | cut -d: -f6)"
  uid="$(id -u "$user")"
  proxy="http://10.249.0.1:${ports[$user]}"
  install -d -m 755 "/etc/systemd/system/user@$uid.service.d"
  printf '[Unit]\nRequires=factory-egress.service\nAfter=factory-egress.service\n' \
    >"/etc/systemd/system/user@$uid.service.d/factory-egress.conf"
  systemctl daemon-reload
  loginctl enable-linger "$user"
  for _ in {1..20}; do
    [[ -S "/run/user/$uid/bus" ]] && break
    sleep 1
  done

  units="$home/.config/systemd/user"
  as_user "$user" systemctl --user disable --now factory-sessions-clean.timer 'factory-worker@*' \
    >/dev/null 2>&1 || true
  rm -f "$units/factory-worker@.service" "$units/factory-sessions-clean.service" \
    "$units/factory-sessions-clean.timer" "$home/.local/bin/factory-spawn"
  install -d -o "$user" -g "$user" "$home/.config" "$home/.config/systemd" "$units" \
    "$units/docker.service.d" "$home/.docker" "$home/sessions"
  printf '[Service]\nEnvironment=HTTPS_PROXY=%s HTTP_PROXY=%s NO_PROXY=localhost,127.0.0.1\nEnvironment=SSL_CERT_FILE=/etc/factory-sandbox/ca-bundle.pem\n' \
    "$proxy" "$proxy" >"$units/docker.service.d/proxy.conf"
  printf '{"proxies": {"default": {"httpsProxy": "%s", "httpProxy": "%s", "noProxy": "localhost,127.0.0.1"}}}\n' \
    "$proxy" "$proxy" >"$home/.docker/config.json"
  chown "$user:$user" "$units/docker.service.d/proxy.conf" "$home/.docker/config.json"

  environment="/etc/factory-sandbox/$user.env"
  key="$(sed -n 's/^ANTHROPIC_ENVIRONMENT_KEY=//p' "$environment" 2>/dev/null || true)"
  id="$(sed -n 's/^ANTHROPIC_ENVIRONMENT_ID=//p' "$environment" 2>/dev/null || true)"
  umask 077
  printf 'FACTORY_PROXY=%s\nHTTPS_PROXY=%s\nNO_PROXY=localhost,127.0.0.1\nANTHROPIC_ENVIRONMENT_ID=%s\nANTHROPIC_ENVIRONMENT_KEY=%s\n' \
    "$proxy" "$proxy" "$id" "$key" >"$environment"
  if [[ "$user" == factory-write ]]; then
    database_url=postgresql://factory_sandbox@10.249.0.1:15432/factory_sandbox
  else
    database_url=postgresql://factory_sandbox_reader@10.249.0.1:15433/factory_sandbox
  fi
  echo "FACTORY_SANDBOX_DATABASE_URL=$database_url" >>"$environment"
  umask 022
  chmod 600 "$environment"
  sed -e "s/@USER@/$user/g" -e "s/@UID@/$uid/g" "$here/systemd/factory-worker.service.in" \
    >"/etc/systemd/system/factory-worker-${user#factory-}@.service"

  lab_environment="/etc/factory-sandbox/chaos-lab-${user#factory-}.env"
  key="$(sed -n 's/^ANTHROPIC_ENVIRONMENT_KEY=//p' "$lab_environment" 2>/dev/null || true)"
  id="$(sed -n 's/^ANTHROPIC_ENVIRONMENT_ID=//p' "$lab_environment" 2>/dev/null || true)"
  aws="$(grep -E '^AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY)=' "$lab_environment" 2>/dev/null || true)"
  umask 077
  printf 'ANTHROPIC_ENVIRONMENT_ID=%s\nANTHROPIC_ENVIRONMENT_KEY=%s\nFACTORY_REPO=rhprasad0/chaos-lab\n%s\n' \
    "$id" "$key" "$aws" | sed '/^$/d' >"$lab_environment"
  umask 022
  chmod 600 "$lab_environment"
  sed -e "s/@USER@/$user/g" -e "s/@UID@/$uid/g" -e "s/TollChat factory/chaos-lab factory/" \
    -e "\|^EnvironmentFile=|a EnvironmentFile=$lab_environment" \
    "$here/systemd/factory-worker.service.in" \
    >"/etc/systemd/system/factory-worker-chaos-lab-${user#factory-}@.service"

  if ! as_user "$user" docker info >/dev/null 2>&1; then
    as_user "$user" systemctl --user reset-failed docker.service 2>/dev/null || true
    as_user "$user" dockerd-rootless-setuptool.sh install --force >/dev/null
  fi
  as_user "$user" systemctl --user daemon-reload
  as_user "$user" systemctl --user restart docker.service
  as_user "$user" docker pull --quiet postgis/postgis:17-3.5 >/dev/null
  as_user "$user" docker pull --quiet "$(sed -n '1s/^FROM //p' "$here/Dockerfile")" >/dev/null
  build="$(mktemp -d)"
  cp "$here/Dockerfile" "$build/"
  install -m 644 /etc/factory-sandbox/mitm-ca.pem "$build/mitmproxy-ca-cert.pem"
  chmod 755 "$build"
  as_user "$user" docker build --quiet --tag factory-sandbox:latest \
    --build-context "certs=$build" "$build" >/dev/null
  rm -rf "$build"
  systemctl daemon-reload
  systemctl enable --now "factory-sessions-clean@$user.timer"
done

echo "ok: proxies on 10.249.0.1:18080 (read) and :18081 (write)"
echo "next: set ANTHROPIC_ENVIRONMENT_ID and ANTHROPIC_ENVIRONMENT_KEY in /etc/factory-sandbox/factory-{read,write}.env"
echo "and /etc/factory-sandbox/chaos-lab-{read,write}.env,"
echo "then: sudo systemctl enable --now factory-worker-read@{1,2} factory-worker-write@{1,2}"
echo "and, one slot each:"
echo "sudo systemctl enable --now factory-worker-chaos-lab-read@1 factory-worker-chaos-lab-write@1"
