"""Offline tests for the loopback dev console and its raw telemetry."""

import json
import os
import threading
import urllib.request

import pytest
from dev_chat import DevChat, create_server


class _Metrics:
    def get_summary(self):
        return {"total_cycles": 1, "tool_usage": {}}


class _Result:
    metrics = _Metrics()

    def __init__(self, answer):
        self.answer = answer

    def __str__(self):
        return self.answer

    def to_dict(self):
        return {"type": "agent_result", "message": {"text": self.answer}}


class _Agent:
    def __init__(self, number, trace_attributes):
        self.number = number
        self.trace_attributes = trace_attributes
        self.messages = []

    def __call__(self, prompt):
        self.messages.extend(
            [
                {"role": "user", "content": [{"text": prompt}]},
                {
                    "role": "assistant",
                    "content": [{"text": f"{self.number}: {prompt}"}],
                },
            ]
        )
        return _Result(f"{self.number}: {prompt}")


class _Factory:
    def __init__(self):
        self.agents = []

    def __call__(self, *, trace_attributes):
        agent = _Agent(len(self.agents) + 1, trace_attributes)
        self.agents.append(agent)
        return agent


def test_chat_reuses_sessions_writes_raw_telemetry_and_resets(tmp_path):
    factory = _Factory()
    telemetry_path = tmp_path / "telemetry.jsonl"
    chat = DevChat(factory, telemetry_path)

    first = chat.chat("one", "first")
    second = chat.chat("one", "second")
    other = chat.chat("two", "other")

    assert first["answer"] == "1: first"
    assert second["answer"] == "1: second"
    assert other["answer"] == "2: other"
    assert len(factory.agents) == 2
    assert factory.agents[0].trace_attributes == {"tollchat.session_id": "one"}
    assert len(factory.agents[0].messages) == 4

    records = [json.loads(line) for line in telemetry_path.read_text().splitlines()]
    assert [record["session_id"] for record in records] == ["one", "one", "two"]
    assert records[1]["messages"][-1]["content"][0]["text"] == "1: second"
    assert os.stat(telemetry_path).st_mode & 0o777 == 0o600

    chat.reset("one")
    assert chat.chat("one", "fresh")["answer"] == "3: fresh"


@pytest.mark.parametrize(
    "session_id,message",
    [("", "hello"), ("bad/id", "hello"), ("ok", " "), ("ok", 1)],
)
def test_chat_rejects_invalid_input(tmp_path, session_id, message):
    with pytest.raises((TypeError, ValueError)):
        DevChat(_Factory(), tmp_path / "telemetry.jsonl").chat(session_id, message)


def test_http_server_serves_ui_and_chat_api(tmp_path):
    chat = DevChat(_Factory(), tmp_path / "telemetry.jsonl")
    server = create_server(chat, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        assert (
            "Reset chat" in urllib.request.urlopen(base_url, timeout=2).read().decode()
        )
        request = urllib.request.Request(
            f"{base_url}/api/chat",
            data=json.dumps({"session_id": "browser", "message": "hello"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        payload = json.loads(urllib.request.urlopen(request, timeout=2).read())
        assert payload["answer"] == "1: hello"
        assert payload["telemetry"]["session_id"] == "browser"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
