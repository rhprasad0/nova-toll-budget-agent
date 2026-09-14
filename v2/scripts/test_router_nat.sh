#!/bin/bash
# Disposable network test; run from anywhere with Docker available.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
CONTAINER=$(docker run -d --privileged ubuntu:24.04 sleep infinity)
trap 'docker rm -f "$CONTAINER" >/dev/null' EXIT
docker exec "$CONTAINER" sh -c 'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nftables iproute2 iptables python3 curl systemd >/dev/null'
sed -n '/^#!\/bin\/bash/,/^NAT_SETUP/{ /^NAT_SETUP/d; p; }' "$ROOT/infra/router-nat.tf" | docker exec -i "$CONTAINER" sh -c 'cat > /router-nat.sh'
docker exec -i "$CONTAINER" bash <<'TEST'
set -euo pipefail
enter() { local ns=$1; shift; nsenter --net="/run/netns/$ns" -- "$@"; }
# Only service start is adapted for the container (systemd is not PID 1).
# Enable uses real systemctl; restart runs the checked-in unit's ExecStart.
mkdir /test-bin
cat > /test-bin/systemctl <<'SH'
#!/bin/bash
set -eu
case "$1" in
  daemon-reload) systemd-analyze verify /etc/systemd/system/tollchat-nat.service ;;
  enable) /usr/bin/systemctl enable "$2" ;;
  restart) $(sed -n 's/^ExecStart=//p' /etc/systemd/system/tollchat-nat.service) ;;
  *) exit 1 ;;
esac
SH
chmod +x /test-bin/systemctl
export PATH=/test-bin:$PATH
ip link add br-test type bridge
ip link set br-test up
for ns in router a c denied server; do
  ip netns add "$ns"
  ip link add "v-$ns" type veth peer name eth0 netns "$ns"
  ip link set "v-$ns" master br-test
  ip link set "v-$ns" up
  enter "$ns" ip link set lo up
  enter "$ns" ip link set eth0 up
done
enter router ip addr add 198.18.0.1/24 dev eth0
enter router ip route add default via 198.18.0.254
enter server ip addr add 198.18.0.2/24 dev eth0
for pair in 'a 224' 'c 225' 'denied 226'; do
  read -r ns octet <<<"$pair"
  enter "$ns" ip addr add "172.31.$octet.2/24" dev eth0
  enter "$ns" ip route add default via 198.18.0.1 dev eth0 onlink
  enter router ip route add "172.31.$octet.0/24" dev eth0
done
ip netns add tailnet
ip link add tailscale0 netns router type veth peer name eth0 netns tailnet
enter router ip addr add 100.64.0.1/24 dev tailscale0
enter router ip link set tailscale0 up
enter tailnet ip addr add 100.64.0.2/24 dev eth0
enter tailnet ip link set eth0 up
enter tailnet ip link set lo up
enter tailnet ip route add default via 100.64.0.1
# Reproduce the deployed Tailscale forwarding and exit-node masquerade rules.
enter router iptables -N ts-forward
enter router iptables -A FORWARD -j ts-forward
enter router iptables -A ts-forward -i tailscale0 -j MARK --set-xmark 0x40000/0xff0000
enter router iptables -A ts-forward -m mark --mark 0x40000/0xff0000 -j ACCEPT
enter router iptables -A ts-forward -s 100.64.0.0/10 -o tailscale0 -j DROP
enter router iptables -A ts-forward -o tailscale0 -j ACCEPT
enter router iptables -t nat -A POSTROUTING -m mark --mark 0x40000/0xff0000 -j MASQUERADE
enter server python3 -m http.server 443 --bind 198.18.0.2 >/tmp/server443.log 2>&1 &
enter server python3 -m http.server 80 --bind 198.18.0.2 >/tmp/server80.log 2>&1 &
sleep 1
probe() { enter "$1" curl --noproxy '*' -fsS --connect-timeout 1 --max-time 2 "http://198.18.0.2:$2" >/dev/null; }
for pass in 1 2 3; do
  if test "$pass" = 3; then
    # Simulate loss of kernel state at boot and execute the persisted unit.
    enter router nft delete table ip tollchat_nat
    enter router sysctl -w net.ipv4.ip_forward=0 >/dev/null
    enter router sysctl -p /etc/sysctl.d/90-tollchat-nat.conf
    enter router systemctl restart tollchat-nat.service
  else
    enter router bash /router-nat.sh
  fi
  probe a 443
  probe c 443
  if probe a 80 || probe denied 443; then echo 'unexpected forwarding allowed' >&2; exit 1; fi
  probe tailnet 80
  enter router iptables -C FORWARD -j ts-forward
  test -L /etc/systemd/system/multi-user.target.wants/tollchat-nat.service
done
# Without NAT the server has no route back to the private client; success above
# also establishes that replies were translated and forwarded correctly.
echo 'router-nat: both CIDRs, denied traffic, tailnet exit, repeat setup and boot reload PASS'
TEST
