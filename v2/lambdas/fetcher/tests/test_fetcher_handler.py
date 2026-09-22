import io
import logging
import traceback
import urllib.error
from datetime import UTC, datetime
from unittest.mock import MagicMock

import handler
import pytest

TOKEN_I95 = "super-secret-i95-token"
TOKEN_I66 = "super-secret-i66-token"


@pytest.fixture(autouse=True)
def reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """handler.py caches clients/tokens as module globals; isolate tests."""
    monkeypatch.setattr(handler, "_clients", {})
    monkeypatch.setattr(handler, "_tokens", {})
    monkeypatch.setenv("I95_TOKEN_PARAM", "/nova-toll/i95-token")
    monkeypatch.setenv("I66_TOKEN_PARAM", "/nova-toll/i66-token")
    monkeypatch.setenv("RAW_BUCKET", "nova-toll-raw-test")
    monkeypatch.setenv("RAW_KMS_KEY_ARN", "arn:aws:kms:us-east-1:123456789012:key/raw")


@pytest.fixture
def stub_aws(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    ssm = MagicMock()

    def _callback_1(Name: str, WithDecryption: object) -> object:
        return {
            "/nova-toll/i95-token": {"Parameter": {"Value": TOKEN_I95}},
            "/nova-toll/i66-token": {"Parameter": {"Value": TOKEN_I66}},
        }[Name]

    ssm.get_parameter.side_effect = _callback_1
    s3 = MagicMock()
    cloudwatch = MagicMock()
    handler._clients.update(ssm=ssm, s3=s3, cloudwatch=cloudwatch)
    return {"ssm": ssm, "s3": s3, "cloudwatch": cloudwatch}


def test_s3_key_matches_spec_examples() -> None:
    now = datetime(2026, 7, 21, 14, 40, 3, tzinfo=UTC)
    assert (
        handler._s3_key("i95", now, "csv", 10)
        == "raw/feed=i95/date=2026-07-21/1440Z.csv"
    )
    assert (
        handler._s3_key("i66", now, "xml", 6)
        == "raw/feed=i66/date=2026-07-21/1436Z.xml"
    )


def test_s3_key_rounds_down_to_schedule_tick() -> None:
    now = datetime(2026, 7, 21, 14, 47, 59, tzinfo=UTC)
    assert (
        handler._s3_key("i95", now, "csv", 10)
        == "raw/feed=i95/date=2026-07-21/1440Z.csv"
    )
    assert (
        handler._s3_key("i66", now, "xml", 6)
        == "raw/feed=i66/date=2026-07-21/1442Z.xml"
    )


def test_s3_key_buckets_never_collide_within_a_feeds_own_tick() -> None:
    """Two polls of one feed inside one tick would overwrite each other, so the
    key's bucket width has to match the rule that drives it."""
    for feed, extension, tick in (("i95", "csv", 10), ("i66", "xml", 6)):
        base = datetime(2026, 7, 21, 14, 0, tzinfo=UTC)
        keys = {
            handler._s3_key(feed, base.replace(minute=m), extension, tick)
            for m in range(60)
        }
        assert len(keys) == 60 // tick


def test_fetch_feed_scrubs_token_from_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(url: str, timeout: float | None = None) -> None:
        # Simulate a urllib exception that echoes the full request URL.
        raise urllib.error.URLError(f"connection refused for {url}")

    monkeypatch.setattr(handler.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError) as exc_info:
        handler._fetch_feed("i95", "https://example.com/feed", TOKEN_I95)

    assert TOKEN_I95 not in str(exc_info.value)
    assert "***" in str(exc_info.value)


def test_fetch_feed_enforces_5mb_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    oversized = io.BytesIO(b"x" * (handler.MAX_RESPONSE_BYTES + 1))

    def _callback_2(url: str, timeout: object = None) -> object:
        return oversized

    monkeypatch.setattr(handler.urllib.request, "urlopen", _callback_2)

    with pytest.raises(RuntimeError, match="byte cap"):
        handler._fetch_feed("i95", "https://example.com/feed", TOKEN_I95)


def test_one_feed_failing_does_not_block_the_other(
    monkeypatch: pytest.MonkeyPatch,
    stub_aws: dict[str, MagicMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    def fake_urlopen(url: str, timeout: float | None = None) -> io.BytesIO:
        if "I95" in url:
            raise urllib.error.URLError(f"connection refused for {url}")
        return io.BytesIO(b"<opt/>")

    monkeypatch.setattr(handler.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="i95"):
        handler.handler({}, None)

    assert not any(record.exc_info for record in caplog.records)

    # i66 still made it through despite i95 failing.
    stub_aws["s3"].put_object.assert_called_once()
    put_kwargs = stub_aws["s3"].put_object.call_args.kwargs
    assert put_kwargs["Key"] == handler._s3_key("i66", datetime.now(UTC), "xml", 6)
    assert put_kwargs["ServerSideEncryption"] == "aws:kms"
    assert put_kwargs["SSEKMSKeyId"].endswith("/raw")
    stub_aws["cloudwatch"].put_metric_data.assert_called_once()
    metric_call = stub_aws["cloudwatch"].put_metric_data.call_args.kwargs
    assert metric_call["MetricData"][0]["Dimensions"] == [
        {"Name": "feed", "Value": "i66"}
    ]


def test_event_selects_which_feeds_to_poll(
    monkeypatch: pytest.MonkeyPatch, stub_aws: dict[str, MagicMock]
) -> None:
    """The two feeds ride separate EventBridge rules, each naming its feed."""

    def selected_token(Name: str, WithDecryption: object) -> object:
        if Name != "/nova-toll/i66-token":
            raise RuntimeError("unselected feed token unavailable")
        return {"Parameter": {"Value": TOKEN_I66}}

    stub_aws["ssm"].get_parameter.side_effect = selected_token

    def _callback_3(url: str, timeout: object = None) -> object:
        return io.BytesIO(b"<opt/>")

    monkeypatch.setattr(
        handler.urllib.request,
        "urlopen",
        _callback_3,
    )

    result = handler.handler({"feeds": ["i66"], "drill_id": "0123456789abcdef"}, None)

    stub_aws["ssm"].get_parameter.assert_called_once_with(
        WithDecryption=True, Name="/nova-toll/i66-token"
    )
    stub_aws["s3"].put_object.assert_called_once()
    key = stub_aws["s3"].put_object.call_args.kwargs["Key"]
    assert key.endswith("-0123456789abcdef.xml")
    assert result == {"keys": [key]}


def test_failed_token_lookup_is_isolated_and_retried_while_successes_are_cached(
    monkeypatch: pytest.MonkeyPatch,
    stub_aws: dict[str, MagicMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub_aws["ssm"].get_parameter.side_effect = [
        RuntimeError(TOKEN_I95),
        {"Parameter": {"Value": TOKEN_I66}},
        {"Parameter": {"Value": TOKEN_I95}},
    ]
    fetch = MagicMock(side_effect=[io.BytesIO(b"feed") for _ in range(5)])
    monkeypatch.setattr(handler.urllib.request, "urlopen", fetch)

    with pytest.raises(RuntimeError, match=r"poll failed for feed\(s\): i95"):
        handler.handler({}, None)

    stub_aws["s3"].put_object.assert_called_once()
    assert "/feed=i66/" in stub_aws["s3"].put_object.call_args.kwargs["Key"]
    assert TOKEN_I95 not in caplog.text
    for _ in range(2):
        assert len(handler.handler({}, None)["keys"]) == 2
    assert [
        call.kwargs["Name"] for call in stub_aws["ssm"].get_parameter.call_args_list
    ] == ["/nova-toll/i95-token", "/nova-toll/i66-token", "/nova-toll/i95-token"]
    assert fetch.call_count == 5
    assert stub_aws["s3"].put_object.call_count == 5
    assert stub_aws["cloudwatch"].put_metric_data.call_count == 5


def test_empty_event_still_polls_every_feed(
    monkeypatch: pytest.MonkeyPatch, stub_aws: dict[str, MagicMock]
) -> None:
    """A manual invoke and scripts/smoke.sh --fire both send {}."""

    def _callback_4(url: str, timeout: object = None) -> object:
        return io.BytesIO(b"<opt/>")

    monkeypatch.setattr(
        handler.urllib.request,
        "urlopen",
        _callback_4,
    )

    handler.handler({}, None)

    keys = [c.kwargs["Key"] for c in stub_aws["s3"].put_object.call_args_list]
    assert {"i95", "i66"} == {k.split("feed=")[1].split("/")[0] for k in keys}


def test_unknown_feed_is_rejected(stub_aws: dict[str, MagicMock]) -> None:
    with pytest.raises(RuntimeError, match="unknown feed"):
        handler.handler({"feeds": ["i495"]}, None)
    stub_aws["ssm"].get_parameter.assert_not_called()


@pytest.mark.parametrize("drill_id", ["", "ABCDEF0123456789", "../not-a-key"])
def test_drill_id_is_strictly_validated(
    stub_aws: dict[str, MagicMock], drill_id: str
) -> None:
    with pytest.raises(RuntimeError, match="drill_id"):
        handler.handler({"feeds": ["i66"], "drill_id": drill_id}, None)
    stub_aws["ssm"].get_parameter.assert_not_called()


@pytest.mark.parametrize("feeds", ["i95", [1]])
def test_feed_selection_must_be_a_string_list(
    stub_aws: dict[str, MagicMock], feeds: str | list[int]
) -> None:
    with pytest.raises(RuntimeError, match="list of strings"):
        handler.handler({"feeds": feeds}, None)
    stub_aws["ssm"].get_parameter.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["fetch", "ssm", "s3", "cloudwatch"])
def test_token_never_appears_in_logs_or_exception(
    monkeypatch: pytest.MonkeyPatch,
    stub_aws: dict[str, MagicMock],
    caplog: pytest.LogCaptureFixture,
    failure_stage: str,
) -> None:
    caplog.set_level(logging.INFO)

    def fake_urlopen(url: str, timeout: float | None = None) -> io.BytesIO:
        if failure_stage == "fetch":
            raise urllib.error.URLError(f"connection refused for {url}")
        return io.BytesIO(b"feed")

    monkeypatch.setattr(handler.urllib.request, "urlopen", fake_urlopen)
    failures = {
        "ssm": stub_aws["ssm"].get_parameter,
        "s3": stub_aws["s3"].put_object,
        "cloudwatch": stub_aws["cloudwatch"].put_metric_data,
    }
    if failure_stage in failures:
        failures[failure_stage].side_effect = RuntimeError(
            f"unsanitized failure: {TOKEN_I95} {TOKEN_I66}"
        )

    with pytest.raises(RuntimeError) as exc_info:
        handler.handler({}, None)

    assert TOKEN_I95 not in caplog.text
    assert TOKEN_I66 not in caplog.text
    assert TOKEN_I95 not in str(exc_info.value)
    assert TOKEN_I66 not in str(exc_info.value)
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert TOKEN_I95 not in rendered
    assert TOKEN_I66 not in rendered
    assert not any(record.exc_info for record in caplog.records)
