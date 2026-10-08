"""Deterministic billing checks; never use deployed data or credentials."""

import io
import json
import logging
import urllib.error
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
from botocore.exceptions import ClientError

from lambdas.publisher import costs

NOW = datetime(2026, 9, 18, 10, tzinfo=UTC)


def aws_pages(
    period: dict[str, str], values: Sequence[str] = ("0.1", "0.2")
) -> list[dict[str, Any]]:
    return [
        {
            "ResultsByTime": [
                {
                    "TimePeriod": {
                        "Start": day,
                        "End": (
                            date.fromisoformat(day) + timedelta(days=1)
                        ).isoformat(),
                    },
                    "Estimated": True,
                    "Total": {},
                    "Groups": [
                        {
                            "Keys": [
                                "AWS Lambda" if i == 0 else "private-resource-id",
                                "environment$development"
                                if i == 0
                                else "environment$private-tag",
                            ],
                            "Metrics": {
                                "UnblendedCost": {"Amount": value, "Unit": "USD"}
                            },
                        }
                    ],
                }
                for day in costs.dates(period)
            ],
            **({"NextPageToken": "second"} if i == 0 else {}),
        }
        for i, value in enumerate(values)
    ]


def source(
    environment: str, now: datetime = NOW, values: Sequence[str] = ("0.1", "0.2")
) -> dict[str, Any]:
    period = costs.requested(costs.periods(now.date()))
    return costs.collect_aws(
        Mock(get_cost_and_usage=Mock(side_effect=aws_pages(period, values))),
        costs.ACCOUNTS[environment],
        period,
        costs.utc_text(
            max(
                now - timedelta(hours=1),
                now.replace(hour=0, minute=0, second=0, microsecond=0),
            )
        ),
    )


def fixture(environment: str = "production", now: datetime = NOW) -> dict[str, Any]:
    period = costs.requested(costs.periods(now.date()))
    sources = {
        "aws_development": source("development", now),
        "openai": costs.blank_source("openai", period),
    }
    if environment == "production":
        sources["aws_production"] = source("production", now, ("0.000000001", "-0.02"))
    sources["openai"].update(
        status="available",
        retrieved_at=costs.utc_text(
            max(
                now - timedelta(minutes=10),
                now.replace(hour=0, minute=0, second=0, microsecond=0),
            )
        ),
        daily=[{"date": day, "usd": "0.4"} for day in costs.dates(period)],
    )
    return costs.build_snapshot(environment, now, sources)


def aws_feed(now: datetime = NOW) -> dict[str, Any]:
    sources = fixture("development", now)["sources"]
    sources["openai"] = costs.blank_source(
        "openai", sources["openai"]["requested"], True
    )
    return costs.build_snapshot("development", now, sources, aws_only=True)


def http_error(
    status: int = 503,
    retry_after: str | None = None,
    *,
    body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    for name, value in (extra_headers or {}).items():
        headers[name] = value
    return urllib.error.HTTPError(
        costs.OPENAI_URL,
        status,
        "private-secret",
        headers,
        io.BytesIO(body) if body is not None else None,
    )


def mock_reader(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[object], raw: bytes = b"{}"
) -> tuple[Mock, Mock]:
    response = MagicMock(status=200, url=costs.OPENAI_URL)
    response.read.return_value = raw
    response.__enter__.return_value = response
    opener = Mock(open=Mock(side_effect=[*outcomes, response]))
    sleep = Mock()
    monkeypatch.setattr(costs.urllib.request, "build_opener", Mock(return_value=opener))
    monkeypatch.setattr(costs.time, "sleep", sleep)
    return opener.open, sleep


@pytest.mark.parametrize(
    "failure",
    [
        http_error(),
        urllib.error.HTTPError(
            costs.OPENAI_URL,
            503,
            "private-secret",
            None,  # pyright: ignore[reportArgumentType] - urllib accepts absent headers
            None,
        ),
        urllib.error.URLError("private-secret"),
        TimeoutError("private-secret"),
        ConnectionResetError("private-secret"),
    ],
)
def test_https_transient_failure_then_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: Exception,
) -> None:
    request, sleep = mock_reader(monkeypatch, [failure, failure])
    budget = Mock()
    assert costs.get_json(costs.OPENAI_URL, "private-secret", budget) == {}
    assert request.call_count == 3
    assert [call.args for call in sleep.call_args_list] == [(2,), (5,)]
    expected_budget = [
        (20,),
        (22,),
        (20,),
        (25,),
        (20,),
    ]
    if isinstance(failure, urllib.error.HTTPError):
        expected_budget.insert(1, (20,))
        expected_budget.insert(4, (20,))
    assert [call.args for call in budget.call_args_list] == expected_budget
    assert all(call.kwargs["timeout"] == 20 for call in request.call_args_list)
    assert "source=openai attempt=1" in caplog.text
    assert "source=openai attempt=2" in caplog.text
    assert "private-secret" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_https_retry_exhaustion(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    error = http_error(status)
    request, sleep = mock_reader(monkeypatch, [error] * 3)
    with pytest.raises(urllib.error.HTTPError):
        costs.get_json(costs.OPENAI_URL, "test-key")
    assert request.call_count == 3 and sleep.call_count == 2


@pytest.mark.parametrize(
    "failure",
    [
        http_error(400),
        http_error(401),
        http_error(403),
        http_error(404),
        http_error(302),
        ValueError("billing_redirect"),
    ],
)
def test_https_permanent_errors_are_not_retried(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    request, sleep = mock_reader(monkeypatch, [failure])
    with pytest.raises(type(failure)):
        costs.get_json(costs.OPENAI_URL, "test-key")
    assert request.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("7", 7),
        ("999", 30),
        ("9" * 5000, 30),
        ("0" * 5000 + "7", 7),
        ("0", 0),
        ("-1", 2),
        ("garbage", 2),
    ],
)
def test_https_retry_after(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: float
) -> None:
    _, sleep = mock_reader(monkeypatch, [http_error(429, value)])
    assert costs.get_json(costs.OPENAI_URL, "test-key") == {}
    sleep.assert_called_once_with(expected)


