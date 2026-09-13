# Development container

This configuration keeps the checkout and developer state in Docker named
volumes. The host seed checkout is used only by VS Code to read this directory;
it is not mounted into the container.

## Create the container

1. In host VS Code User settings, set:

   ```json
   "dev.containers.copyGitConfig": false,
   "dev.containers.gitCredentialHelperConfigLocation": "none"
   ```

2. Fully quit every VS Code process. From a host Bash shell, privately enter the
   Context7 key, then launch the trusted seed checkout without an SSH agent:

   ```sh
   read -rsp "Context7 API key: " CONTEXT7_API_KEY
   export CONTEXT7_API_KEY
   printf '\n'
   env -u SSH_AUTH_SOCK code /path/to/trusted/nova-toll-budget-agent
   unset CONTEXT7_API_KEY
   ```

3. Choose **Dev Containers: Reopen in Container**. Do **not** choose **Clone
   Repository in Container Volume**; this configuration already owns the one
   workspace volume.
4. The first create clones the fixed HTTPS repository into an empty
   `nova-toll-budget-agent-workspace` volume. Later creates reuse it. A
   non-empty volume without `.git` fails without changing its contents.

These settings prevent VS Code from copying host Git configuration or adding
its host-backed credential helper. Fully quitting and launching with
`SSH_AUTH_SOCK` unset prevents the existing VS Code process environment from
forwarding the host SSH agent. The host-side initialization check fails visibly
before container creation if the socket variable is still set; it only reads
that variable and does not copy source or authenticate.

The hidden prompt keeps the Context7 key out of shell history and command
arguments. `remoteEnv` forwards only `CONTEXT7_API_KEY` so the remote Codex
extension can inherit it, and the Context7 MCP declaration allows only that
named variable through to its process. This is the narrow exception to the
no-host-credential-forwarding rule: the value is not stored in the repository,
image, Docker configuration, or named volumes, but processes running as the
same `vscode` user can read their environment. Repeat the private launch after
fully quitting VS Code; do not print the variable or persist it in a shell file.

Interactive work runs as the non-root `vscode` user. Authenticate only when
needed, from inside the container:

```sh
codex login
gh auth login
aws configure sso --profile nova-toll
aws configure sso --profile nova-toll-dev
aws configure sso --profile nova-toll-prod
aws sso login --profile nova-toll-dev
sudo tailscale up
```

Start Codex from `/workspaces/nova-toll-budget-agent` and approve its trust
prompt for that exact checkout. Codex intentionally disables the repository's
`.codex/config.toml`, including its MCP servers, until the project is trusted.

`nova-toll` is for the local agent console. `nova-toll-dev` is for development
operations and the AWS MCP. `nova-toll-prod` is only for separately authorized
production procedures. Having a profile or logging in does not authorize a
deployment or migration. Setup does not retrieve SSM secrets; production work
remains governed by [the production runbook](../v2/RUNBOOK.md) and protected
workflows.

## Complete agentmemory onboarding

Agentmemory starts in keyless mode before this setup. To enable the selected
Codex plugin and its token-spending compression and context features, run these
commands in order from the container shell:

```sh
codex plugin marketplace add rohitg00/agentmemory
codex plugin add agentmemory@agentmemory
```

The OpenAI API key is separate from Codex subscription login. Create its private
configuration in the persistent home volume, then edit it without putting the
key in a command argument or shell history:

```sh
install -d -m 700 ~/.agentmemory
umask 077
touch ~/.agentmemory/.env
chmod 600 ~/.agentmemory/.env
${EDITOR:-vi} ~/.agentmemory/.env
```

In the editor, add these three assignments, replacing the placeholder with the
key before saving:

```text
OPENAI_API_KEY=<enter privately in the editor>
AGENTMEMORY_AUTO_COMPRESS=true
AGENTMEMORY_INJECT_CONTEXT=true
```

Do not print the file or environment, and do not put the key in repository,
image, Docker, command-line, history, or log content. Processes running as the
same `vscode` user can read this key. Both enabled agentmemory features spend
OpenAI API tokens.

Choose **Dev Containers: Restart Container** to restart agentmemory and load the
file, then close the current Codex session and start a fresh one. Verify
`codex plugin list`, the loopback health check below, and—without displaying the
file, environment, or key—that plugin status reports both features enabled.
Save and recall one benign observation to confirm the hooks. Authentication,
quota, hook, or compression errors are failures; review only sanitized status
or logs.

## Persistence and checks

- `nova-toll-budget-agent-workspace` contains the writable checkout.
- `nova-toll-dev-home` contains Codex, agentmemory, AWS, GitHub, and shell state.
- `nova-toll-tailscale` contains Tailscale state.

Credentials are entered interactively and remain in the named home or
Tailscale state volume. The transient Context7 variable is the exception
described above and is not persisted. The volumes are not automatically backed
up; commit work that must survive volume deletion. Do not copy or mount host
credentials into the container.

After reopening, verify the boundary and toolchain:

```sh
id -u                                      # nonzero
for path in /workspaces/nova-toll-budget-agent /home/vscode /var/lib/tailscale; do
  findmnt -no SOURCE,FSTYPE --target "$path"
done
test ! -S /var/run/docker.sock
test ! -S "/run/user/$(id -u)/docker.sock"
! command -v docker
test -z "${SSH_AUTH_SOCK:-}"
test -z "$(find /tmp -maxdepth 1 -type s -name 'vscode-ssh-auth-*.sock' -print -quit)"
if git config --show-origin --get-all credential.helper 2>/dev/null | grep -Eiq 'vscode|dev.?container'; then
  echo "VS Code-backed Git credential helper is present" >&2
  exit 1
fi
test -n "${CONTEXT7_API_KEY:-}"
codex mcp get context7
python3 --version
uv --version
node --version
npm --version
terraform version
git --version
gh --version
aws --version
psql --version
tailscale version
codex --version
curl -fsS http://127.0.0.1:3111/agentmemory/livez
sudo tailscale status
```

The SSH checks must produce no output. Run `gh auth login` inside the container;
it is the only GitHub credential path for this environment. Do not enable host
Git credential or SSH-agent forwarding. The Context7 checks confirm only that
the variable and inherited-environment declaration exist; they do not print the
key. Do not use `env`, `printenv`, `set`, or `echo` to inspect it.

On the host, use a separate clean shell with `CONTEXT7_API_KEY` unset for
`devcontainer read-configuration --workspace-folder .`, `devcontainer build
--workspace-folder .`, and Docker inspection; resolved configuration output
must never be captured while the key is present. Inspection should show only
the three named volumes, `/dev/net/tun`, `NET_ADMIN`, and `NET_RAW`—no bind,
host checkout, Docker socket, host network, or privileged mode.

From `v2/`, run `uv sync --locked`, Ruff, format, Pyright, the offline eval
check, and the documented Node tests. Docker/PostGIS tests, including
`scripts/run_db_tests.sh`, are intentionally unavailable because this container
does not expose Docker.
