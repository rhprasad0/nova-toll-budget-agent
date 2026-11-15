"""mitmproxy addon: the sandbox's only way out.

- Only HTTPS to port 443 is allowed. Checks use the connection's real target
  (the CONNECT host), never the Host header, and a request whose Host header
  names a different host is refused.
- Hosts not in allowlist.txt get a 403, both at CONNECT and per request. An entry
  with a path allows that host only for that path: a trailing slash allows paths
  under it, and no trailing slash allows that one file. Paths are decoded first,
  and empty, `.` or `..` segments are refused.
- Requests to api.anthropic.com lose whatever credential the client sent and get the
  real subscription token from the proxy's own environment as a bearer header, so the
  agent never holds it. Without a token they are refused.
- Run with `--set rawtcp=false`, so traffic that is not HTTP is dropped instead of
  relayed past these checks.
- Every flow is appended to /state/flows/flows.jsonl, tagged with the current job id,
  with Anthropic's rate-limit headers (never credentials) on API responses.
"""

import importlib
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

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
PATHS: dict[str, list[str]] = {}
for entry in ENTRIES:
    if "/" in entry:
        host, path = entry.split("/", 1)
        PATHS.setdefault(host, []).append("/" + path)
API_HOST = "api.anthropic.com"
PORT = 443
OTLP_PORT = 4318  # the reverse listener that forwards telemetry to the collector
JOB_FILE = Path("/state/current-job")
LOG = Path("/state/flows/flows.jsonl")


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
        "host": req.host,
        "port": req.port,
        "method": req.method,
        "path": req.path if kind != "connect" else None,
        "status": flow.response.status_code if flow.response else None,
        "bytes_out": len(req.raw_content or b""),
        "bytes_in": len(flow.response.raw_content or b"") if flow.response else 0,
        "allowed": allowed,
    }
    if flow.response and req.host == API_HOST:
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


def _path_allowed(path: str, allowed: list[str]) -> bool:
    decoded = unquote(path.split("?", 1)[0])
    if not decoded.startswith("/") or "\\" in decoded:
        return False
    segments = decoded.split("/")[1:]
    # A trailing slash leaves one empty last segment; any other empty segment is "//".
    if any(s in {"", ".", ".."} for s in segments[:-1]) or segments[-1] in {".", ".."}:
        return False
    return any(
        decoded.startswith(entry) if entry.endswith("/") else decoded == entry
        for entry in allowed
    )


def _allowed(host: str, port: int, path: str | None) -> bool:
    """path is None at CONNECT, before the request line is visible."""
    if port != PORT:
        return False
    if host in ALLOWED:
        return True
    allowed = PATHS.get(host, [])
    return bool(allowed) and (path is None or _path_allowed(path, allowed))


def http_connect(flow: Flow) -> None:
    if not _allowed(flow.request.host, flow.request.port, None):
        _deny(flow)
        _log(flow, allowed=False, kind="connect")


def request(flow: Flow) -> None:
    if _is_telemetry(flow):
        return
    req = flow.request
    claimed = (req.host_header or req.host).rsplit(":", 1)[0].strip("[]").lower()
    if (
        req.scheme != "https"
        or claimed != req.host.lower()
        or not _allowed(req.host, req.port, req.path)
    ):
        _deny(flow)
        _log(flow, allowed=False, kind="request")
        return
    if req.host == API_HOST:
        for header in ("authorization", "x-api-key"):
            req.headers.pop(header, None)
        token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        if not token:
            _deny(flow)
            _log(flow, allowed=False, kind="request")
            return
        req.headers["authorization"] = f"Bearer {token}"


def response(flow: Flow) -> None:
    if (
        flow.response
        and flow.response.status_code == 403
        and flow.response.content == b"blocked by factory proxy\n"
    ):
        return  # already logged by the hook that blocked it
    _log(flow, allowed=True, kind="telemetry" if _is_telemetry(flow) else "request")
