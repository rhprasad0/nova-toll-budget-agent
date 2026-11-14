"""mitmproxy addon: the sandbox's only way out.

- Hosts not in allowlist.txt get a 403, both at CONNECT and per request. An entry
  with a path (host/prefix) allows that host only for paths under the prefix.
- Requests to api.anthropic.com lose whatever credential the client sent and get the
  real subscription token from the proxy's own environment as a bearer header, so the
  agent never holds it. Without a token they are refused.
- Every flow is appended to /state/flows/flows.jsonl, tagged with the current job id,
  with Anthropic's rate-limit headers (never credentials) on API responses.
"""

import importlib
import json
import os
import time
from pathlib import Path
from typing import Any

# mitmproxy exists only in the proxy image; the repository's type checks run without it.
http = importlib.import_module("mitmproxy.http")
Flow = Any  # mitmproxy.http.HTTPFlow

HERE = Path(__file__).parent
ENTRIES = [
    line.strip()
    for line in (HERE / "allowlist.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]
ALLOWED = {entry for entry in ENTRIES if "/" not in entry}
PREFIXES: dict[str, list[str]] = {}
for entry in ENTRIES:
    if "/" in entry:
        host, path = entry.split("/", 1)
        PREFIXES.setdefault(host, []).append("/" + path)
API_HOST = "api.anthropic.com"
OTLP_PORT = 4318  # the reverse listener that forwards telemetry to the collector
JOB_FILE = Path("/state/current-job")
LOG = Path("/state/flows/flows.jsonl")
LOG.parent.mkdir(parents=True, exist_ok=True)


def _job() -> str:
    try:
        return JOB_FILE.read_text().strip() or "none"
    except OSError:
        return "none"


def _log(flow: Flow, allowed: bool, kind: str) -> None:
    req = flow.request
    record = {
        "time_ms": int(time.time() * 1000),
        "job_id": _job(),
        "kind": kind,
        "client": flow.client_conn.peername[0] if flow.client_conn.peername else None,
        "host": req.pretty_host,
        "method": req.method,
        "path": req.path if kind != "connect" else None,
        "status": flow.response.status_code if flow.response else None,
        "bytes_out": len(req.raw_content or b""),
        "bytes_in": len(flow.response.raw_content or b"") if flow.response else 0,
        "allowed": allowed,
    }
    if flow.response and req.pretty_host == API_HOST:
        record["ratelimit"] = {
            k: v
            for k, v in flow.response.headers.items()
            if k.lower().startswith(("anthropic-ratelimit", "retry-after"))
        }
    with LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _is_telemetry(flow: Flow) -> bool:
    return (
        flow.client_conn.sockname is not None
        and flow.client_conn.sockname[1] == OTLP_PORT
    )


def _deny(flow: Flow) -> None:
    flow.response = http.Response.make(
        403, b"blocked by factory proxy\n", {"content-type": "text/plain"}
    )


def _allowed(host: str, path: str | None) -> bool:
    """path is None at CONNECT, before the request line is visible."""
    if host in ALLOWED:
        return True
    prefixes = PREFIXES.get(host, [])
    return bool(prefixes) and (path is None or path.startswith(tuple(prefixes)))


def http_connect(flow: Flow) -> None:
    if not _allowed(flow.request.pretty_host, None):
        _deny(flow)
        _log(flow, allowed=False, kind="connect")


def request(flow: Flow) -> None:
    if _is_telemetry(flow):
        return
    if not _allowed(flow.request.pretty_host, flow.request.path):
        _deny(flow)
        _log(flow, allowed=False, kind="request")
        return
    if flow.request.pretty_host == API_HOST:
        for header in ("authorization", "x-api-key"):
            flow.request.headers.pop(header, None)
        token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        if not token:
            _deny(flow)
            _log(flow, allowed=False, kind="request")
            return
        flow.request.headers["authorization"] = f"Bearer {token}"


def response(flow: Flow) -> None:
    if (
        flow.response
        and flow.response.status_code == 403
        and flow.response.content == b"blocked by factory proxy\n"
    ):
        return  # already logged by the hook that blocked it
    _log(flow, allowed=True, kind="telemetry" if _is_telemetry(flow) else "request")
