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
declare -A ports=([factory-read]=18080 [factory-write]=18081)

as_owner() { sudo -u "$owner" -H "$@"; }
as_user() {
  local user="$1" uid
  shift
  uid="$(id -u "$user")"
  sudo -u "$user" -H env XDG_RUNTIME_DIR="/run/user/$uid" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
    DOCKER_HOST="unix:///run/user/$uid/docker.sock" "$@"
}

apt-get update -qq
apt-get install -y -qq uidmap passt jq nftables >/dev/null

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

as_owner mkdir -p "$state/certs" "$state/flows-read" "$state/flows-write"
if [[ ! -f "$state/certs/mitmproxy-ca-cert.pem" ]]; then
  as_owner docker run --rm --user "$(id -u "$owner"):$(id -g "$owner")" \
    -v "$state/certs:/certs" mitmproxy/mitmproxy:12.2.3 \
    sh -c 'timeout 5 mitmdump --set confdir=/certs >/dev/null 2>&1; true'
fi
install -d -m 755 /etc/factory-sandbox
install -m 644 "$state/certs/mitmproxy-ca-cert.pem" /etc/factory-sandbox/mitm-ca.pem
cat /etc/ssl/certs/ca-certificates.crt /etc/factory-sandbox/mitm-ca.pem \
  >/etc/factory-sandbox/ca-bundle.pem
chmod 644 /etc/factory-sandbox/ca-bundle.pem
token="$(as_owner gh auth token)"
(cd "$here" && as_owner env GITHUB_TOKEN="$token" docker compose up --detach --build --quiet-pull)
unset token

for user in "${!ports[@]}"; do
  getent passwd "$user" >/dev/null || useradd --create-home --shell /bin/bash "$user"
  grep -q "^$user:" /etc/subuid || usermod --add-subuids "$(($(id -u "$user") * 65536))-$(($(id -u "$user") * 65536 + 65535))" "$user"
  grep -q "^$user:" /etc/subgid || usermod --add-subgids "$(($(id -u "$user") * 65536))-$(($(id -u "$user") * 65536 + 65535))" "$user"
done
install -m 644 "$here/egress.nft" /etc/factory-sandbox/egress.nft
install -m 644 "$here/systemd/factory-egress.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now factory-egress.service
systemctl restart factory-egress.service

for user in "${!ports[@]}"; do
  home="$(getent passwd "$user" | cut -d: -f6)"
  proxy="http://10.249.0.1:${ports[$user]}"
  loginctl enable-linger "$user"
  uid="$(id -u "$user")"
  for _ in {1..20}; do
    [[ -S "/run/user/$uid/bus" ]] && break
    sleep 1
  done
  units="$home/.config/systemd/user"
  install -d -o "$user" -g "$user" "$home/.config" "$home/.config/factory" "$units" \
    "$units/docker.service.d" "$home/.local" "$home/.local/bin" "$home/sessions"
  printf '[Service]\nEnvironment=HTTPS_PROXY=%s HTTP_PROXY=%s NO_PROXY=localhost,127.0.0.1\n' \
    "$proxy" "$proxy" >"$units/docker.service.d/proxy.conf"
  printf 'FACTORY_PROXY=%s\nHTTPS_PROXY=%s\nNO_PROXY=localhost,127.0.0.1\n' "$proxy" "$proxy" \
    >"$home/.config/factory/proxy.env"
  install -d -o "$user" -g "$user" "$home/.docker"
  printf '{"proxies": {"default": {"httpsProxy": "%s", "httpProxy": "%s", "noProxy": "localhost,127.0.0.1"}}}\n' \
    "$proxy" "$proxy" >"$home/.docker/config.json"
  [[ -f "$home/.config/factory/environment.env" ]] ||
    printf 'ANTHROPIC_ENVIRONMENT_ID=\nANTHROPIC_ENVIRONMENT_KEY=\n' \
      >"$home/.config/factory/environment.env"
  chmod 600 "$home/.config/factory/environment.env"
  install -m 755 "$here/spawn.sh" "$home/.local/bin/factory-spawn"
  install -m 644 "$here/systemd/factory-worker@.service" \
    "$here/systemd/factory-sessions-clean.service" \
    "$here/systemd/factory-sessions-clean.timer" "$units/"
  chown -R "$user:$user" "$home/.config" "$home/.local" "$home/.docker"

  if ! as_user "$user" docker info >/dev/null 2>&1; then
    as_user "$user" systemctl --user reset-failed docker.service 2>/dev/null || true
    as_user "$user" dockerd-rootless-setuptool.sh install --force >/dev/null
  fi
  as_user "$user" systemctl --user daemon-reload
  as_user "$user" systemctl --user restart docker.service
  as_user "$user" systemctl --user enable --now factory-sessions-clean.timer
  as_user "$user" docker pull --quiet postgis/postgis:17-3.5 >/dev/null
  as_user "$user" docker pull --quiet "$(sed -n '1s/^FROM //p' "$here/Dockerfile")" >/dev/null
  build="$(mktemp -d)"
  cp "$here/Dockerfile" "$build/"
  install -m 644 /etc/factory-sandbox/mitm-ca.pem "$build/mitmproxy-ca-cert.pem"
  chmod 755 "$build"
  as_user "$user" docker build --quiet --tag factory-sandbox:latest \
    --build-context "certs=$build" "$build" >/dev/null
  rm -rf "$build"
done

echo "ok: proxies on 10.249.0.1:18080 (read) and :18081 (write)"
echo "next: put each environment's ID and key in ~factory-{read,write}/.config/factory/environment.env,"
echo "then: sudo -u factory-read  XDG_RUNTIME_DIR=/run/user/\$(id -u factory-read)  systemctl --user enable --now factory-worker@{1,2}"
echo "and:  sudo -u factory-write XDG_RUNTIME_DIR=/run/user/\$(id -u factory-write) systemctl --user enable --now factory-worker@{1,2}"
