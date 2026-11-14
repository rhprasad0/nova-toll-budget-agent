# The factory sandbox: the toolchains and pinned checkers the required CI jobs
# use, plus Claude Code. Build from the repository root (see factory/setup.sh):
#   docker build -f factory/agent/Dockerfile --build-context certs=STATE/certs .
# The versions below must match CI; factory/host/test_factory.py checks them.
FROM rust:1.99.1-slim-trixie

ARG CLAUDE_CODE_VERSION=2.1.325
ARG NODE_VERSION=22.22.1
ARG NODE_SHA256=9a6bc82f9b491279147219f6a18add1e18424dce90d41d2a5fcd69d4924ba3aa
ARG TERRAFORM_VERSION=1.15.8
ARG TERRAFORM_SHA256=d25ce7b6902013ad905db3d2eab0be4cd905887fe88b81a6171b8d5503c31f3d
ARG PLAYWRIGHT_VERSION=1.63.0

# Debian trixie's python3 is 3.13, which v2 requires; uv never downloads one.
RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends ca-certificates curl git jq xxd zip unzip \
      xz-utils make gcc libc6-dev python3 python3-venv postgresql-client \
 && rm -rf /var/lib/apt/lists/* \
 && rustup component add rustfmt clippy

RUN curl -fsSLo /tmp/node.txz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && echo "${NODE_SHA256}  /tmp/node.txz" | sha256sum -c - \
 && tar -xJf /tmp/node.txz -C /usr/local --strip-components=1 && rm /tmp/node.txz
RUN curl -fsSLo /tmp/tf.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
 && echo "${TERRAFORM_SHA256}  /tmp/tf.zip" | sha256sum -c - \
 && unzip -q /tmp/tf.zip terraform -d /usr/local/bin && rm /tmp/tf.zip
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /usr/local/bin/
# The database tests drive their PostGIS containers through the host's Docker socket.
COPY --from=docker:28.5.1-cli /usr/local/bin/docker /usr/local/bin/docker
# Baked in, so the proxy need not allow GitHub release downloads.
COPY v2/scripts/install_check_tools.sh /tmp/
RUN /tmp/install_check_tools.sh /usr/local/bin && rm /tmp/install_check_tools.sh
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN npx --yes "playwright@${PLAYWRIGHT_VERSION}" install --with-deps chromium firefox \
 && chmod -R a+rX /opt/ms-playwright && rm -rf /root/.npm

# The proxy's CA, so every client trusts it through the OS store.
COPY --from=certs mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/factory-mitm.crt
RUN update-ca-certificates

RUN useradd --create-home --uid 1000 agent \
 && mkdir -p /work && chown agent:agent /work
COPY factory/agent/run-verify.sh /usr/local/bin/

USER agent
RUN curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_CODE_VERSION}"

ENV PATH="/home/agent/.local/bin:${PATH}" \
    CARGO_HOME=/home/agent/.cargo \
    HTTPS_PROXY=http://proxy:8080 \
    HTTP_PROXY=http://proxy:8080 \
    NO_PROXY=localhost,127.0.0.1,proxy \
    https_proxy=http://proxy:8080 \
    http_proxy=http://proxy:8080 \
    no_proxy=localhost,127.0.0.1,proxy \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    UV_NATIVE_TLS=1 \
    UV_PYTHON_DOWNLOADS=never \
    DISABLE_AUTOUPDATER=1
WORKDIR /work
