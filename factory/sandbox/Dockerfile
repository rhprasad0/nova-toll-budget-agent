FROM ghcr.io/rhprasad0/nova-toll-budget-agent/toolchain@sha256:c8d9d79225fb2a6715221cc6b90ee05ab2debdbd169f88df8ce04db548dabdd3

ARG ANT_VERSION=2.11.0
ARG ANT_SHA256=dd04cbd77fae03b7704423658b01a2c552e29cd6729b6c224167e9a5e98febb6
ARG GH_VERSION=2.103.3
ARG GH_SHA256=4c806978ffce1cec70853302a56d70ac6da4f19bae7adca4e1a8ab00633dd91d

USER root
COPY --from=certs mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/factory-mitm.crt
RUN update-ca-certificates && mkdir -p /mnt/memory /workspace
RUN curl -fsSLo /tmp/ant.tgz "https://github.com/anthropics/anthropic-cli/releases/download/v${ANT_VERSION}/ant_${ANT_VERSION}_linux_amd64.tar.gz" \
 && echo "${ANT_SHA256}  /tmp/ant.tgz" | sha256sum -c - \
 && tar -xzf /tmp/ant.tgz -C /usr/local/bin ant && rm /tmp/ant.tgz
RUN curl -fsSLo /tmp/gh.tgz "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" \
 && echo "${GH_SHA256}  /tmp/gh.tgz" | sha256sum -c - \
 && tar -xzf /tmp/gh.tgz -C /usr/local/bin --strip-components=2 "gh_${GH_VERSION}_linux_amd64/bin/gh" && rm /tmp/gh.tgz
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    UV_SYSTEM_CERTS=1 \
    GIT_TERMINAL_PROMPT=0 \
    NO_PROXY=localhost,127.0.0.1 \
    no_proxy=localhost,127.0.0.1
WORKDIR /workspace
ENV PATH="/usr/local/bin:/usr/bin:/bin"
ENTRYPOINT ["ant", "beta:worker", "run", "--workdir", "/workspace"]
