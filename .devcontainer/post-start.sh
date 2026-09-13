#!/usr/bin/env bash
set -euo pipefail

tailscale_log=/tmp/tailscaled.log
tailscale_status=/tmp/tailscale-status.json
tailscale_socket=/var/run/tailscale/tailscaled.sock
agentmemory_data="$HOME/.local/share/agentmemory"
agentmemory_log="$HOME/.local/state/agentmemory.log"

sudo install -d -m 0755 /var/run/tailscale
tailscale_running=false
if timeout 2 sudo tailscale --socket="$tailscale_socket" status --json >"$tailscale_status" 2>&1; then
  tailscale_running=true
elif grep -q '"BackendState"' "$tailscale_status"; then
  tailscale_running=true
fi
if [[ "$tailscale_running" != true ]]; then
  : >"$tailscale_log"
  sudo tailscaled --state=/var/lib/tailscale/tailscaled.state --socket="$tailscale_socket" >"$tailscale_log" 2>&1 &
fi

tailscale_ready=false
for _ in $(seq 1 20); do
  if timeout 2 sudo tailscale --socket="$tailscale_socket" status --json >"$tailscale_status" 2>&1 || grep -q '"BackendState"' "$tailscale_status"; then
    tailscale_ready=true
    break
  fi
  sleep 1
done
if [[ "$tailscale_ready" != true ]]; then
  echo "Tailscale daemon did not become ready." >&2
  tail -n 100 "$tailscale_log" >&2
  exit 1
fi
if grep -q '"BackendState": "NeedsLogin"' "$tailscale_status"; then
  echo "Tailscale is ready but not enrolled; run: sudo tailscale up"
fi

mkdir -p "$agentmemory_data" "$(dirname "$agentmemory_log")"
if ! curl --max-time 2 -fsS http://127.0.0.1:3111/agentmemory/livez >/dev/null 2>&1; then
  : >"$agentmemory_log"
  (cd "$agentmemory_data" && agentmemory --data-dir "$agentmemory_data") >"$agentmemory_log" 2>&1 &
fi

for _ in $(seq 1 30); do
  if curl --max-time 2 -fsS http://127.0.0.1:3111/agentmemory/livez >/dev/null 2>&1; then
    exit 0
  fi
  sleep 1
done

echo "Agentmemory did not become healthy on loopback." >&2
tail -n 100 "$agentmemory_log" >&2
exit 1
