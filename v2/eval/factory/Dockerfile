FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv
FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home factory \
    && mkdir -p /private/work /private/agent-state/home /private/agent-state/codex \
    && chown -R factory:factory /private
COPY runtime /opt/factory
WORKDIR /opt/factory/v2
RUN uv sync --frozen --python /usr/local/bin/python3.13 --no-managed-python \
    && chmod -R a-w /opt/factory
ENV PATH="/opt/factory/v2/.venv/bin:$PATH" \
    PYTHONPATH="/opt/factory/v2" \
    PYTHONDONTWRITEBYTECODE=1 \
    OTEL_SDK_DISABLED=true \
    HOME="/private/agent-state/home" \
    CODEX_HOME="/private/agent-state/codex"
USER factory
WORKDIR /private/work
CMD ["sleep", "infinity"]
