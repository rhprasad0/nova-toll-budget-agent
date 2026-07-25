import io
import logging
import urllib.error
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from conftest import express_fetcher_handler as handler


@pytest.fixture(autouse=True)
def reset_module_state(monkeypatch):
    """handler.py caches clients as module globals; isolate tests."""
    monkeypatch.setattr(handler, "_clients", {})
    monkeypatch.setenv("RAW_BUCKET", "nova-toll-raw-test")


@pytest.fixture
def stub_aws():
    s3 = MagicMock()
    cloudwatch = MagicMock()
    handler._clients.update(s3=s3, cloudwatch=cloudwatch)
    return {"s3": s3, "cloudwatch": cloudwatch}


def test_s3_key_matches_spec_examples():
    now = datetime(2026, 7, 21, 14, 40, 3, tzinfo=UTC)
    assert handler._s3_key(now) == "raw/feed=i95-live/date=2026-07-21/1440Z.json"


def test_s3_key_rounds_down_to_schedule_tick():
    now = datetime(2026, 7, 21, 14, 47, 59, tzinfo=UTC)
    assert handler._s3_key(now) == "raw/feed=i95-live/date=2026-07-21/1440Z.json"


def test_fetch_is_single_attempt_no_retry(monkeypatch):
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(handler.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="i95-live fetch failed"):
        handler._fetch()

    assert len(calls) == 1


def test_fetch_enforces_5mb_cap(monkeypatch):
    oversized = io.BytesIO(b"x" * (handler.MAX_RESPONSE_BYTES + 1))
    monkeypatch.setattr(
        handler.urllib.request, "urlopen", lambda url, timeout=None: oversized
    )

    with pytest.raises(RuntimeError, match="byte cap"):
        handler._fetch()


def test_success_path_puts_object_and_metric(monkeypatch, stub_aws, caplog):
    caplog.set_level(logging.INFO)
    body = io.BytesIO(b'{"response": []}')
    monkeypatch.setattr(
        handler.urllib.request, "urlopen", lambda url, timeout=None: body
    )

    handler.handler({}, None)

    stub_aws["s3"].put_object.assert_called_once()
    put_kwargs = stub_aws["s3"].put_object.call_args.kwargs
    assert put_kwargs["Key"] == handler._s3_key(datetime.now(UTC))
    assert put_kwargs["Bucket"] == "nova-toll-raw-test"

    stub_aws["cloudwatch"].put_metric_data.assert_called_once()
    metric_call = stub_aws["cloudwatch"].put_metric_data.call_args.kwargs
    assert metric_call["MetricData"][0]["Dimensions"] == [
        {"Name": "feed", "Value": "i95-live"}
    ]
    assert "poll succeeded feed=i95-live" in caplog.text
