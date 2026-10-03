"""Offline contracts for the v2 loopback streaming console."""

import asyncio
import json
import threading
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from datetime import date
from http.client import HTTPConnection, HTTPResponse
from pathlib import Path
from typing import Any

import pytest

from agent import dev_chat
from agent.dev_chat import DevChat, create_server


class _Metrics:
    def get_summary(self) -> dict[str, object]:
        return {"total_cycles": 2, "tool_usage": {"get_current_toll_price": 1}}


class _Result:
    metrics = _Metrics()

    def __str__(self) -> str:
        return "## Price\n\nHello 👋 **$4.25**"

    def to_dict(self) -> dict[str, object]:
        return {"message": {"role": "assistant", "content": [{"text": str(self)}]}}


class _Agent:
    def __init__(self, number: int, factory_kwargs: dict[str, object]) -> None:
        self.number = number
        self.factory_kwargs = factory_kwargs

    async def stream_async(self, prompt: str) -> AsyncIterator[dict[str, object]]:
        yield {"init_event_loop": True}
        yield {"data": f"{self.number}: {prompt} 👋"}
        yield {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tool-1",
                            "name": "get_current_toll_price",
                            "input": {"origin_point_id": "a"},
                        }
                    }
                ],
            }
        }
        yield {
            "message": {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": "tool-1",
                            "status": "success",
                            "content": [{"text": "priced"}],
                        }
                    }
                ],
            }
        }
        yield {"result": _Result()}


class _Factory:
    def __init__(self) -> None:
        self.agents: list[_Agent] = []

    def __call__(self, **kwargs: object) -> _Agent:
        agent = _Agent(len(self.agents) + 1, kwargs)
        self.agents.append(agent)
        return agent


class _FailingAgent:
    async def stream_async(self, _prompt: str) -> AsyncIterator[dict[str, object]]:
        yield {"data": "partial"}
        raise ValueError("secret failure details")


async def _collect(
    app: DevChat, session_id: str = "browser", message: str = "hello"
) -> list[dict[str, Any]]:
    return [event async for event in app.stream(session_id, message)]


def test_streams_raw_events_text_tools_result_and_reuses_session() -> None:
    factory = _Factory()
    app = DevChat(factory)

    events = asyncio.run(_collect(app, message="price it"))

    assert [event["sequence"] for event in events] == list(range(5))
    assert events[0]["event"] == {"init_event_loop": True}
    assert events[1]["text_delta"] == "1: price it 👋"
    assert events[2]["tool_updates"] == [
        {
            "index": 0,
            "label": "Checking current toll price",
            "status": "running",
        }
    ]
    assert events[3]["tool_updates"][0]["status"] == "completed"
    assert events[4]["final"] == {
        "text": "## Price\n\nHello 👋 **$4.25**",
        "metrics": {
            "total_cycles": 2,
            "tool_usage": {"get_current_toll_price": 1},
        },
    }
    assert isinstance(events[4]["event"]["result"], dict)

    second = asyncio.run(_collect(app, message="again"))
    assert second[1]["text_delta"].startswith("1:")
    assert len(factory.agents) == 1
    assert factory.agents[0].factory_kwargs == {}


def test_reset_and_new_york_date_create_fresh_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = iter((date(2026, 8, 22), date(2026, 8, 22), date(2026, 8, 23)))
    monkeypatch.setattr(dev_chat, "_new_york_date", lambda: next(dates))
    factory = _Factory()
    app = DevChat(factory)

    assert asyncio.run(_collect(app))[1]["text_delta"].startswith("1:")
    assert asyncio.run(_collect(app))[1]["text_delta"].startswith("1:")
    assert asyncio.run(_collect(app))[1]["text_delta"].startswith("2:")
    app.reset("browser")
    assert len(factory.agents) == 2


@pytest.mark.parametrize(
    ("session_id", "message"),
    [("", "hello"), ("bad/id", "hello"), ("ok", " "), ("ok", 1)],
)
def test_rejects_invalid_input(session_id: str, message: str | int) -> None:
    with pytest.raises((TypeError, ValueError)):
        DevChat(_Factory()).validate(session_id, message)


def test_agent_failure_emits_one_safe_terminal_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _strict_callback_1(**_kwargs: object) -> object:
        return _FailingAgent()

    app = DevChat(_strict_callback_1)

    events = asyncio.run(_collect(app))

    assert events[0]["text_delta"] == "partial"
    assert events[-1] == {
        "type": "error",
        "sequence": 1,
        "message": "TollChat couldn't complete the request. Check the server log.",
    }
    assert "secret failure details" in caplog.text
    assert "browser" not in caplog.text


def test_agent_construction_failure_emits_one_safe_terminal_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(**_kwargs: object) -> None:
        raise ValueError("startup secret details")

    events = asyncio.run(_collect(DevChat(fail)))

    assert events == [
        {
            "type": "error",
            "sequence": 0,
            "message": "TollChat couldn't complete the request. Check the server log.",
        }
    ]
    assert "startup secret details" in caplog.text


