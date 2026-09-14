locals {
  router_nat_setup = <<-NAT_SETUP
#!/bin/bash
# Shared by first boot and the reviewed SSM in-place setup. No Tailscale keys.
set -euo pipefail
trap 'echo "router-nat: setup failed at line $LINENO" >&2' ERR

command -v nft >/dev/null || dnf install -y nftables
UPLINK=$(ip -4 route show default | awk '{for (i=1;i<NF;i++) if ($i=="dev") print $(i+1)}')
[[ "$UPLINK" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'router-nat: expected one default interface' >&2; exit 1; }

install -d -m 0755 /etc/nftables
cat > /etc/nftables/tollchat-nat.nft <<EOF
add table ip tollchat_nat
flush table ip tollchat_nat
table ip tollchat_nat {
  chain forward {
    type filter hook forward priority 10; policy accept;
    # EC2 uses the same interface for private ingress and internet egress.
    # Tailscale traffic traverses tailscale0 and keeps its existing policy.
    iifname "$UPLINK" oifname "$UPLINK" jump private_egress
  }
  chain private_egress {
    ct state invalid counter drop
    # Do not turn the router into a path to metadata, private VPCs, or tailnets.
    ip saddr { 172.31.224.0/24, 172.31.225.0/24 } ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/3 } counter drop
    ip saddr { 172.31.224.0/24, 172.31.225.0/24 } tcp dport 443 ct state { new, established } counter accept
    ip daddr { 172.31.224.0/24, 172.31.225.0/24 } ct state { established, related } counter accept
    counter drop
  }
  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    iifname "$UPLINK" oifname "$UPLINK" ip saddr { 172.31.224.0/24, 172.31.225.0/24 } tcp dport 443 counter masquerade
  }
}
EOF

# Check before loading. The batch replaces only our table, atomically.
nft --check --file /etc/nftables/tollchat-nat.nft
cat > /etc/systemd/system/tollchat-nat.service <<'EOF'
[Unit]
Description=TollChat private HTTPS NAT
Wants=network-online.target
After=network-online.target
Before=tailscaled.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft --file /etc/nftables/tollchat-nat.nft
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
echo 'net.ipv4.ip_forward = 1' > /etc/sysctl.d/90-tollchat-nat.conf
sysctl -p /etc/sysctl.d/90-tollchat-nat.conf
systemctl daemon-reload
systemctl enable tollchat-nat.service
systemctl restart tollchat-nat.service
echo 'router-nat: HTTPS forwarding configured'
NAT_SETUP
}
