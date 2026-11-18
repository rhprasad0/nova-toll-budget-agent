FROM ghcr.io/rhprasad0/nova-toll-budget-agent/toolchain@sha256:c8d9d79225fb2a6715221cc6b90ee05ab2debdbd169f88df8ce04db548dabdd3

ARG ANT_VERSION=2.11.0
ARG ANT_SHA256=dd04cbd77fae03b7704423658b01a2c552e29cd6729b6c224167e9a5e98febb6

USER root
COPY --from=certs mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/factory-mitm.crt
RUN update-ca-certificates && mkdir -p /mnt/memory /workspace
RUN curl -fsSLo /tmp/ant.tgz "https://github.com/anthropics/anthropic-cli/releases/download/v${ANT_VERSION}/ant_${ANT_VERSION}_linux_amd64.tar.gz" \
 && echo "${ANT_SHA256}  /tmp/ant.tgz" | sha256sum -c - \
 && tar -xzf /tmp/ant.tgz -C /usr/local/bin ant && rm /tmp/ant.tgz
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    UV_SYSTEM_CERTS=1 \
    GIT_TERMINAL_PROMPT=0 \
    NO_PROXY=localhost,127.0.0.1 \
    no_proxy=localhost,127.0.0.1
WORKDIR /workspace
ENTRYPOINT ["ant", "beta:worker", "run", "--workdir", "/workspace"]
