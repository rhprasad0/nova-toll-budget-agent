"""Deterministic billing checks; never use deployed data or credentials."""

import io
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from lambdas.publisher import costs

NOW = datetime(2026, 9, 18, 10, tzinfo=UTC)


def aws_pages(period, values=("0.1", "0.2")):
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


def source(environment, now=NOW, values=("0.1", "0.2")):
    period = costs.requested(costs.periods(now.date()))
    return costs.collect_aws(
        Mock(get_cost_and_usage=Mock(side_effect=aws_pages(period, values))),
        costs.ACCOUNTS[environment],
        period,
        costs.utc_text(now - timedelta(hours=1)),
    )


def fixture(environment="production", now=NOW):
    period = costs.requested(costs.periods(now.date()))
    sources = {
        "aws_development": source("development", now),
        "openai": costs.blank_source("openai", period, environment == "development"),
    }
    if environment == "production":
        sources["aws_production"] = source("production", now, ("0.000000001", "-0.02"))
        sources["openai"].update(
            status="available",
            retrieved_at=costs.utc_text(now - timedelta(minutes=10)),
            daily=[{"date": day, "usd": "0.4"} for day in costs.dates(period)],
        )
    return costs.build_snapshot(environment, now, sources)


def test_publication_after_midnight_preserves_requested_utc_period():
    started = NOW.replace(hour=23, minute=59)
    completed = started + timedelta(minutes=2)
    sources = fixture("development", started)["sources"]
    sources["aws_development"]["retrieved_at"] = costs.utc_text(completed)
    snapshot = costs.build_snapshot(
        "development", started, sources, published_at=completed
    )
    assert snapshot["requested"]["end_exclusive"] == started.date().isoformat()
    assert snapshot["published_at"] == costs.utc_text(completed)


def test_aws_pagination_account_filter_and_exact_credits():
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


def test_aws_missing_days_bad_currency_and_repeated_pages_fail():
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


def test_ungrouped_aws_charges_are_included():
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


def test_openai_all_pages_all_charges_and_no_filters(monkeypatch):
    period = {"start": "2026-09-16", "end_exclusive": "2026-09-18"}

    def bucket(day, results):
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
def test_month_boundaries_and_empty_month(today):
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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(environment="production"),
        lambda s: s.update(scope="aws-production+aws-development+openai-organization"),
        lambda s: s.update(currency="EUR"),
        lambda s: s.update(schema_version=2),
        lambda s: s.update(api_key="private"),
        lambda s: s["sources"]["aws_development"].update(scope="production-account"),
        lambda s: s["sources"]["aws_development"].update(currency="EUR"),
        lambda s: s["sources"]["aws_development"].update(account_id="private"),
        lambda s: s["sources"]["aws_development"]["daily"].pop(),
        lambda s: s["sources"]["aws_development"]["daily"][0].update(usd="NaN"),
        lambda s: s["sources"]["aws_development"]["aws_services"][0].update(usd="999"),
        lambda s: s["sources"]["aws_development"]["aws_services"][0].update(
            label="private-resource-id"
        ),
        lambda s: s["sources"]["aws_development"].update(
            finalized_through="2026-09-17"
        ),
        lambda s: s["month_to_date"].update(aws="999"),
        lambda s: s["daily"][0].update(total="0"),
        lambda s: s.update(published_at="2026-09-19T00:00:00Z"),
        lambda s: s["requested"].update(end_exclusive="2026-09-17"),
        lambda s: s["attempt"].update(status="failed"),
    ],
)
def test_reject_invalid_development_aggregates(mutate):
    value = fixture("development")
    mutate(value)
    with pytest.raises((ValueError, KeyError, TypeError)):
        costs.development_source(value, costs.requested(costs.periods(NOW.date())), NOW)


def test_development_freshness_and_last_valid_retention():
    dev = fixture("development")
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


def test_redirect_origin_duplicate_fields_and_oversized_body_rejected():
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


def test_handler_preserves_data_and_sanitizes_provider_failure(monkeypatch):
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
    clients = []

    def client(name, **_):
        clients.append(name)
        assert name in {"s3", "ce"}
        return {"s3": s3, "ce": ce}[name]

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
    assert clients == ["s3", "ce"]
    s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied"}}, "GetObject"
    )
    s3.put_object.reset_mock()
    with pytest.raises(RuntimeError, match="cost_snapshot_read_failed"):
        costs.handler({}, context)
    s3.put_object.assert_not_called()
    s3.list_objects_v2.return_value = {}
    s3.get_object.reset_mock()
    period = costs.requested(costs.periods(datetime.now(UTC).date()))
    ce.get_cost_and_usage.side_effect = aws_pages(period)
    assert costs.handler({}, context) == {"status": "succeeded"}
    s3.get_object.assert_not_called()
    s3.list_objects_v2.assert_called_with(
        Bucket="tollchat-site-903859731897-dev", Prefix="costs.json", MaxKeys=1
    )
    first = json.loads(s3.put_object.call_args.kwargs["Body"])
    assert first["sources"]["aws_development"]["status"] == "available"
    assert first["month_to_date"]["total"] is None


def test_deterministic_public_fixtures():
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
