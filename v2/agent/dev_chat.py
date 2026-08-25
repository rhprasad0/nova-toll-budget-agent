"""Loopback-only streaming browser console for the v2 TollChat agent."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from agent.toll_agent import build_agent

_ASSET_ROOT = Path(__file__).resolve().parent
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_MAX_MESSAGE_CHARS = 8_000
_EASTERN = ZoneInfo("America/New_York")
_TOOL_LABELS = {
    "get_current_toll_price": "Checking current toll price",
    "get_annual_toll_ballpark": "Estimating annual commute tolls",
}
logger = logging.getLogger(__name__)


def _new_york_date() -> date:
    return datetime.now(_EASTERN).date()


def _json_safe(value: object) -> object:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_safe(to_dict())
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _json_safe(item) for key, item in mapping.items()}
    if isinstance(value, Sequence):
        return [_json_safe(item) for item in cast(Sequence[object], value)]
    return str(value)


def _activity_updates(
    message: object, activities: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    if not isinstance(message, Mapping):
        return []
    message_data = cast(Mapping[object, object], message)
    content = message_data.get("content", [])
    if not isinstance(content, Sequence):
        return []
    updates: list[dict[str, object]] = []
    for block in cast(Sequence[object], content):
        if not isinstance(block, Mapping):
            continue
        block_data = cast(Mapping[object, object], block)
        tool_use = block_data.get("toolUse")
        if isinstance(tool_use, Mapping):
            tool_use_data = cast(Mapping[object, object], tool_use)
            tool_id = tool_use_data.get("toolUseId")
            if isinstance(tool_id, str) and tool_id not in activities:
                activity: dict[str, object] = {
                    "index": len(activities),
                    "label": _TOOL_LABELS.get(
                        str(tool_use_data.get("name")), "Checking toll data"
                    ),
                    "status": "running",
                }
                activities[tool_id] = activity
                updates.append(dict(activity))
            continue
        tool_result = block_data.get("toolResult")
        if isinstance(tool_result, Mapping):
            tool_result_data = cast(Mapping[object, object], tool_result)
            tool_id = tool_result_data.get("toolUseId")
            if isinstance(tool_id, str) and tool_id in activities:
                activity = activities[tool_id]
                activity["status"] = (
                    "failed"
                    if tool_result_data.get("status") == "error"
                    else "completed"
                )
                updates.append(dict(activity))
    return updates


class DevChat:
    """In-memory browser sessions backed by streamed Strands agents."""

    def __init__(self, agent_factory: Callable[..., Any] = build_agent) -> None:
        self.agent_factory = agent_factory
        self.sessions: dict[str, tuple[Any, threading.Lock, date]] = {}
        self.sessions_lock = threading.Lock()

    @staticmethod
    def validate(session_id: object, message: object) -> tuple[str, str]:
        session = DevChat._validate_session(session_id)
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if not (prompt := message.strip()):
            raise ValueError("message is required")
        if len(prompt) > _MAX_MESSAGE_CHARS:
            raise ValueError(f"message must be at most {_MAX_MESSAGE_CHARS} characters")
        return session, prompt

    @staticmethod
    def _validate_session(session_id: object) -> str:
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid session id")
        return session_id

    async def stream(
        self, session_id: object, message: object
    ) -> AsyncIterator[dict[str, object]]:
        session, prompt = self.validate(session_id, message)
        activities: dict[str, dict[str, object]] = {}
        sequence = 0
        try:
            agent, lock = self._session(session)
            with lock:
                async for sdk_event in agent.stream_async(prompt):
                    event = cast(dict[str, object], sdk_event)
                    payload: dict[str, object] = {
                        "type": "event",
                        "sequence": sequence,
                        "event": _json_safe(event),
                    }
                    if isinstance(event.get("data"), str):
                        payload["text_delta"] = event["data"]
                    if updates := _activity_updates(event.get("message"), activities):
                        payload["tool_updates"] = updates
                    if "result" in event and (result := event["result"]) is not None:
                        metrics = getattr(result, "metrics", None)
                        get_summary = getattr(metrics, "get_summary", None)
                        payload["final"] = {
                            "text": str(result).strip(),
                            "metrics": (
                                _json_safe(get_summary())
                                if callable(get_summary)
                                else {}
                            ),
                        }
                    yield payload
                    sequence += 1
                    if "final" in payload:
                        return
            raise RuntimeError("agent stream ended without a result")
        except Exception:
            logger.exception("agent request failed")
            yield {
                "type": "error",
                "sequence": sequence,
                "message": "TollChat couldn't complete the request. Check the server log.",
            }

    def reset(self, session_id: object) -> None:
        session = self._validate_session(session_id)
        with self.sessions_lock:
            self.sessions.pop(session, None)

    def _session(self, session_id: str) -> tuple[Any, threading.Lock]:
        with self.sessions_lock:
            today = _new_york_date()
            if session_id not in self.sessions or self.sessions[session_id][2] != today:
                self.sessions[session_id] = (
                    self.agent_factory(),
                    threading.Lock(),
                    today,
                )
            agent, lock, _ = self.sessions[session_id]
            return agent, lock


def create_server(
    app: DevChat, host: str = "127.0.0.1", port: int = 8000
) -> ThreadingHTTPServer:
    """Create the local-only HTTP server; tests use an ephemeral port."""

    static = {
        "/": (_ASSET_ROOT / "dev_chat.html", "text/html; charset=utf-8"),
        "/faq.html": (_ASSET_ROOT / "faq.html", "text/html; charset=utf-8"),
        "/privacy.txt": (_ASSET_ROOT / "privacy.txt", "text/plain; charset=utf-8"),
        "/terms.txt": (_ASSET_ROOT / "terms.txt", "text/plain; charset=utf-8"),
        "/dev_chat.mjs": (
            _ASSET_ROOT / "dev_chat.mjs",
            "text/javascript; charset=utf-8",
        ),
        "/chat.mjs": (
            _ASSET_ROOT / "dev_chat.mjs",
            "text/javascript; charset=utf-8",
        ),
        "/assets/tollchat-logo.png": (
            _ASSET_ROOT / "assets/tollchat-logo.png",
            "image/png",
        ),
        "/assets/favicon.png": (
            _ASSET_ROOT / "assets/favicon.png",
            "image/png",
        ),
        "/assets/commute-map.mjs": (
            _ASSET_ROOT / "assets/commute-map.mjs",
            "text/javascript; charset=utf-8",
        ),
        "/assets/commute-routes.mjs": (
            _ASSET_ROOT / "assets/commute-routes.mjs",
            "text/javascript; charset=utf-8",
        ),
        "/assets/commute-estimates.json": (
            _ASSET_ROOT / "assets/commute-estimates.json",
            "application/json; charset=utf-8",
        ),
        "/assets/coverage-locations.json": (
            _ASSET_ROOT / "assets/coverage-locations.json",
            "application/json; charset=utf-8",
        ),
        "/assets/chat-markdown.mjs": (
            _ASSET_ROOT / "assets/chat-markdown.mjs",
            "text/javascript; charset=utf-8",
        ),
        "/assets/markdown-it.esm.min.mjs": (
            _ASSET_ROOT / "assets/markdown-it.esm.min.mjs",
            "text/javascript; charset=utf-8",
        ),
        "/assets/LICENSE.txt": (
            _ASSET_ROOT / "assets/LICENSE.txt",
            "text/plain; charset=utf-8",
        ),
        **{
            f"/assets/maplibre-gl-6.0.0/{name}": (
                _ASSET_ROOT / "assets/maplibre-gl-6.0.0" / name,
                content_type,
            )
            for name, content_type in {
                "LICENSE.txt": "text/plain; charset=utf-8",
                "maplibre-gl.css": "text/css; charset=utf-8",
                "maplibre-gl.mjs": "text/javascript; charset=utf-8",
                "maplibre-gl-shared.mjs": "text/javascript; charset=utf-8",
                "maplibre-gl-worker.mjs": "text/javascript; charset=utf-8",
            }.items()
        },
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            asset = static.get(self.path)
            if asset is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            path, content_type = asset
            self._send(HTTPStatus.OK, path.read_bytes(), content_type)

        def do_POST(self) -> None:
            if self.path not in {"/api/chat", "/api/reset"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not self._same_origin():
                self._json_response(HTTPStatus.FORBIDDEN, {"error": "invalid origin"})
                return
            content_type = self.headers.get("Content-Type", "").partition(";")[0]
            if content_type.strip().lower() != "application/json":
                self._json_response(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    {"error": "Content-Type must be application/json"},
                )
                return
            try:
                body = self._json()
                session_id = body.get("session_id", "")
                if self.path == "/api/chat":
                    app.validate(session_id, body.get("message", ""))
                else:
                    app.reset(session_id)
            except (TypeError, ValueError) as error:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            if self.path == "/api/reset":
                self._json_response(HTTPStatus.OK, {"ok": True})
                return
            self.send_response(HTTPStatus.OK)
            self._headers("application/x-ndjson; charset=utf-8")
            self.end_headers()
            try:
                asyncio.run(
                    self._write_stream(app.stream(session_id, body.get("message", "")))
                )
            except (BrokenPipeError, ConnectionResetError):
                return

        def _same_origin(self) -> bool:
            port = cast(tuple[str, int], self.server.server_address)[1]
            return self.headers.get("Origin") in {
                f"http://127.0.0.1:{port}",
                f"http://localhost:{port}",
            }

        async def _write_stream(self, events: AsyncIterator[dict[str, object]]) -> None:
            async for event in events:
                self.wfile.write(
                    json.dumps(
                        event, ensure_ascii=False, separators=(",", ":")
                    ).encode()
                    + b"\n"
                )
                self.wfile.flush()

        def _json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= _MAX_MESSAGE_CHARS * 4 + 256:
                raise ValueError("invalid request size")
            try:
                body = json.loads(self.rfile.read(length))
            except json.JSONDecodeError as error:
                raise ValueError("invalid JSON") from error
            if not isinstance(body, dict):
                raise TypeError("JSON body must be an object")
            return cast(dict[str, Any], body)

        def _json_response(self, status: HTTPStatus, body: dict[str, object]) -> None:
            self._send(
                status,
                json.dumps(body, ensure_ascii=False).encode(),
                "application/json; charset=utf-8",
            )

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self._headers(content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _headers(self, content_type: str) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "connect-src 'self' https://tiles.openfreemap.org; "
                "worker-src 'self' blob:; "
                "object-src 'none'; base-uri 'none'; form-action 'self'",
            )

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    server = create_server(DevChat())
    print("TollChat v2 dev console: http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
