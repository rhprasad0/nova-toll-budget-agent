"""Loopback-only browser console for exercising the TollChat agent locally."""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from strands.telemetry import StrandsTelemetry
from toll_agent import build_agent

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
from rds_ci_test_support import configure_pricing_reader_rds_env

_HTML_PATH = Path(__file__).with_suffix(".html")
_CA_BUNDLE_PATH = _REPO_ROOT / "infra/build/loader/rds-ca-bundle.pem"
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_MAX_MESSAGE_CHARS = 8_000


def configure_local_pricing_env() -> None:
    """Discover read-only RDS settings needed by the local console."""
    if not _CA_BUNDLE_PATH.exists():
        raise FileNotFoundError(
            f"{_CA_BUNDLE_PATH} missing -- run scripts/build_zips.sh first"
        )
    os.environ.setdefault("AWS_PROFILE", "nova-toll")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("DB_NAME", "nova_toll")
    os.environ.setdefault("DB_USER", "pricing_reader")
    os.environ.setdefault("DB_CA_BUNDLE_PATH", str(_CA_BUNDLE_PATH))
    configure_pricing_reader_rds_env()


class DevChat:
    """In-memory conversations plus append-only, local raw telemetry."""

    def __init__(
        self,
        agent_factory: Callable[..., Any] = build_agent,
        telemetry_path: Path = Path(".tollchat/telemetry.jsonl"),
    ) -> None:
        self.agent_factory = agent_factory
        self.telemetry_path = telemetry_path
        self.sessions: dict[str, tuple[Any, threading.Lock]] = {}
        self.sessions_lock = threading.Lock()
        self.telemetry_lock = threading.Lock()

    def chat(self, session_id: str, message: str) -> dict[str, Any]:
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid session id")
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if not (message := message.strip()):
            raise ValueError("message is required")
        if len(message) > _MAX_MESSAGE_CHARS:
            raise ValueError(f"message must be at most {_MAX_MESSAGE_CHARS} characters")

        agent, lock = self._session(session_id)
        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        try:
            with lock:
                result = agent(message)
                answer = str(result).strip()
                record = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "request_id": request_id,
                    "session_id": session_id,
                    "prompt": message,
                    "answer": answer,
                    "result": result.to_dict(),
                    "metrics": result.metrics.get_summary(),
                    "messages": copy.deepcopy(agent.messages),
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                }
        except Exception as error:
            record = {
                "timestamp": datetime.now(UTC).isoformat(),
                "request_id": request_id,
                "session_id": session_id,
                "prompt": message,
                "error": {"type": type(error).__name__, "message": str(error)},
                "messages": copy.deepcopy(agent.messages),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
            self._append(record)
            raise RuntimeError(
                "agent request failed; inspect the telemetry panel"
            ) from error

        self._append(record)
        return {"answer": answer, "telemetry": record}

    def reset(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid session id")
        with self.sessions_lock:
            self.sessions.pop(session_id, None)

    def _session(self, session_id: str) -> tuple[Any, threading.Lock]:
        with self.sessions_lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = (
                    self.agent_factory(
                        trace_attributes={"tollchat.session_id": session_id}
                    ),
                    threading.Lock(),
                )
            return self.sessions[session_id]

    def _append(self, record: dict[str, Any]) -> None:
        self.telemetry_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        line = json.dumps(record, default=str, separators=(",", ":")) + "\n"
        with (
            self.telemetry_lock,
            os.fdopen(
                os.open(
                    self.telemetry_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600
                ),
                "a",
                encoding="utf-8",
            ) as telemetry,
        ):
            os.fchmod(telemetry.fileno(), 0o600)
            telemetry.write(line)


def create_server(
    app: DevChat, host: str = "127.0.0.1", port: int = 8000
) -> ThreadingHTTPServer:
    """Create the local-only HTTP server; tests pass port=0 for an ephemeral port."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send(
                HTTPStatus.OK, _HTML_PATH.read_bytes(), "text/html; charset=utf-8"
            )

        def do_POST(self) -> None:
            try:
                body = self._json()
                session_id = body.get("session_id", "")
                if self.path == "/api/chat":
                    self._json_response(
                        HTTPStatus.OK, app.chat(session_id, body.get("message", ""))
                    )
                elif self.path == "/api/reset":
                    app.reset(session_id)
                    self._json_response(HTTPStatus.OK, {"ok": True})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except (TypeError, ValueError) as error:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except RuntimeError as error:
                self._json_response(
                    HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)}
                )

        def _json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= _MAX_MESSAGE_CHARS + 256:
                raise ValueError("invalid request size")
            try:
                body = json.loads(self.rfile.read(length))
            except json.JSONDecodeError as error:
                raise ValueError("invalid JSON") from error
            if not isinstance(body, dict):
                raise TypeError("JSON body must be an object")
            return body

        def _json_response(self, status: HTTPStatus, body: dict[str, Any]) -> None:
            self._send(
                status, json.dumps(body, default=str).encode(), "application/json"
            )

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    configure_local_pricing_env()
    os.environ.setdefault("OTEL_SERVICE_NAME", "tollchat-dev")
    StrandsTelemetry().setup_console_exporter()
    server = create_server(DevChat())
    print("TollChat dev console: http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