def test_retry_after_http_date() -> None:
    from email.utils import format_datetime

    later = datetime.now(UTC) + timedelta(seconds=12)
    delay = costs.retry_delay(http_error(503, format_datetime(later, usegmt=True)), 2)
    assert 10 <= delay <= 12
    assert (
        costs.retry_delay(
            http_error(503, format_datetime(later + timedelta(minutes=1), usegmt=True)),
            2,
        )
        == 30
    )
    assert (
        costs.retry_delay(
            http_error(503, format_datetime(later - timedelta(minutes=1), usegmt=True)),
            2,
        )
        == 0
    )


def test_https_malformed_response_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request, sleep = mock_reader(monkeypatch, [], b'{"duplicate":1,"duplicate":2}')
    with pytest.raises(ValueError):
        costs.get_json(costs.OPENAI_URL, "test-key")
    assert request.call_count == 1
    sleep.assert_not_called()
    assert "error=ValueError status=200" in caplog.text


def test_https_body_timeout_is_retried(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    response = MagicMock(status=200, url=costs.OPENAI_URL)
    response.__enter__.return_value = response
    response.read.side_effect = [TimeoutError("private-secret"), b"{}"]
    request, sleep = mock_reader(monkeypatch, [response, response])
    assert costs.get_json(costs.OPENAI_URL, "private-secret") == {}
    assert request.call_count == 2
    sleep.assert_called_once_with(2)
    assert "error=TimeoutError status=200" in caplog.text
    assert "private-secret" not in caplog.text


def test_https_429_diagnostics_and_actual_retry_delay(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    error = http_error(
        429,
        "61",
        body=json.dumps(
            {
                "error": {
                    "code": "rate_limit_exceeded",
                    "type": "requests",
                    "message": "private-secret org-private project-private",
                }
            }
        ).encode(),
        extra_headers={
            "x-request-id": "req_" + "a" * 32,
            "x-ratelimit-limit-requests": "60",
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-reset-requests": "1m1.5s",
            "Authorization": "Bearer private-secret",
            "openai-organization": "org-private",
        },
    )
    _, sleep = mock_reader(monkeypatch, [error])
    assert costs.get_json(costs.OPENAI_URL, "private-secret") == {}
    sleep.assert_called_once_with(30)
    failure = next(
        r.getMessage() for r in caplog.records if "COST_REQUEST_FAILED" in r.message
    )
    diagnostics = json.loads(failure.split("diagnostics=", 1)[1])
    assert diagnostics == {
        "provider_code": "rate_limit_exceeded",
        "provider_type": "requests",
        "x-request-id": "req_" + "a" * 32,
        "x-ratelimit-limit-requests": "60",
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-requests": "1m1.5s",
        "retry-after": "61",
        "body_kind": "json_error",
    }
    assert "COST_REQUEST_RETRY source=openai attempt=1 delay_seconds=30" in caplog.text
    assert not any(
        value in caplog.text
        for value in ["private-secret", "org-private", "project-private"]
    )


@pytest.mark.parametrize(
    "code,error_type",
    [
        ("slow_down", "rate_limit_error"),
        ("insufficient_quota", "insufficient_quota"),
        ("credit_balance_exhausted", "insufficient_quota"),
        ("organization_spend_limit_exceeded", "insufficient_quota"),
        ("project_spend_limit_exceeded", "insufficient_quota"),
        ("organization_usage_limit_exceeded", "insufficient_quota"),
    ],
)
def test_openai_error_classification(code: str, error_type: str) -> None:
    error = http_error(
        429, body=json.dumps({"error": {"code": code, "type": error_type}}).encode()
    )
    diagnostic = costs.openai_error_diagnostics(error, lambda seconds: None)
    assert diagnostic["provider_code"] == code
    assert diagnostic["provider_type"] == error_type
    assert diagnostic["body_kind"] == "json_error"


@pytest.mark.parametrize(
    "body,kind",
    [
        (b"<html>private-secret</html>", "html"),
        (b" <!DOCTYPE html><html>private-secret</html>", "html"),
        (b"not json private-secret", "malformed"),
        (b'{"error":{"code":"rate_limit_exceeded"},"error":{}}', "malformed"),
        (b'{"error":[]}', "malformed"),
        (b"\xff", "malformed"),
        (b"x" * (costs.MAX_ERROR_BODY + 1), "oversized"),
        (b"", "empty"),
    ],
)
def test_openai_unusual_error_bodies(body: bytes, kind: str) -> None:
    error = http_error(429, body=body)
    diagnostic = costs.openai_error_diagnostics(error, lambda seconds: None)
    assert diagnostic["body_kind"] == kind
    assert diagnostic["provider_code"] == "unknown"
    assert "private-secret" not in json.dumps(diagnostic)


def test_openai_untrusted_diagnostic_fields(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    error = http_error(
        401,
        "private-secret\nCOST_REFRESH_SUCCEEDED",
        body=b'{"error":{"code":"private-secret","type":{"private-secret":true},"message":"private-secret"}}',
        extra_headers={
            "x-request-id": "req_private-secret",
            "x-ratelimit-limit-requests": "9" * 129,
            "x-ratelimit-remaining-requests": "private-secret",
            "x-ratelimit-reset-requests": "1s\nprivate-secret",
        },
    )
    request, sleep = mock_reader(monkeypatch, [error])
    with pytest.raises(urllib.error.HTTPError) as failure:
        costs.get_json(costs.OPENAI_URL, "private-secret")
    assert failure.value is error
    assert request.call_count == 1
    sleep.assert_not_called()
    assert "private-secret" not in caplog.text
    assert "COST_REFRESH_SUCCEEDED" not in caplog.text
    assert "reason=permanent" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_openai_diagnostic_read_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    error = http_error(429, body=b"x" * (costs.MAX_ERROR_BODY + 100))
    read = Mock(wraps=error.read)
    monkeypatch.setattr(error, "read", read)
    assert (
        costs.openai_error_diagnostics(error, lambda seconds: None)["body_kind"]
        == "oversized"
    )
    read.assert_called_once_with(costs.MAX_ERROR_BODY + 1)


@pytest.mark.parametrize("read_error", [TimeoutError, ValueError])
def test_openai_diagnostic_read_failure_preserves_original_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    read_error: type[Exception],
) -> None:
    error = http_error(429, body=b"not read")
    monkeypatch.setattr(error, "read", Mock(side_effect=read_error("private-secret")))
    request, sleep = mock_reader(monkeypatch, [error] * 3)
    with pytest.raises(urllib.error.HTTPError) as failure:
        costs.get_json(costs.OPENAI_URL, "test-key")
    assert failure.value is error
    assert request.call_count == 3 and sleep.call_count == 2
    assert '"body_kind":"unreadable"' in caplog.text
    assert "reason=exhausted" in caplog.text
    assert "private-secret" not in caplog.text


def test_openai_html_content_type_and_close_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = http_error(
        429,
        body=b"<head>private-secret</head>",
        extra_headers={"Content-Type": "text/html; charset=utf-8"},
    )
    monkeypatch.setattr(
        error, "close", Mock(side_effect=RuntimeError("private-secret"))
    )
    diagnostic = costs.openai_error_diagnostics(error, lambda seconds: None)
    assert diagnostic["body_kind"] == "html"
    assert "private-secret" not in json.dumps(diagnostic)


def test_openai_diagnostic_respects_publication_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = http_error(429, body=b"not read")
    read = Mock(wraps=error.read)
    monkeypatch.setattr(error, "read", read)
    budget = Mock(side_effect=ValueError("private-secret"))
    assert (
        costs.openai_error_diagnostics(error, budget)["body_kind"] == "skipped_budget"
    )
    budget.assert_called_once_with(20)
    read.assert_not_called()
    assert error.closed


@pytest.mark.parametrize("remaining,requests", [(79000, 0), (81000, 1), (82000, 1)])
def test_https_publication_budget(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    remaining: int,
    requests: int,
) -> None:
    request, sleep = mock_reader(monkeypatch, [http_error()])
    checks = iter([remaining, remaining, remaining, 79000])

    def budget(seconds: float) -> None:
        costs.require(next(checks) >= 60000 + seconds * 1000)

    with pytest.raises(ValueError):
        costs.get_json(costs.OPENAI_URL, "test-key", budget)
    assert request.call_count == requests
    assert sleep.call_count == (1 if remaining == 82000 else 0)
    assert "reason=budget" in caplog.text
    assert ("COST_REQUEST_RETRY" in caplog.text) == (remaining == 82000)


def test_aws_feed_failure_retains_original_publication() -> None:
    previous = aws_feed()
    now = NOW + timedelta(days=1)
    period = costs.requested(costs.periods(now.date()))
    failed = costs.build_snapshot(
        "development",
        now,
        {
            "aws_development": costs.blank_source("aws_development", period),
            "openai": costs.blank_source("openai", period, True),
        },
        previous,
        aws_only=True,
    )
    assert failed["scope"] == "aws-development"
    assert failed["attempt"]["status"] == "failed"
    assert failed["published_at"] == previous["published_at"]
    assert failed["sources"] == previous["sources"]
    with pytest.raises(ValueError):
        costs.development_source(failed, period, now)


def test_production_rejects_failed_mismatched_and_old_retrieval_feeds() -> None:
    feed = aws_feed()
    cases = [fixture("development"), aws_feed(NOW - timedelta(days=1))]
    failed = json.loads(json.dumps(feed))
    failed["attempt"]["status"] = "failed"
    failed["attempt"]["sources"]["aws_development"] = "unavailable"
    cases.append(failed)
    old = json.loads(json.dumps(feed))
    later = NOW + timedelta(hours=49)
    old["published_at"] = costs.utc_text(later)
    old["attempt"]["at"] = costs.utc_text(later)
    with pytest.raises(ValueError):
        costs.development_source(old, old["requested"], later)
    for value in cases:
        with pytest.raises(ValueError):
            costs.development_source(value, feed["requested"], NOW)


@pytest.mark.parametrize(
    "failure_key,openai_failure",
    [
        (None, True),
        (costs.AWS_FEED_KEY, True),
        ("costs.json", True),
        (costs.AWS_FEED_KEY, False),
    ],
)
def test_development_openai_outage_does_not_freeze_production(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure_key: str | None,
    openai_failure: bool,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    production = fixture("production", now)
    development = fixture("development", now)
    snapshots: dict[str, dict[str, Any]] = {
        "costs.json": fixture("development", now - timedelta(days=1))
    }
    previous = snapshots["costs.json"]
    s3 = Mock()

    def listed(*, Prefix: str, **_: object) -> dict[str, Any]:
        return {"Contents": [{"Key": Prefix}]} if Prefix in snapshots else {}

    def read(*, Key: str, **_: object) -> dict[str, Any]:
        return {"Body": io.BytesIO(json.dumps(snapshots[Key]).encode())}

    def write(*, Key: str, Body: bytes, **_: object) -> None:
        if Key == failure_key:
            raise RuntimeError("private-secret publication-error")
        snapshots[Key] = json.loads(Body)

    s3.list_objects_v2.side_effect = listed
    s3.get_object.side_effect = read
    s3.put_object.side_effect = write

    def client(name: str, **_: object) -> Mock:
        return {
            "s3": s3,
            "ce": Mock(),
            "ssm": Mock(
                get_parameter=Mock(
                    return_value={"Parameter": {"Value": "private-secret"}}
                )
            ),
        }[name]

    def openai(*_: object) -> dict[str, Any]:
        # The independent AWS write must already have been attempted.
        assert s3.put_object.call_args.kwargs["Key"] == costs.AWS_FEED_KEY
        if openai_failure:
            raise urllib.error.HTTPError(
                costs.OPENAI_URL, 503, "private-secret", Message(), None
            )
        return development["sources"]["openai"]

    monkeypatch.setattr(costs.boto3, "client", client)
    monkeypatch.setattr(
        costs, "collect_aws", Mock(return_value=source("development", now))
    )
    collector = Mock(side_effect=openai)
    monkeypatch.setattr(costs, "collect_openai", collector)
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "development")
    monkeypatch.setenv("COST_BUCKET", "tollchat-site-903859731897-dev")
    context = SimpleNamespace(
        invoked_function_arn="arn:aws:lambda:us-east-1:903859731897:function:test",
        get_remaining_time_in_millis=lambda: 300000,
    )
    assert costs.handler({}, context) == {"status": "failed"}
    assert [call.kwargs["Key"] for call in s3.put_object.call_args_list] == [
        costs.AWS_FEED_KEY,
        "costs.json",
    ]
    if openai_failure:
        assert snapshots["costs.json"]["published_at"] == previous["published_at"]
        assert snapshots["costs.json"]["month_to_date"] == previous["month_to_date"]
        assert "COST_REFRESH_SUCCEEDED snapshot=dashboard" not in caplog.text
    else:
        assert snapshots["costs.json"]["attempt"]["status"] == "succeeded"
        assert snapshots["costs.json"]["month_to_date"] == development["month_to_date"]
        assert "COST_REFRESH_SUCCEEDED snapshot=dashboard" in caplog.text
    assert "private-secret" not in caplog.text
    if failure_key == costs.AWS_FEED_KEY:
        assert "COST_REFRESH_SUCCEEDED snapshot=aws-feed" not in caplog.text
        collector.assert_called_once()
        assert snapshots["costs.json"]["attempt"]["status"] == (
            "failed" if openai_failure else "succeeded"
        )
        return
    feed = snapshots[costs.AWS_FEED_KEY]
    assert (
        feed["scope"] == "aws-development" and feed["attempt"]["status"] == "succeeded"
    )
    assert feed["sources"]["openai"]["status"] == "not_configured"
    assert feed["requested"] == costs.requested(costs.periods(now.date()))
    assert "COST_REFRESH_SUCCEEDED snapshot=aws-feed" in caplog.text
    # Run the real production handler using this freshly published feed.
    snapshots.pop("costs.json")
    failure_key = None
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setenv("COST_BUCKET", "tollchat-site-920534282028")
    context.invoked_function_arn = "arn:aws:lambda:us-east-1:920534282028:function:test"
    monkeypatch.setattr(costs, "get_json", Mock(return_value=feed))
    monkeypatch.setattr(
        costs, "collect_openai", Mock(return_value=production["sources"]["openai"])
    )
    monkeypatch.setattr(
        costs, "collect_aws", Mock(return_value=production["sources"]["aws_production"])
    )
    assert costs.handler({}, context) == {"status": "succeeded"}
    assert snapshots["costs.json"] == costs.validate_snapshot(
        snapshots["costs.json"], "production", datetime.now(UTC)
    )
    assert snapshots["costs.json"]["month_to_date"] == production["month_to_date"]
    assert (
        snapshots["costs.json"]["sources"]["aws_development"]
        == feed["sources"]["aws_development"]
    )


@pytest.mark.parametrize("minute", [0, 9, 30, 60])
def test_fixture_remains_valid_in_first_utc_hour(minute: int) -> None:
    now = NOW.replace(hour=0, minute=0) + timedelta(minutes=minute)
    snapshot = fixture("development", now)
    assert costs.validate_snapshot(snapshot, "development", now) == snapshot


def test_publication_after_midnight_preserves_requested_utc_period() -> None:
    started = NOW.replace(hour=23, minute=59)
    completed = started + timedelta(minutes=2)
    sources = fixture("development", started)["sources"]
    sources["aws_development"]["retrieved_at"] = costs.utc_text(completed)
    snapshot = costs.build_snapshot(
        "development", started, sources, published_at=completed
    )
    assert snapshot["requested"]["end_exclusive"] == started.date().isoformat()
    assert snapshot["published_at"] == costs.utc_text(completed)


def test_aws_pagination_account_filter_and_exact_credits() -> None:
    period = costs.requested(costs.periods(NOW.date()))
    client = Mock(
        get_cost_and_usage=Mock(
            side_effect=aws_pages(period, ("0.100000000000000000000000000001", "-0.2"))
        )
    )
    result = costs.collect_aws(
        client, costs.ACCOUNTS["development"], period, costs.utc_text(NOW)
    )
    assert result["daily"][0]["usd"] == "-0.099999999999999999999999999999"
    first, second = client.get_cost_and_usage.call_args_list
    assert first.kwargs["Filter"] == {
        "Dimensions": {
            "Key": "LINKED_ACCOUNT",
            "Values": [costs.ACCOUNTS["development"]],
        }
    }
    assert second.kwargs["NextPageToken"] == "second"
    assert first.kwargs["Metrics"] == ["UnblendedCost"]
    assert "private" not in json.dumps(result)
    assert result["aws_services"][1]["label"] == "Other AWS services"
    assert result["aws_environments"][1]["label"] == "unallocated"
    assert result["finalized_through"] is None and result["estimated"] is True


def test_aws_missing_days_bad_currency_and_repeated_pages_fail() -> None:
    period = costs.requested(costs.periods(NOW.date()))
    for kind in ("missing", "currency", "repeated"):
        pages = aws_pages(period)
        if kind == "missing":
            for page in pages:
                page["ResultsByTime"].clear()
        elif kind == "currency":
            pages[0]["ResultsByTime"][0]["Groups"][0]["Metrics"]["UnblendedCost"][
                "Unit"
            ] = "EUR"
        else:
            pages[1]["NextPageToken"] = "second"
        with pytest.raises(ValueError):
            costs.collect_aws(
                Mock(get_cost_and_usage=Mock(side_effect=pages)),
                costs.ACCOUNTS["development"],
                period,
                costs.utc_text(NOW),
            )


def test_ungrouped_aws_charges_are_included() -> None:
    period = {"start": "2026-09-17", "end_exclusive": "2026-09-18"}
    page = aws_pages(period)[0]
    page.pop("NextPageToken")
    page["ResultsByTime"][0].update(
        Groups=[], Total={"UnblendedCost": {"Amount": "-1.23", "Unit": "USD"}}
    )
    result = costs.collect_aws(
        Mock(get_cost_and_usage=Mock(return_value=page)),
        costs.ACCOUNTS["development"],
        period,
        costs.utc_text(NOW),
    )
    assert result["daily"] == [{"date": "2026-09-17", "usd": "-1.23"}]
    assert result["aws_environments"] == [{"label": "unallocated", "usd": "-1.23"}]


def test_openai_all_pages_all_charges_and_no_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period = {"start": "2026-09-16", "end_exclusive": "2026-09-18"}

    def bucket(day: str, results: list[dict[str, object]]) -> dict[str, object]:
        start = int(costs.timestamp(day + "T00:00:00Z").timestamp())
        return {"start_time": start, "end_time": start + 86400, "results": results}

    pages = [
        {
            "data": [
                bucket(
                    "2026-09-16",
                    [
                        {
                            "amount": {
                                "value": Decimal("0.1000000000001"),
                                "currency": "usd",
                            },
                            "project_id": "private",
                        },
                        {"amount": {"value": Decimal("-0.1"), "currency": "usd"}},
                    ],
                )
            ],
            "has_more": True,
            "next_page": "second",
        },
        {"data": [bucket("2026-09-17", [])], "has_more": False, "next_page": None},
    ]
    get = Mock(side_effect=pages)
    monkeypatch.setattr(costs, "get_json", get)
    result = costs.collect_openai("test-key", period, costs.utc_text(NOW))
    assert result["daily"] == [
        {"date": "2026-09-16", "usd": "0.0000000000001"},
        {"date": "2026-09-17", "usd": "0"},
    ]
    for call in get.call_args_list:
        assert not any(
            term in call.args[0]
            for term in ("project", "group_by", "api_key", "line_item")
        )
    assert "page=second" in get.call_args_list[1].args[0]
    assert "private" not in json.dumps(result)
    monkeypatch.setattr(
        costs, "get_json", Mock(return_value={"data": [], "has_more": False})
    )
    with pytest.raises(ValueError):
        costs.collect_openai("test-key", period, costs.utc_text(NOW))


@pytest.mark.parametrize(
    "today",
    [
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
        date(2028, 3, 1),
        date(2026, 5, 31),
    ],
)
def test_month_boundaries_and_empty_month(today: date) -> None:
    now = datetime.combine(today, datetime.min.time(), UTC) + timedelta(hours=10)
    snapshot = fixture(now=now)
    assert len(snapshot["daily"]) == 30
    assert (
        snapshot["requested"]["start"]
        == min(today.replace(day=1), today - timedelta(days=30)).isoformat()
    )
    assert snapshot["daily"][-1]["date"] == (today - timedelta(days=1)).isoformat()
    if today.day == 1:
        assert Decimal(snapshot["month_to_date"]["total"]) == 0
        assert snapshot["aws_services"] == []


def _callback_1(s: dict[str, Any]) -> object:
    return s.update(scope="aws-production+aws-development+openai-organization")


def _callback_2(s: dict[str, Any]) -> object:
    return s.update(currency="EUR")


def _callback_3(s: dict[str, Any]) -> object:
    return s.update(schema_version=2)


def _callback_4(s: dict[str, Any]) -> object:
    return s.update(api_key="private")


def _callback_5(s: dict[str, Any]) -> object:
    return s["sources"]["aws_development"].update(scope="production-account")


def _callback_6(s: dict[str, Any]) -> object:
    return s["sources"]["aws_development"].update(currency="EUR")


def _callback_7(s: dict[str, Any]) -> object:
    return s["sources"]["aws_development"].update(account_id="private")


def _callback_8(s: dict[str, Any]) -> object:
    return s["sources"]["aws_development"]["daily"].pop()


def _callback_9(s: dict[str, Any]) -> object:
    return s["sources"]["aws_development"]["daily"][0].update(usd="NaN")


def _callback_10(s: dict[str, Any]) -> object:
    return s["sources"]["aws_development"]["aws_services"][0].update(usd="999")


def _callback_11(s: dict[str, Any]) -> object:
    return s["sources"]["aws_development"]["aws_services"][0].update(
        label="private-resource-id"
    )


def _callback_12(s: dict[str, Any]) -> object:
    return s["sources"]["aws_development"].update(finalized_through="2026-09-17")


def _callback_13(s: dict[str, Any]) -> object:
    return s["daily"][0].update(total="0")


def _callback_14(s: dict[str, Any]) -> object:
    return s.update(published_at="2026-09-19T00:00:00Z")


def _callback_15(s: dict[str, Any]) -> object:
    return s["requested"].update(end_exclusive="2026-09-17")


def _callback_16(s: dict[str, Any]) -> object:
    return s["attempt"].update(status="failed")


def _strict_callback_1(s: dict[str, Any]) -> object:
    return s.update(environment="production")


def _strict_callback_2(s: dict[str, Any]) -> object:
    return s["month_to_date"].update(aws="999")


@pytest.mark.parametrize(
    "mutate",
    [
        _strict_callback_1,
        _callback_1,
        _callback_2,
        _callback_3,
        _callback_4,
        _callback_5,
        _callback_6,
        _callback_7,
        _callback_8,
        _callback_9,
        _callback_10,
        _callback_11,
        _callback_12,
        _strict_callback_2,
        _callback_13,
        _callback_14,
        _callback_15,
        _callback_16,
    ],
)
def test_reject_invalid_development_aggregates(
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    value = aws_feed()
    mutate(value)
    with pytest.raises((ValueError, KeyError, TypeError)):
        costs.development_source(value, costs.requested(costs.periods(NOW.date())), NOW)


def test_development_freshness_and_last_valid_retention() -> None:
    dev = aws_feed()
    assert (
        costs.development_source(dev, dev["requested"], NOW)["scope"]
        == "development-account"
    )
    with pytest.raises(ValueError):
        costs.development_source(dev, dev["requested"], NOW + timedelta(hours=49))
    original = fixture()
    next_day = NOW + timedelta(days=1)
    period = costs.requested(costs.periods(next_day.date()))
    sources = {
        name: costs.blank_source(name, period)
        for name in costs.source_ids("production")
    }
    sources["aws_production"] = source("production", next_day)
    failed = costs.build_snapshot("production", next_day, sources, original)
    assert failed["attempt"]["status"] == "failed"
    assert {key: value for key, value in failed.items() if key != "attempt"} == {
        key: value for key, value in original.items() if key != "attempt"
    }
    partial = costs.build_snapshot("production", next_day, sources)
    assert partial["month_to_date"] == {"aws": None, "openai": None, "total": None}
    assert partial["sources"]["aws_production"]["daily"]
    assert partial["aws_services"]


def test_redirect_origin_duplicate_fields_and_oversized_body_rejected() -> None:
    with pytest.raises(ValueError):
        costs.NoRedirect().redirect_request(None, None, None, None, None, None)
    for url in (
        "http://dev.tollchat.ai/costs.json",
        "https://dev.tollchat.ai.evil/costs.json",
        "https://dev.tollchat.ai/costs.json#fragment",
    ):
        with pytest.raises(ValueError):
            costs.get_json(url)
    with pytest.raises(ValueError):
        costs.get_json(costs.DEVELOPMENT_URL, "test-key")
    with pytest.raises(ValueError):
        costs.decode(b'{"schema_version":1,"schema_version":2}')
    with pytest.raises(ValueError):
        costs.decode(b" " * (costs.MAX_BODY + 1))


def test_handler_preserves_data_and_sanitizes_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    previous = fixture(
        "development",
        datetime.now(UTC).replace(hour=10, microsecond=0) - timedelta(days=1),
    )
    s3 = Mock(
        list_objects_v2=Mock(return_value={"Contents": [{"Key": "costs.json"}]}),
        get_object=Mock(
            return_value={"Body": io.BytesIO(json.dumps(previous).encode())}
        ),
    )
    ce = Mock(get_cost_and_usage=Mock(side_effect=RuntimeError("secret private error")))
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "development")
    monkeypatch.setenv("COST_BUCKET", "tollchat-site-903859731897-dev")
    clients: list[str] = []

    def client(name: str, **_: object) -> Mock:
        clients.append(name)
        assert name in {"s3", "ce", "ssm"}
        return {
            "s3": s3,
            "ce": ce,
            "ssm": Mock(get_parameter=Mock(side_effect=RuntimeError("secret"))),
        }[name]

    monkeypatch.setattr(costs.boto3, "client", client)
    context = SimpleNamespace(
        invoked_function_arn="arn:aws:lambda:us-east-1:903859731897:function:test",
        get_remaining_time_in_millis=lambda: 90000,
    )
    assert costs.handler({}, context) == {"status": "failed"}
    result = json.loads(s3.put_object.call_args.kwargs["Body"])
    assert result["published_at"] == previous["published_at"]
    assert result["daily"] == previous["daily"]
    assert "secret" not in json.dumps(result)
    assert [record.getMessage() for record in caplog.records] == [
        "COST_SOURCE_FAILED source=aws_development attempt=terminal error=RuntimeError status=None",
        "COST_REFRESH_FAILED snapshot=aws-feed stage=collection error=UnavailableSource",
        "COST_SOURCE_FAILED source=openai attempt=terminal error=RuntimeError status=None",
        "COST_REFRESH_FAILED snapshot=dashboard stage=collection error=UnavailableSource",
    ]
    assert all(
        record.levelno == logging.WARNING and record.exc_info is None
        for record in caplog.records
    )
    assert "secret" not in caplog.text
    assert "private error" not in caplog.text
    assert clients == ["s3", "ce", "ssm"]
    s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied"}}, "GetObject"
    )
    s3.put_object.reset_mock()
    assert costs.handler({}, context) == {"status": "failed"}
    assert all(
        call.kwargs["Key"] != "costs.json" for call in s3.put_object.call_args_list
    )
    s3.list_objects_v2.return_value = {}
    s3.get_object.reset_mock()
    period = costs.requested(costs.periods(datetime.now(UTC).date()))
    ce.get_cost_and_usage.side_effect = aws_pages(period)
    assert costs.handler({}, context) == {"status": "failed"}
    s3.get_object.assert_not_called()
    s3.list_objects_v2.assert_called_with(
        Bucket="tollchat-site-903859731897-dev", Prefix="costs.json", MaxKeys=1
    )
    first = json.loads(s3.put_object.call_args.kwargs["Body"])
    assert first["sources"]["aws_development"]["status"] == "available"
    assert first["month_to_date"]["total"] is None


def test_deterministic_public_fixtures() -> None:
    directory = Path(__file__).resolve().parents[3] / "tests/fixtures"
    for environment in costs.ACCOUNTS:
        expected = json.loads((directory / f"costs-{environment}.json").read_text())
        assert expected == fixture(environment)
        public = json.dumps(expected)
        for secret in (
            "account_id",
            "project_id",
            "arn:aws",
            "api_key",
            "chat_content",
            *costs.ACCOUNTS.values(),
        ):
            assert secret not in public


def test_legacy_development_and_production_do_not_double_count_openai() -> None:
    legacy = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "tests/fixtures/costs-development-legacy.json"
        ).read_text()
    )
    dev = fixture("development")
    for snapshot in (legacy, aws_feed()):
        production = fixture()
        production["sources"]["aws_development"] = costs.development_source(
            snapshot, production["requested"], NOW
        )
        assert (
            costs.build_snapshot("production", NOW, production["sources"]) == fixture()
        )
    for snapshot, scope in ((legacy, dev["scope"]), (dev, legacy["scope"])):
        snapshot["scope"] = scope
        with pytest.raises(ValueError):
            costs.validate_snapshot(snapshot, "development", NOW)


