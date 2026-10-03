FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv
FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates curl bubblewrap postgresql-client jq unzip groff-base proxychains4 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home factory \
    && mkdir -p /private/work /private/agent-state/home /private/agent-state/codex /private/agent-state/aws /private/agent-state/tailscale \
    && chmod 700 /private/agent-state /private/agent-state/aws /private/agent-state/tailscale \
    && printf 'strict_chain\ntcp_read_time_out 15000\ntcp_connect_time_out 5000\n[ProxyList]\nsocks5 127.0.0.1 1055\n' > /etc/factory-proxychains.conf \
    && chown -R factory:factory /private
RUN case "$(dpkg --print-architecture)" in \
      amd64) codex_arch=x86_64; codex_sha=4fcc47ab57f52ff75363951a8761146cd10c8288bd86fed45487dbb204a16b71 ;; \
      arm64) codex_arch=aarch64; codex_sha=7f0fe42ff22ecfa3a47bc4a34f5b22c4218b431a4ec0aba51c7d98299f07900c ;; \
      *) exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/openai/codex/releases/download/rust-v0.160.0/codex-package-${codex_arch}-unknown-linux-musl.tar.gz" -o /tmp/codex.tar.gz \
    && printf '%s  /tmp/codex.tar.gz\n' "$codex_sha" | sha256sum -c - \
    && tar -xzf /tmp/codex.tar.gz -C /usr/local --no-same-owner \
    && test -x /usr/local/bin/codex-code-mode-host \
    && codex --version \
    && codex-code-mode-host --help >/dev/null \
    && rm /tmp/codex.tar.gz \
    && printf '#!/bin/sh\nexec /opt/factory/v2/.venv/bin/python -m eval.factory.factory "$@"\n' > /usr/local/bin/factory \
    && chmod 755 /usr/local/bin/factory
RUN case "$(dpkg --print-architecture)" in \
      amd64) aws_arch=x86_64; aws_sha=ddd7a5aabf363f5b82085ef732c806d4fe73ad0d10e35cffedd5c3560f56a641 ;; \
      arm64) aws_arch=aarch64; aws_sha=11a035805d7cbcbb6f13d1fe1f3422ea198048e2b643ce3c7ea215cf0f21f35a ;; \
      *) exit 1 ;; \
    esac \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${aws_arch}-2.36.32.zip" -o /tmp/awscli.zip \
    && printf '%s  /tmp/awscli.zip\n' "$aws_sha" | sha256sum -c - \
    && unzip -q /tmp/awscli.zip -d /tmp/awscli \
    && /tmp/awscli/aws/install \
    && rm -rf /tmp/awscli /tmp/awscli.zip
RUN case "$(dpkg --print-architecture)" in \
      amd64) tailscale_arch=amd64; tailscale_sha=50748df1045e60b5b695f19f4c56b0da36c019948b440fb456b6584a50f0d8b9 ;; \
      arm64) tailscale_arch=arm64; tailscale_sha=9dd1e6a592a014bbaea0103167ffe299adeda4ba14e078ce9c2895364f6c4c3f ;; \
      *) exit 1 ;; \
    esac \
    && curl -fsSL "https://pkgs.tailscale.com/stable/tailscale_1.102.4_${tailscale_arch}.tgz" -o /tmp/tailscale.tgz \
    && printf '%s  /tmp/tailscale.tgz\n' "$tailscale_sha" | sha256sum -c - \
    && tar -xzf /tmp/tailscale.tgz -C /tmp \
    && install -m 755 "/tmp/tailscale_1.102.4_${tailscale_arch}/tailscale" "/tmp/tailscale_1.102.4_${tailscale_arch}/tailscaled" /usr/local/bin/ \
    && rm -rf /tmp/tailscale.tgz "/tmp/tailscale_1.102.4_${tailscale_arch}"
COPY runtime /opt/factory
WORKDIR /opt/factory/v2
RUN uv sync --frozen --python /usr/local/bin/python3.13 --no-managed-python \
    && mkdir -p /etc/codex \
    && printf 'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n' > /etc/codex/config.toml \
    && timeout 20s /opt/factory/v2/.venv/bin/python -m eval.factory.container_check \
    && chmod -R a-w /opt/factory \
    && mkdir -m 700 /run/tailscale \
    && ln -s /private/agent-state/tailscale/tailscaled.sock /run/tailscale/tailscaled.sock \
    && chown factory:factory /run/tailscale
ENV PATH="/opt/factory/v2/.venv/bin:/usr/local/codex-path:$PATH" \
    PYTHONPATH="/opt/factory/v2" \
    PYTHONDONTWRITEBYTECODE=1 \
    OTEL_SDK_DISABLED=true \
    HOME="/private/agent-state/home" \
    CODEX_HOME="/private/agent-state/codex" \
    AWS_CONFIG_FILE="/private/agent-state/aws/config" \
    AWS_SHARED_CREDENTIALS_FILE="/private/agent-state/aws/credentials" \
    AWS_PROFILE="nova-toll-dev" \
    AWS_REGION="us-east-1" \
    AWS_DEFAULT_REGION="us-east-1" \
    AWS_EC2_METADATA_DISABLED="true" \
    AWS_PAGER=""
USER factory
WORKDIR /private/work
CMD ["sleep", "infinity"]
