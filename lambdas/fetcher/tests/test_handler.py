import io
import logging
import urllib.error
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

import handler

TOKEN_I95 = "super-secret-i95-token"
TOKEN_I66 = "super-secret-i66-token"


@pytest.fixture(autouse=True)
def reset_module_state(monkeypatch):
    """handler.py caches clients/tokens as module globals; isolate tests."""
    monkeypatch.setattr(handler, "_clients", {})
    monkeypatch.setattr(handler, "_tokens", None)
    monkeypatch.setenv("I95_TOKEN_PARAM", "/nova-toll/i95-token")
    monkeypatch.setenv("I66_TOKEN_PARAM", "/nova-toll/i66-token")
    monkeypatch.setenv("RAW_BUCKET", "nova-toll-raw-test")


@pytest.fixture
def stub_aws(monkeypatch):
    ssm = MagicMock()
    ssm.get_parameter.side_effect = lambda Name, WithDecryption: {
        "/nova-toll/i95-token": {"Parameter": {"Value": TOKEN_I95}},
        "/nova-toll/i66-token": {"Parameter": {"Value": TOKEN_I66}},
    }[Name]
    s3 = MagicMock()
    cloudwatch = MagicMock()
    handler._clients.update(ssm=ssm, s3=s3, cloudwatch=cloudwatch)
    return {"ssm": ssm, "s3": s3, "cloudwatch": cloudwatch}


def test_s3_key_matches_spec_examples():
    now = datetime(2026, 7, 21, 14, 40, 3, tzinfo=UTC)
    assert (
        handler._s3_key("i95", now, "csv") == "raw/feed=i95/date=2026-07-21/1440Z.csv"
    )
    assert (
        handler._s3_key("i66", now, "xml") == "raw/feed=i66/date=2026-07-21/1440Z.xml"
    )


def test_s3_key_rounds_down_to_schedule_tick():
    now = datetime(2026, 7, 21, 14, 47, 59, tzinfo=UTC)
    assert (
        handler._s3_key("i95", now, "csv") == "raw/feed=i95/date=2026-07-21/1440Z.csv"
    )


def test_fetch_feed_scrubs_token_from_exception_text(monkeypatch):
    def fake_urlopen(url, timeout=None):
        # Simulate a urllib exception that echoes the full request URL.
        raise urllib.error.URLError(f"connection refused for {url}")

    monkeypatch.setattr(handler.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError) as exc_info:
        handler._fetch_feed("i95", "https://example.com/feed", TOKEN_I95)

    assert TOKEN_I95 not in str(exc_info.value)
    assert "***" in str(exc_info.value)


def test_fetch_feed_enforces_5mb_cap(monkeypatch):
    oversized = io.BytesIO(b"x" * (handler.MAX_RESPONSE_BYTES + 1))
    monkeypatch.setattr(
        handler.urllib.request, "urlopen", lambda url, timeout=None: oversized
    )

    with pytest.raises(RuntimeError, match="byte cap"):
        handler._fetch_feed("i95", "https://example.com/feed", TOKEN_I95)


def test_one_feed_failing_does_not_block_the_other(monkeypatch, stub_aws, caplog):
    caplog.set_level(logging.INFO)

    def fake_urlopen(url, timeout=None):
        if "I95" in url:
            raise urllib.error.URLError(f"connection refused for {url}")
        return io.BytesIO(b"<opt/>")

    monkeypatch.setattr(handler.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="i95"):
        handler.handler({}, None)

    # i66 still made it through despite i95 failing.
    stub_aws["s3"].put_object.assert_called_once()
    put_kwargs = stub_aws["s3"].put_object.call_args.kwargs
    assert put_kwargs["Key"] == handler._s3_key("i66", datetime.now(UTC), "xml")
    stub_aws["cloudwatch"].put_metric_data.assert_called_once()
    metric_call = stub_aws["cloudwatch"].put_metric_data.call_args.kwargs
    assert metric_call["MetricData"][0]["Dimensions"] == [
        {"Name": "feed", "Value": "i66"}
    ]


def test_token_never_appears_in_logs_or_exception(monkeypatch, stub_aws, caplog):
    caplog.set_level(logging.INFO)

    def fake_urlopen(url, timeout=None):
        raise urllib.error.URLError(f"connection refused for {url}")

    monkeypatch.setattr(handler.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError) as exc_info:
        handler.handler({}, None)

    assert TOKEN_I95 not in caplog.text
    assert TOKEN_I66 not in caplog.text
    assert TOKEN_I95 not in str(exc_info.value)
    assert TOKEN_I66 not in str(exc_info.value)
