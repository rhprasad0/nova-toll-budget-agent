"""Offline contracts for the v2 loopback streaming console."""

# pyright: basic

import asyncio
import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from agent import dev_chat
from agent.dev_chat import DevChat, create_server


class _Metrics:
    def get_summary(self):
        return {"total_cycles": 2, "tool_usage": {"get_current_toll_price": 1}}


class _Result:
    metrics = _Metrics()

    def __str__(self):
        return "## Price\n\nHello 👋 **$4.25**"

    def to_dict(self):
        return {"message": {"role": "assistant", "content": [{"text": str(self)}]}}


class _Agent:
    def __init__(self, number, trace_attributes):
        self.number = number
        self.trace_attributes = trace_attributes

    async def stream_async(self, prompt):
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
    def __init__(self):
        self.agents = []

    def __call__(self, *, trace_attributes):
        agent = _Agent(len(self.agents) + 1, trace_attributes)
        self.agents.append(agent)
        return agent


class _FailingAgent:
    async def stream_async(self, _prompt):
        yield {"data": "partial"}
        raise ValueError("secret failure details")


async def _collect(app, session_id="browser", message="hello"):
    return [event async for event in app.stream(session_id, message)]


def test_streams_raw_events_text_tools_result_and_reuses_session():
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
    assert factory.agents[0].trace_attributes == {"tollchat.session_id": "browser"}


def test_reset_and_new_york_date_create_fresh_agents(monkeypatch):
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
def test_rejects_invalid_input(session_id, message):
    with pytest.raises((TypeError, ValueError)):
        DevChat(_Factory()).validate(session_id, message)


def test_agent_failure_emits_one_safe_terminal_error(caplog):
    app = DevChat(lambda **_kwargs: _FailingAgent())

    events = asyncio.run(_collect(app))

    assert events[0]["text_delta"] == "partial"
    assert events[-1] == {
        "type": "error",
        "sequence": 1,
        "message": "Agent request failed. Check the server log.",
    }
    assert "secret failure details" in caplog.text


def test_http_server_serves_assets_streams_ndjson_and_resets():
    factory = _Factory()
    app = DevChat(factory)
    server = create_server(app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        page = urllib.request.urlopen(base_url, timeout=2)
        assert page.headers["Cache-Control"] == "no-store"
        assert "Strands event inspector" in page.read().decode()
        assert (
            "consumeNdjson"
            in urllib.request.urlopen(f"{base_url}/dev_chat.mjs", timeout=2)
            .read()
            .decode()
        )

        response = _post(
            f"{base_url}/api/chat",
            {"session_id": "browser", "message": "hello 👋"},
        )
        assert response.headers.get_content_type() == "application/x-ndjson"
        events = [json.loads(line) for line in response]
        assert events[1]["text_delta"] == "1: hello 👋 👋"
        assert events[-1]["final"]["text"].startswith("## Price")

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
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _post(url, body):
    return urllib.request.urlopen(
        urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        ),
        timeout=2,
    )
