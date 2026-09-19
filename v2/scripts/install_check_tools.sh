#!/usr/bin/env bash
# Manual/CI setup only. Hooks never download or install tools.
set -euo pipefail
if [[ "$(uname -s)" != Linux ]]; then
  echo 'This installer supports Linux; install ShellCheck 0.11.0, actionlint 1.7.12 and Gitleaks 8.30.1 on other systems.' >&2
  exit 1
fi
case "$(uname -m)" in
  x86_64)
    shell_arch=x86_64; action_arch=amd64; leaks_arch=x64
    shell_sha=b7af85e41cc99489dcc21d66c6d5f3685138f06d34651e6d34b42ec6d54fe6f6
    action_sha=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
    leaks_sha=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
    ;;
  aarch64|arm64)
    shell_arch=aarch64; action_arch=arm64; leaks_arch=arm64
    shell_sha=68a8133197a50beb8803f8d42f9908d1af1c5540d4bb05fdfca8c1fa47decefc
    action_sha=325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6
    leaks_sha=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080
    ;;
  *) echo 'Unsupported Linux architecture.' >&2; exit 1 ;;
esac
install_dir="${1:-$HOME/.local/bin}"
workspace="$(mktemp -d)"
trap 'rm -rf -- "$workspace"' EXIT
mkdir -p -- "$install_dir"
install_tool() {
  local url="$1" checksum="$2" member="$3" name="$4"
  curl --fail --silent --show-error --location "$url" -o "$workspace/archive.tar.gz"
  printf '%s  %s\n' "$checksum" "$workspace/archive.tar.gz" | sha256sum --check --status
  tar -xzf "$workspace/archive.tar.gz" -C "$workspace" "$member"
  install -m 755 "$workspace/$member" "$install_dir/$name"
}
install_tool "https://github.com/koalaman/shellcheck/releases/download/v0.11.0/shellcheck-v0.11.0.linux.$shell_arch.tar.gz" "$shell_sha" shellcheck-v0.11.0/shellcheck shellcheck
install_tool "https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_$action_arch.tar.gz" "$action_sha" actionlint actionlint
install_tool "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_$leaks_arch.tar.gz" "$leaks_sha" gitleaks gitleaks
printf 'Installed ShellCheck 0.11.0, actionlint 1.7.12 and Gitleaks 8.30.1 in %s. Add this directory to PATH.\n' "$install_dir"