def test_http_server_streams_ndjson_and_resets() -> None:
    factory = _Factory()
    app = DevChat(factory)
    server = create_server(app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        response = _post(
            f"{base_url}/api/chat",
            {"session_id": "browser", "message": "hello 👋"},
        )
        assert response.headers.get_content_type() == "application/x-ndjson"
        events = [json.loads(line) for line in response]
        assert events[1]["text_delta"] == "1: hello 👋 👋"
        assert events[-1]["final"]["text"].startswith("## Price")

        with pytest.raises(urllib.error.HTTPError) as foreign_reset:
            _post(
                f"{base_url}/api/reset",
                {"session_id": "browser"},
                origin="https://evil.example",
            )
        assert foreign_reset.value.code == 403
        response = _post(
            f"{base_url}/api/chat",
            {"session_id": "browser", "message": "still here"},
        )
        events = [json.loads(line) for line in response]
        assert events[1]["text_delta"].startswith("1:")

        reset = _post(f"{base_url}/api/reset", {"session_id": "browser"})
        assert json.load(reset) == {"ok": True}
        assert len(factory.agents) == 1

        with pytest.raises(urllib.error.HTTPError) as invalid:
            _post(
                f"{base_url}/api/chat",
                {"session_id": "bad/id", "message": "hello"},
            )
        assert invalid.value.code == 400
        assert json.load(invalid.value) == {"error": "invalid session id"}

        for origin, content_type, expected_status in (
            ("https://evil.example", "application/json", 403),
            (base_url, "text/plain", 415),
            (None, "application/json", 403),
        ):
            with pytest.raises(urllib.error.HTTPError) as rejected:
                _post(
                    f"{base_url}/api/chat",
                    {"session_id": "blocked", "message": "do not run"},
                    origin=origin,
                    content_type=content_type,
                )
            assert rejected.value.code == expected_status
        assert len(factory.agents) == 1
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_http_asset_allowlist_preserves_bytes_headers_and_rejections() -> None:
    expected = {
        "/": "text/html; charset=utf-8",
        "/faq.html": "text/html; charset=utf-8",
        "/privacy.txt": "text/plain; charset=utf-8",
        "/terms.txt": "text/plain; charset=utf-8",
        "/dev_chat.mjs": "text/javascript; charset=utf-8",
        "/chat.mjs": "text/javascript; charset=utf-8",
        "/assets/tollchat-logo.png": "image/png",
        "/assets/favicon.png": "image/png",
        "/assets/evals.css": "text/css; charset=utf-8",
        "/assets/chat.css": "text/css; charset=utf-8",
        "/assets/commute-map.mjs": "text/javascript; charset=utf-8",
        "/assets/commute-routes.mjs": "text/javascript; charset=utf-8",
        "/assets/commute-estimates.json": "application/json; charset=utf-8",
        "/assets/coverage-locations.json": "application/json; charset=utf-8",
        "/assets/chat-markdown.mjs": "text/javascript; charset=utf-8",
        "/assets/markdown-it.esm.min.mjs": "text/javascript; charset=utf-8",
        "/assets/LICENSE.txt": "text/plain; charset=utf-8",
        "/assets/maplibre-gl-6.0.0/LICENSE.txt": "text/plain; charset=utf-8",
        "/assets/maplibre-gl-6.0.0/maplibre-gl.css": "text/css; charset=utf-8",
        "/assets/maplibre-gl-6.0.0/maplibre-gl.mjs": "text/javascript; charset=utf-8",
        "/assets/maplibre-gl-6.0.0/maplibre-gl-shared.mjs": "text/javascript; charset=utf-8",
        "/assets/maplibre-gl-6.0.0/maplibre-gl-worker.mjs": "text/javascript; charset=utf-8",
    }
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' https://tiles.openfreemap.org; "
            "worker-src 'self' blob:; "
            "object-src 'none'; base-uri 'none'; form-action 'self'"
        ),
    }
    root = Path(dev_chat.__file__).parent
    unserved_files = (
        "/dev_chat.html",
        "/dev_chat.py",
        "/toll_agent.py",
        "/assets/costs.mjs",
        "/assets/tollchat-annual-commute-example.png",
        "/assets/maplibre-gl-6.0.0/maplibre-gl.d.mts",
    )
    assert all((root / path.lstrip("/")).is_file() for path in unserved_files)
    server = create_server(DevChat(_Factory()), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        for path, content_type in expected.items():
            connection.request("GET", path)
            response = connection.getresponse()
            filename = {"/": "dev_chat.html", "/chat.mjs": "dev_chat.mjs"}.get(
                path, path.lstrip("/")
            )
            body = (root / filename).read_bytes()
            assert response.status == 200, path
            assert response.read() == body, path
            assert response.headers["Content-Type"] == content_type, path
            assert response.headers["Content-Length"] == str(len(body)), path
            for name, value in headers.items():
                assert response.headers[name] == value, (path, name)

        for path in (
            *unserved_files,
            "/missing",
            "/assets/",
            "/../pyproject.toml",
            "/assets/../dev_chat.py",
            "/%2e%2e/pyproject.toml",
            "/assets/%2e%2e/dev_chat.py",
            "/?cache=1",
            "/assets/chat.css?cache=1",
        ):
            connection.request("GET", path)
            response = connection.getresponse()
            assert response.status == 404, path
            response.read()

        connection.request("HEAD", "/")
        response = connection.getresponse()
        assert response.status == 501
        assert response.read() == b""
    finally:
        connection.close()
        server.shutdown()
        thread.join()
        server.server_close()


def _post(
    url: str,
    body: object,
    *,
    origin: str | None = "same-origin",
    content_type: str = "application/json",
) -> HTTPResponse:
    if origin == "same-origin":
        origin = url.removesuffix("/api/chat").removesuffix("/api/reset")
    headers = {"Content-Type": content_type}
    if origin is not None:
        headers["Origin"] = origin
    return urllib.request.urlopen(
        urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        ),
        timeout=2,
    )