@pytest.mark.parametrize("previous_kind", ["none", "legacy", "current"])
@pytest.mark.parametrize(
    "failure", [None, "ParameterNotFound", "AccessDeniedException", "provider"]
)
def test_development_handler_collects_openai_and_retains_last_valid(
    monkeypatch: pytest.MonkeyPatch, previous_kind: str, failure: str | None
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    period = costs.requested(costs.periods(now.date()))
    previous = fixture("development", now - timedelta(days=1))
    if previous_kind == "legacy":
        previous["scope"] = "aws-development"
        previous["sources"]["openai"] = costs.blank_source(
            "openai", previous["requested"], True
        )
        previous["attempt"]["sources"]["openai"] = "not_configured"
        previous.update(costs.summarize(previous["sources"], previous["periods"]))
    s3 = Mock(
        list_objects_v2=Mock(
            return_value={}
            if previous_kind == "none"
            else {"Contents": [{"Key": "costs.json"}]}
        ),
        get_object=Mock(
            return_value={"Body": io.BytesIO(json.dumps(previous).encode())}
        ),
    )
    ssm = Mock(get_parameter=Mock(return_value={"Parameter": {"Value": "test-secret"}}))
    if failure in {"ParameterNotFound", "AccessDeniedException"}:
        ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": failure, "Message": "test-secret"}}, "GetParameter"
        )
    collector = Mock(return_value=fixture("development", now)["sources"]["openai"])
    if failure == "provider":
        collector.side_effect = RuntimeError("test-secret private-provider-error")
    monkeypatch.setattr(costs, "collect_openai", collector)
    clients = {
        "s3": s3,
        "ssm": ssm,
        "ce": Mock(get_cost_and_usage=Mock(side_effect=aws_pages(period))),
    }

    def _strict_callback_3(name: str, **_: object) -> object:
        return clients[name]

    monkeypatch.setattr(costs.boto3, "client", _strict_callback_3)
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "development")
    monkeypatch.setenv("COST_BUCKET", "tollchat-site-903859731897-dev")
    context = SimpleNamespace(
        invoked_function_arn="arn:aws:lambda:us-east-1:903859731897:function:test",
        get_remaining_time_in_millis=lambda: 90000,
    )
    assert costs.handler({}, context) == {
        "status": "failed" if failure else "succeeded"
    }
    ssm.get_parameter.assert_called_once_with(
        WithDecryption=True, Name=costs.BILLING_KEY
    )
    if failure not in {"ParameterNotFound", "AccessDeniedException"}:
        assert collector.call_args.args[:2] == ("test-secret", period)
        assert now <= costs.timestamp(collector.call_args.args[2]) <= datetime.now(UTC)
    result = json.loads(s3.put_object.call_args.kwargs["Body"])
    costs.validate_snapshot(result, "development", datetime.now(UTC))
    assert result["scope"] == "aws-development+openai-organization"
    assert "test-secret" not in json.dumps(result)
    assert "private-provider-error" not in json.dumps(result)
    if failure and previous_kind != "none":
        assert result["daily"] == previous["daily"]
        assert result["month_to_date"] == previous["month_to_date"]
        assert result["published_at"] == previous["published_at"]
        assert (
            result["sources"]["aws_development"]
            == previous["sources"]["aws_development"]
        )
    elif failure:
        assert result["sources"]["aws_development"]["status"] == "available"
        assert result["month_to_date"]["total"] is None
    else:
        assert result["sources"]["openai"]["status"] == "available"
        assert costs.amount(result["month_to_date"]["total"]) == costs.amount(
            result["month_to_date"]["aws"]
        ) + costs.amount(result["month_to_date"]["openai"])
        assert result["requested"] == period
