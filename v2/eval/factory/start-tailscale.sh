#!/bin/sh
set -eu
umask 077

state_dir=/private/agent-state/tailscale
socket="$state_dir/tailscaled.sock"
mkdir -p "$state_dir"
chmod 700 "$state_dir"

if ! tailscale --socket="$socket" status --json >/dev/null 2>&1; then
    # Ignore terminal hangup before spawning the daemon; VS Code hooks use a PTY.
    nohup sh -c '"$@" &' sh tailscaled --tun=userspace-networking \
        --socks5-server=127.0.0.1:1055 --state="$state_dir/tailscaled.state" \
        --socket="$socket" </dev/null >"$state_dir/daemon.log" 2>&1
fi

# The inner shell expands its socket argument, not this shell.
# shellcheck disable=SC2016
if ! timeout 10s sh -c '
    until tailscale --socket="$1" status --json >/dev/null 2>&1; do sleep 0.1; done
' sh "$socket"; then
    printf 'Tailscale startup failed; inspect /private/agent-state/tailscale/daemon.log.\n' >&2
    exit 1
fi
