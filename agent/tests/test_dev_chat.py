"""Offline tests for the loopback dev console and its raw telemetry."""

import json
import logging
import os
import threading
import urllib.request
from datetime import date

import pytest

from agent import dev_chat
from agent.dev_chat import DevChat, configure_local_pricing_env, create_server


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


class _FailingAgent:
    def __init__(self):
        self.messages = []

    def __call__(self, _prompt):
        raise ValueError("boom")


def test_local_server_discovers_its_read_only_database_environment(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    ca_bundle = tmp_path / "rds-ca-bundle.pem"
    ca_bundle.touch()
    monkeypatch.setattr(dev_chat, "_CA_BUNDLE_PATH", ca_bundle)
    discovered = []
    monkeypatch.setattr(
        dev_chat,
        "configure_pricing_reader_rds_env",
        lambda: discovered.append(True),
    )
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_PROFILE",
        "AWS_DEFAULT_REGION",
        "DB_NAME",
        "DB_USER",
        "DB_CA_BUNDLE_PATH",
    ):
        monkeypatch.delenv(name, raising=False)

    configure_local_pricing_env()

    assert discovered == [True]
    assert os.environ["AWS_PROFILE"] == "nova-toll"
    assert os.environ["AWS_DEFAULT_REGION"] == "us-east-1"
    assert os.environ["DB_NAME"] == "nova_toll"
    assert os.environ["DB_USER"] == "pricing_reader"
    assert os.environ["DB_CA_BUNDLE_PATH"] == str(ca_bundle)


def test_local_server_preserves_ambient_aws_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    ca_bundle = tmp_path / "rds-ca-bundle.pem"
    ca_bundle.touch()
    monkeypatch.setattr(dev_chat, "_CA_BUNDLE_PATH", ca_bundle)
    monkeypatch.setattr(dev_chat, "configure_pricing_reader_rds_env", lambda: None)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ambient")
    monkeypatch.delenv("AWS_PROFILE", raising=False)

    configure_local_pricing_env()

    assert "AWS_PROFILE" not in os.environ


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

    records = [json.loads(line) for line in telemetry_path.read_text().splitlines()]
    assert [record["session_id"] for record in records] == ["one", "one", "two"]
    assert records[1]["metrics"] == {"total_cycles": 1, "tool_usage": {}}
    assert "messages" not in records[1]
    assert os.stat(telemetry_path).st_mode & 0o777 == 0o600

    chat.reset("one")
    assert chat.chat("one", "fresh")["answer"] == "3: fresh"


def test_chat_rebuilds_a_session_when_the_new_york_date_changes(tmp_path, monkeypatch):
    dates = iter((date(2026, 8, 5), date(2026, 8, 5), date(2026, 8, 6)))
    monkeypatch.setattr(dev_chat, "_new_york_date", lambda: next(dates))
    factory = _Factory()
    chat = DevChat(factory, tmp_path / "telemetry.jsonl")

    assert chat.chat("one", "before midnight")["answer"] == "1: before midnight"
    assert chat.chat("one", "still today")["answer"] == "1: still today"
    assert chat.chat("one", "after midnight")["answer"] == "2: after midnight"
    assert len(factory.agents) == 2


@pytest.mark.parametrize(
    "session_id,message",
    [("", "hello"), ("bad/id", "hello"), ("ok", " "), ("ok", 1)],
)
def test_chat_rejects_invalid_input(tmp_path, session_id, message):
    with pytest.raises((TypeError, ValueError)):
        DevChat(_Factory(), tmp_path / "telemetry.jsonl").chat(session_id, message)


def test_chat_logs_and_records_agent_traceback(tmp_path, caplog):
    telemetry_path = tmp_path / "telemetry.jsonl"
    chat = DevChat(lambda **_kwargs: _FailingAgent(), telemetry_path)
    caplog.set_level(logging.ERROR)

    with pytest.raises(RuntimeError, match="inspect the telemetry panel"):
        chat.chat("broken", "hello")

    [record] = [json.loads(line) for line in telemetry_path.read_text().splitlines()]
    assert "ValueError: boom" in record["error"]["traceback"]
    assert "messages" not in record
    assert record["request_id"] in caplog.text
    assert any(log_record.exc_info for log_record in caplog.records)


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
