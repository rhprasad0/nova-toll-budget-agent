FROM mcr.microsoft.com/devcontainers/python:1-3.13-bookworm

ARG NODE_MAJOR=22
ARG CODEX_VERSION=0.154.0
ARG AGENTMEMORY_VERSION=0.9.29

RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg postgresql-client unzip \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /etc/apt/keyrings/hashicorp.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/hashicorp.gpg] https://apt.releases.hashicorp.com bookworm main" > /etc/apt/sources.list.d/hashicorp.list \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && curl -fsSL https://pkgs.tailscale.com/stable/debian/bookworm.noarmor.gpg -o /etc/apt/keyrings/tailscale.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/tailscale.gpg] https://pkgs.tailscale.com/stable/debian bookworm main" > /etc/apt/sources.list.d/tailscale.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends awscli gh nodejs tailscale terraform \
    && npm install --global "@openai/codex@${CODEX_VERSION}" "@agentmemory/agentmemory@${AGENTMEMORY_VERSION}" "@agentmemory/mcp@${AGENTMEMORY_VERSION}" \
    && pip install --no-cache-dir uv==0.12.5 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN install -d -o vscode -g vscode /home/vscode/.local/share /home/vscode/.local/state /workspaces/nova-toll-budget-agent \
    && install -d -m 0700 /var/lib/tailscale

USER vscode
