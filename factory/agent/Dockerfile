FROM debian:trixie-slim

ARG CLAUDE_CODE_VERSION=2.1.325
ARG NODE_VERSION=22.22.1
ARG NODE_SHA256=9a6bc82f9b491279147219f6a18add1e18424dce90d41d2a5fcd69d4924ba3aa
ARG TERRAFORM_VERSION=1.15.8
ARG TERRAFORM_SHA256=d25ce7b6902013ad905db3d2eab0be4cd905887fe88b81a6171b8d5503c31f3d
ARG PLAYWRIGHT_VERSION=1.63.0

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends ca-certificates curl git jq xxd zip unzip \
      xz-utils make gcc libc6-dev python3 python3-venv postgresql-client \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSLo /tmp/node.txz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && echo "${NODE_SHA256}  /tmp/node.txz" | sha256sum -c - \
 && tar -xJf /tmp/node.txz -C /usr/local --strip-components=1 && rm /tmp/node.txz
RUN curl -fsSLo /tmp/tf.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
 && echo "${TERRAFORM_SHA256}  /tmp/tf.zip" | sha256sum -c - \
 && unzip -q /tmp/tf.zip terraform -d /usr/local/bin && rm /tmp/tf.zip
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /usr/local/bin/
COPY --from=docker:28.5.1-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:28.5.1-cli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins
COPY v2/scripts/install_check_tools.sh /tmp/
RUN /tmp/install_check_tools.sh /usr/local/bin && rm /tmp/install_check_tools.sh
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN npx --yes "playwright@${PLAYWRIGHT_VERSION}" install --with-deps chromium firefox \
 && chmod -R a+rX /opt/ms-playwright && rm -rf /root/.npm


RUN useradd --create-home --uid 1000 agent \
 && mkdir -p /work && chown agent:agent /work

USER agent
RUN curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_CODE_VERSION}"

ENV PATH="/home/agent/.local/bin:${PATH}" \
    DISABLE_AUTOUPDATER=1 \
    CHECKPOINT_DISABLE=1
WORKDIR /work
