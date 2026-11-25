"""mitmproxy addon: the sandbox's only way out.

- Only HTTPS to port 443 is allowed. Checks use the connection's real target
  (the CONNECT host), never the Host header, and a request whose Host header
  names a different host is refused.
- Hosts not in allowlist.txt get a 403, both at CONNECT and per request, unless it
  has a "*" entry: then any host without path entries is allowed. A host with path
  entries stays limited to those paths, and a host not written in lowercase without a
  trailing dot is refused, so no spelling of it slips past those limits. An entry
  with a path allows that host only for that path: a trailing slash allows paths
  under it, and no trailing slash allows that one file. Paths are decoded first,
  and empty, `.` or `..` segments are refused.
- With CLAUDE_CODE_OAUTH_TOKEN set, requests to api.anthropic.com lose whatever
  credential the client sent and get that subscription token as a bearer header, so
  the agent never holds it. Without it, the client's own credential passes through:
  a self-hosted sandbox worker authenticates with its environment key.
- Requests to github.com and api.github.com always lose the client's credential.
  GITHUB_TOKEN, when set, is added only to git smart-HTTP requests, so a sandbox can
  fetch and push without holding it but cannot use it on the API; GITHUB_API_TOKEN,
  when set, is added to api.github.com requests. Otherwise they go anonymous.
- ALLOWLIST names the allowlist file (default allowlist.txt). An entry followed by
  "GET" allows only GET and HEAD.
- Run with `--set rawtcp=false`, so traffic that is not HTTP is dropped instead of
  relayed past these checks.
- The checks and credential changes run in `requestheaders`, before mitmproxy sends
  anything upstream, so they hold when `stream_large_bodies` streams a request body.
- Every flow is appended to /state/flows/flows.jsonl, tagged with the current job id,
  with Anthropic's rate-limit headers (never credentials) on API responses.
"""

import base64
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
LINES = [
    line.split()
    for line in (HERE / os.environ.get("ALLOWLIST", "allowlist.txt"))
    .read_text()
    .splitlines()
    if line.strip() and not line.startswith("#")
]
ENTRIES = [words[0] for words in LINES]
READ_ONLY = {words[0] for words in LINES if words[1:] == ["GET"]}
ALLOWED = {entry for entry in ENTRIES if "/" not in entry}
ANY_HOST = "*" in ALLOWED
PATHS: dict[str, list[str]] = {}
for entry in ENTRIES:
    if "/" in entry:
        host, path = entry.split("/", 1)
        PATHS.setdefault(host, []).append("/" + path)
GIT_SERVICES = ("/info/refs", "/git-upload-pack", "/git-receive-pack")
API_HOST = "api.anthropic.com"
GITHUB_HOSTS = {"github.com", "api.github.com"}
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
    if port != PORT or host != host.lower().rstrip("."):
        return False
    if host in ALLOWED or (ANY_HOST and host not in PATHS):
        return True
    allowed = PATHS.get(host, [])
    return bool(allowed) and (path is None or _path_allowed(path, allowed))


def _read_only(host: str, path: str) -> bool:
    decoded = unquote(path.split("?", 1)[0])
    return host in READ_ONLY or any(
        entry.startswith(host + "/") and decoded.startswith(entry[len(host) :])
        for entry in READ_ONLY
    )


def http_connect(flow: Flow) -> None:
    if not _allowed(flow.request.host, flow.request.port, None):
        _deny(flow)
        _log(flow, allowed=False, kind="connect")


def requestheaders(flow: Flow) -> None:
    if _is_telemetry(flow):
        return
    req = flow.request
    claimed = (req.host_header or req.host).rsplit(":", 1)[0].strip("[]").lower()
    if (
        req.scheme != "https"
        or claimed != req.host.lower()
        or not _allowed(req.host, req.port, req.path)
        or (req.method not in {"GET", "HEAD"} and _read_only(req.host, req.path))
    ):
        _deny(flow)
        _log(flow, allowed=False, kind="request")
        return
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if req.host == API_HOST and token:
        for header in ("authorization", "x-api-key"):
            req.headers.pop(header, None)
        req.headers["authorization"] = f"Bearer {token}"
    if req.host in GITHUB_HOSTS:
        for header in ("authorization", "cookie"):
            req.headers.pop(header, None)
        git = os.environ.get("GITHUB_TOKEN")
        api = os.environ.get("GITHUB_API_TOKEN")
        service = req.path.split("?", 1)[0].endswith(GIT_SERVICES)
        if git and req.host == "github.com" and service:
            basic = base64.b64encode(f"x-access-token:{git}".encode()).decode()
            req.headers["authorization"] = f"Basic {basic}"
        elif api and req.host == "api.github.com":
            req.headers["authorization"] = f"Bearer {api}"


def response(flow: Flow) -> None:
    if (
        flow.response
        and flow.response.status_code == 403
        and flow.response.content == b"blocked by factory proxy\n"
    ):
        return  # already logged by the hook that blocked it
    _log(flow, allowed=True, kind="telemetry" if _is_telemetry(flow) else "request")
