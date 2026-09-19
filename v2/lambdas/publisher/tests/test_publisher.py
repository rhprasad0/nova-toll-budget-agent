import json
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, NoReturn, Self, cast

import pytest

if TYPE_CHECKING:
    from lambdas.publisher import handler as publisher
else:
    import report_publisher_handler as publisher

type JSON = str | int | float | bool | list[JSON] | dict[str, JSON] | None

EASTERN = publisher._EASTERN


def _row(
    order: int,
    group: int | None = None,
    *,
    path_id: str | None = None,
    area: str | None = None,
    leg_count: int = 1,
) -> dict[str, JSON]:
    group = order if group is None else group
    return {
        "facility": "i95_i495",
        "path_id": path_id or f"path-{order}",
        "path_order": order,
        "pricing_legs": [
            {
                "route_step_id": f"step-{order}-{leg}",
                "facility": "i95_i495",
                "pricing_key": {
                    "od_pair_id": order * 10 + leg,
                    "source_route_key": f"Northbound:route-{order}-{leg}",
                },
            }
            for leg in range(leg_count)
        ],
        "origin_area": area or f"Origin {group}",
        "destination_area": f"Destination {group}",
        "direction": "northbound",
    }


def _valid_rows() -> list[dict[str, JSON]]:
    i66 = [_row(order) for order in range(1, 21)]
    for order, row in enumerate(i66, start=1):
        row["facility"] = "i66"
        row["direction"] = "eastbound"
        cast(list[dict[str, JSON]], row["pricing_legs"])[0]["facility"] = "i66"
        cast(list[dict[str, JSON]], row["pricing_legs"])[0]["pricing_key"] = {
            "source_route_key": f"EB:route-{order}",
            "start_zone_id": 1000 + order,
            "end_zone_id": 2000 + order,
        }
        row["origin_area"] = f"I66 Origin {(order - 1) % 16}"
        row["destination_area"] = f"I66 Destination {(order - 1) % 16}"
    return i66 + [_row(order, (order - 21) % 246) for order in range(21, 583)]


def _paths(*paths: publisher._Path) -> tuple[publisher._Path, ...]:
    return tuple(paths)


def _path(path_id: str, *, legs: int = 1, group: str = "A") -> publisher._Path:
    return publisher._Path(
        path_id,
        1,
        f"Origin {group}",
        f"Destination {group}",
        "northbound",
        tuple(
            publisher._Leg(f"step-{path_id}-{number}", number, f"route-{number}")
            for number in range(legs)
        ),
    )


class _S3:
    def __init__(
        self,
        pages: Sequence[dict[str, JSON]] = (),
        fail_put: str | None = None,
        delete_response: dict[str, JSON] | None = None,
    ) -> None:
        self.pages, self.fail_put, self.delete_response = (
            list(pages),
            fail_put,
            delete_response,
        )
        self.calls: list[tuple[str, str | list[str]]] = []

    def put_object(self, **kwargs: object) -> None:
        self.calls.append(("put", cast(str, kwargs["Key"])))
        if kwargs["Key"] == self.fail_put:
            raise RuntimeError("put failed")

    def get_paginator(self, name: str) -> SimpleNamespace:
        assert name == "list_objects_v2"
        self.calls.append(("paginator", name))
        return SimpleNamespace(paginate=self._paginate)

    def _paginate(self, **kwargs: object) -> Iterator[dict[str, JSON]]:
        return iter(self.pages if kwargs["Prefix"] == "tolls/i95-i495/" else [])

    def delete_objects(self, **kwargs: JSON) -> dict[str, JSON]:
        self.calls.append(
            (
                "delete",
                [
                    str(item["Key"])
                    for item in cast(
                        list[dict[str, JSON]],
                        cast(dict[str, JSON], kwargs["Delete"])["Objects"],
                    )
                ],
            )
        )
        return self.delete_response or {
            "Deleted": cast(dict[str, JSON], kwargs["Delete"])["Objects"]
        }


@pytest.mark.parametrize(
    ("invoked_at", "hours"),
    [
        (datetime(2026, 1, 12, 0, tzinfo=EASTERN), 168),
        (datetime(2026, 3, 9, 0, tzinfo=EASTERN), 167),
        (datetime(2026, 11, 2, 0, tzinfo=EASTERN), 169),
    ],
)
def test_prior_completed_week_uses_elapsed_utc_hours(
    invoked_at: datetime, hours: int
) -> None:
    start, end = publisher._week_window(invoked_at)
    buckets = publisher._hour_starts(start, end)
    assert len(buckets) == hours
    assert buckets[-1] < end.astimezone(UTC)
    if hours == 169:
        repeated = [
            bucket.astimezone(EASTERN)
            for bucket in buckets
            if bucket.astimezone(EASTERN).hour == 1
        ]
        assert len({value.isoformat() for value in repeated}) > 1


def test_descriptor_contract_validates_all_counts_and_collisions_before_s3() -> None:
    rows = _valid_rows()
    paths = publisher._validate_paths(rows)
    assert len(paths) == 582
    rows[21]["path_order"] = 21
    with pytest.raises(ValueError, match="order"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    for index in (20, 266, 512):
        rows[index]["origin_area"], rows[index]["destination_area"] = "Same!", "End!"
    for index in (21, 267, 513):
        rows[index]["origin_area"], rows[index]["destination_area"] = "Same?", "End?"
    with pytest.raises(ValueError, match="collide"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    cast(dict[str, JSON], cast(list[JSON], rows[20]["pricing_legs"])[0])[
        "unexpected"
    ] = "no"
    with pytest.raises(ValueError, match="leg"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    cast(
        dict[str, JSON],
        cast(dict[str, JSON], cast(list[JSON], rows[20]["pricing_legs"])[0])[
            "pricing_key"
        ],
    )["source_route_key"] = "Southbound:wrong-series"
    with pytest.raises(ValueError, match="leg"):
        publisher._validate_paths(rows)


def test_descriptor_filters_global_i66_orders_and_rejects_other_facilities() -> None:
    rows = _valid_rows()
    assert publisher._validate_paths(rows)[0].order == 1
    rows[20]["direction"] = "eastbound"
    with pytest.raises(ValueError, match="malformed"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    rows[0]["pricing_legs"] = []
    with pytest.raises(ValueError, match="malformed"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    rows[20]["path_id"] = rows[0]["path_id"]
    with pytest.raises(ValueError, match="malformed"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    rows[0]["direction"] = "northbound"
    with pytest.raises(ValueError, match="direction"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    rows[0]["facility"] = "unknown"
    with pytest.raises(ValueError, match="unsupported"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    for row in rows:
        row["path_order"] = cast(int, row["path_order"]) + 1
    with pytest.raises(ValueError, match="global order"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    rows[19], rows[20] = rows[20], rows[19]
    with pytest.raises(ValueError, match="global"):
        publisher._validate_paths(rows)


def test_revision_dedupe_cutoff_and_complete_multi_leg_totals() -> None:
    start = datetime(2026, 1, 5, tzinfo=EASTERN)
    end = datetime(2026, 1, 12, tzinfo=EASTERN)
    interval = start.astimezone(UTC)
    selected = publisher._selected_prices(
        [
            {
                "interval_end_at": interval,
                "calculated_at": interval,
                "s3_key": "a",
                "zone_toll_rate_usd": "1.00",
            },
            {
                "interval_end_at": interval,
                "calculated_at": interval,
                "s3_key": "b",
                "zone_toll_rate_usd": "2.00",
            },
            {
                "interval_end_at": interval,
                "calculated_at": end.astimezone(UTC),
                "s3_key": "future",
                "zone_toll_rate_usd": "9.00",
            },
        ],
        start,
        end,
        interval,
    )
    assert selected == {interval: Decimal("2.00")}
    path = _path("one", legs=2)
    rows = publisher._hourly_rows(
        _paths(path), {"one": [selected, {interval: Decimal("3.00")}]}, start, end
    )
    first = rows[path.group][0]
    assert (
        first["observed_count"],
        first["minimum"],
        first["median"],
        first["maximum"],
    ) == (1, "5.00", "5.00", "5.00")
    missing = publisher._hourly_rows(_paths(path), {"one": [selected, {}]}, start, end)[
        path.group
    ][0]
    assert (
        missing["status"] == "missing"
        and missing["observed_count"] == 0
        and missing["minimum"] is None
    )


def test_off_cadence_source_interval_is_pre_mutation_and_recorded_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    paths = publisher._validate_paths(_valid_rows())
    start = datetime(2026, 1, 5, tzinfo=EASTERN)
    interval = start.astimezone(UTC).replace(minute=1)
    s3 = _S3()

    def _callback_1(*_args: object) -> object:
        return [
            {
                "interval_end_at": interval,
                "calculated_at": interval,
                "s3_key": "source",
                "zone_toll_rate_usd": "1.00",
            }
        ]

    monkeypatch.setattr(
        publisher,
        "_source_rows",
        _callback_1,
    )
    with pytest.raises(ValueError, match="ten-minute cadence"):
        publisher._publish(
            paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    assert s3.calls == []
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1


def test_multi_path_partial_coverage_and_even_median_are_honest() -> None:
    start, end = (
        datetime(2026, 1, 5, tzinfo=EASTERN),
        datetime(2026, 1, 12, tzinfo=EASTERN),
    )
    interval = start.astimezone(UTC)
    first, second = _path("one"), _path("two")
    rows = publisher._hourly_rows(
        _paths(first, second),
        {"one": [{interval: Decimal("1.00")}], "two": [{interval: Decimal("3.00")}]},
        start,
        end,
    )[first.group]
    assert rows[0]["observed_count"] == 2
    assert rows[0]["expected_count"] == 12
    assert rows[0]["median"] == "2.00"


def test_public_document_and_html_contain_only_broad_data_and_escape_text() -> None:
    path = _path("x", group="<unsafe>")
    start, end = (
        datetime(2026, 1, 5, tzinfo=EASTERN),
        datetime(2026, 1, 12, tzinfo=EASTERN),
    )
    document = publisher._report_document(
        path,
        1,
        start,
        end,
        [
            {
                "utc_start": "2026-01-05T05:00:00Z",
                "local_start": "<unsafe>",
                "status": "missing",
                "observed_count": 0,
                "expected_count": 6,
                "minimum": None,
                "median": None,
                "maximum": None,
            }
        ],
    )
    assert set(document) == {
        "schema_version",
        "facility",
        "route",
        "week",
        "cadence_minutes",
        "path_count",
        "hours",
    }
    assert "route_step_id" not in json.dumps(document)
    html = publisher._render_report_html(
        document, "https://example.invalid/?x=<unsafe>"
    )
    assert "&lt;unsafe&gt;" in html and "?x=&lt;unsafe&gt;" in html


def test_publish_is_manifest_last_then_paginates_and_deletes_only_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = publisher._validate_paths(_valid_rows())
    s3 = _S3(
        pages=[
            {"Contents": [{"Key": "tolls/i95-i495/old"}]},
            {"Contents": [{"Key": "tolls/i95-i495/old-two"}]},
        ]
    )

    def _callback_2(*_args: object) -> object:
        return []

    monkeypatch.setattr(publisher, "_source_rows", _callback_2)
    result = publisher._publish(
        paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
    )
    assert result["status"] == "published"
    first_list = next(
        index for index, call in enumerate(s3.calls) if call[0] == "paginator"
    )
    assert all(call[0] == "put" for call in s3.calls[:first_list])
    assert ("delete", ["tolls/i95-i495/old", "tolls/i95-i495/old-two"]) in s3.calls


@pytest.mark.parametrize(
    "failed_key",
    [
        "report",
        "tolls/i95-i495/index.html",
        publisher.MANIFEST_KEY,
    ],
)
def test_precommit_put_failures_never_list_or_delete(
    monkeypatch: pytest.MonkeyPatch, failed_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    paths = publisher._validate_paths(_valid_rows())
    key = (
        f"{publisher._route_key(paths[0])}/report.json"
        if failed_key == "report"
        else failed_key
    )
    s3 = _S3(fail_put=key)

    def _callback_3(*_args: object) -> object:
        return []

    monkeypatch.setattr(publisher, "_source_rows", _callback_3)
    with pytest.raises(RuntimeError, match="put failed"):
        publisher._publish(
            paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    assert all(call[0] == "put" for call in s3.calls)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 1


def test_aggregation_failure_is_pre_mutation_and_recorded_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    paths = publisher._validate_paths(_valid_rows())

    def _callback_4(*_args: object) -> object:
        raise ValueError("bad source")

    monkeypatch.setattr(
        publisher,
        "_source_rows",
        _callback_4,
    )
    with pytest.raises(ValueError, match="bad source"):
        publisher._publish(
            paths, object(), _S3(), "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("list failed"),
        RuntimeError("delete failed"),
        {"Errors": [{"Code": "Denied"}]},
    ],
)
def test_list_and_delete_failures_propagate_once(
    monkeypatch: pytest.MonkeyPatch,
    failure: RuntimeError | dict[str, JSON],
    caplog: pytest.LogCaptureFixture,
) -> None:
    paths = publisher._validate_paths(_valid_rows())
    s3 = _S3(
        pages=[{"Contents": [{"Key": "tolls/i95-i495/old"}]}],
        delete_response=failure if isinstance(failure, dict) else {},
    )
    if str(failure) == "list failed":

        def _callback_5(**_kwargs: object) -> NoReturn:
            raise cast(RuntimeError, failure)

        monkeypatch.setattr(s3, "_paginate", _callback_5)
    if str(failure) == "delete failed":

        def _callback_6(**_kwargs: object) -> NoReturn:
            raise cast(RuntimeError, failure)

        s3.delete_objects = _callback_6

    def _callback_7(*_args: object) -> object:
        return []

    monkeypatch.setattr(publisher, "_source_rows", _callback_7)
    with pytest.raises(RuntimeError):
        publisher._publish(
            paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    assert ("put", publisher.MANIFEST_KEY) in s3.calls
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 1


def test_cleanup_batches_no_more_than_one_thousand_keys() -> None:
    keys: list[JSON] = [
        {"Key": f"tolls/i95-i495/old-{number}"} for number in range(1001)
    ]
    s3 = _S3(pages=[{"Contents": keys}])
    publisher._cleanup_stale(s3, "bucket", set())
    deleted = [call[1] for call in s3.calls if call[0] == "delete"]
    assert [len(batch) for batch in deleted] == [1000, 1]


def test_cleanup_rejects_partial_success_response_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    s3 = _S3(
        pages=[{"Contents": [{"Key": "tolls/i95-i495/old"}]}],
        delete_response={"Deleted": []},
    )
    with pytest.raises(ValueError, match="partial"):
        publisher._cleanup_stale(s3, "bucket", set())
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=delete") == 1


def test_handler_rejects_invalid_publication_switch_before_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "sometimes")

    def _callback_8(**_kwargs: object) -> object:
        return pytest.fail("connected")

    monkeypatch.setattr(publisher, "_connect", _callback_8)
    with pytest.raises(ValueError, match="true or false"):
        publisher.handler({"trigger": "watchdog"}, None)


def test_loader_event_keeps_its_strict_source_key_boundary() -> None:
    event = {
        "source": "tollchat.pricing-loader",
        "detail-type": "I95 Pricing Load Committed",
        "detail": {
            "environment": "production",
            "schema_version": 1,
            "facility": "i95_i495",
            "source_watermark": "2026-01-12T05:00:00Z",
            "source_key": "not-a-loader-key",
            "row_count": 1,
        },
    }
    with pytest.raises(ValueError):
        publisher._expected_watermark(event)


def test_smoke_log_uses_the_exact_correlated_digest_shape(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Connection:
        def cursor(self) -> "Self":
            return self

        def transaction(self) -> "Self":
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_9(**_kwargs: object) -> object:
        return _Connection()

    monkeypatch.setattr(publisher, "_connect", _callback_9)

    def _callback_10(_service: object) -> object:
        return object()

    monkeypatch.setattr(publisher.boto3, "client", _callback_10)

    def _callback_11(_connection: object) -> object:
        return []

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_11)

    def _callback_12(_rows: object) -> object:
        return ()

    monkeypatch.setattr(publisher, "_validate_paths", _callback_12)
    digest = "a" * 64

    def _callback_13(*_args: object) -> object:
        return {
            "status": "published",
            "generation_id": "2026-01-12T05:00:00Z",
            "route_count": 246,
            "result_sha256": digest,
        }

    monkeypatch.setattr(
        publisher,
        "_publish",
        _callback_13,
    )

    def _callback_14(*_args: object) -> object:
        return None

    monkeypatch.setattr(publisher, "_log_success", _callback_14)
    smoke_id = "123e4567-e89b-12d3-a456-426614174000"
    result = publisher.handler({"trigger": "watchdog", "smoke_id": smoke_id}, None)
    assert result["result_sha256"] == digest
    assert (
        f"V2_REPORT_SMOKE_OK {smoke_id} published 2026-01-12T05:00:00Z {digest}"
        in caplog.text
    )


def test_reader_transaction_setup_precedes_source_reads_and_connections_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class _Cursor:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str) -> None:
            calls.append(sql)

    class _Connection:
        def __init__(self) -> None:
            self.closed = False

        def transaction(self) -> "Self":
            return self

        def cursor(self) -> "_Cursor":
            return _Cursor()

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    report, reader = _Connection(), _Connection()
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_15(**_kwargs: object) -> object:
        return next(connections)

    monkeypatch.setattr(publisher, "_connect", _callback_15)

    def _callback_16(_service: object) -> object:
        return object()

    monkeypatch.setattr(publisher.boto3, "client", _callback_16)

    def _callback_17(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_17)

    def _callback_18(*_args: object) -> object:
        return calls.append("source") or (_ for _ in ()).throw(
            RuntimeError("source failed")
        )

    monkeypatch.setattr(
        publisher,
        "_publish",
        _callback_18,
    )
    with pytest.raises(RuntimeError, match="source failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert calls[:2] == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET LOCAL statement_timeout = '180s'",
    ]
    assert calls[-1] == "source"
    assert report.closed and reader.closed


@pytest.mark.parametrize("failure", ["transaction", "timeout"])
def test_reader_setup_failure_records_once_before_source_or_s3(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    calls: list[object] = []

    class _Transaction:
        def __enter__(self) -> Self:
            if failure == "transaction":
                raise RuntimeError("transaction entry failed")
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class _Cursor:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str) -> None:
            calls.append(sql)
            if failure == "timeout" and "statement_timeout" in sql:
                raise RuntimeError("timeout setup failed")

    class _Connection:
        def __init__(self) -> None:
            self.closed = False

        def transaction(self) -> "_Transaction":
            return _Transaction()

        def cursor(self) -> "_Cursor":
            return _Cursor()

        def close(self) -> None:
            self.closed = True

    report, reader = _Connection(), _Connection()
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_19(**_kwargs: object) -> object:
        return next(connections)

    monkeypatch.setattr(publisher, "_connect", _callback_19)

    def _callback_20(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_20)

    def _callback_21(*_args: object) -> object:
        return pytest.fail("source read")

    monkeypatch.setattr(publisher, "_publish", _callback_21)

    def _callback_22(_service: object) -> object:
        return pytest.fail("s3 client")

    monkeypatch.setattr(publisher.boto3, "client", _callback_22)

    def _callback_23(*_args: object) -> object:
        return pytest.fail("success")

    monkeypatch.setattr(publisher, "_log_success", _callback_23)
    with pytest.raises(RuntimeError):
        publisher.handler({"trigger": "watchdog"}, None)
    if failure == "timeout":
        assert calls == [
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
            "SET LOCAL statement_timeout = '180s'",
        ]
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    assert report.closed and reader.closed


def test_report_connection_acquisition_records_once_before_all_work(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")

    def _callback_24(**_kwargs: object) -> object:
        raise RuntimeError("report connect failed")

    monkeypatch.setattr(
        publisher,
        "_connect",
        _callback_24,
    )

    def _callback_25(*_args: object) -> object:
        return pytest.fail("source")

    monkeypatch.setattr(publisher, "_publish", _callback_25)

    def _callback_26(_service: object) -> object:
        return pytest.fail("s3")

    monkeypatch.setattr(publisher.boto3, "client", _callback_26)

    def _callback_27(*_args: object) -> object:
        return pytest.fail("success")

    monkeypatch.setattr(publisher, "_log_success", _callback_27)
    with pytest.raises(RuntimeError, match="report connect failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1


def test_reader_connection_acquisition_records_once_and_closes_report(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Report:
        closed = False

        def close(self) -> None:
            self.closed = True

    report = _Report()
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_28(**kwargs: object) -> object:
        return (
            (_ for _ in ()).throw(RuntimeError("reader connect failed"))
            if kwargs
            else report
        )

    monkeypatch.setattr(
        publisher,
        "_connect",
        _callback_28,
    )

    def _callback_29(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_29)

    def _callback_30(*_args: object) -> object:
        return pytest.fail("source")

    monkeypatch.setattr(publisher, "_publish", _callback_30)

    def _callback_31(_service: object) -> object:
        return pytest.fail("s3")

    monkeypatch.setattr(publisher.boto3, "client", _callback_31)

    def _callback_32(*_args: object) -> object:
        return pytest.fail("success")

    monkeypatch.setattr(publisher, "_log_success", _callback_32)
    with pytest.raises(RuntimeError, match="reader connect failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    assert report.closed


def test_s3_client_construction_records_once_and_closes_connections(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Connection:
        def __init__(self) -> None:
            self.closed = False

        def transaction(self) -> "Self":
            return self

        def cursor(self) -> "Self":
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    report, reader = _Connection(), _Connection()
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_33(**_kwargs: object) -> object:
        return next(connections)

    monkeypatch.setattr(publisher, "_connect", _callback_33)

    def _callback_34(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_34)

    def _callback_35(_service: object) -> object:
        raise RuntimeError("s3 construction failed")

    monkeypatch.setattr(
        publisher.boto3,
        "client",
        _callback_35,
    )

    def _callback_36(*_args: object) -> object:
        return pytest.fail("source")

    monkeypatch.setattr(publisher, "_publish", _callback_36)

    def _callback_37(*_args: object) -> object:
        return pytest.fail("success")

    monkeypatch.setattr(publisher, "_log_success", _callback_37)
    with pytest.raises(RuntimeError, match="s3 construction failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    assert report.closed and reader.closed


@pytest.mark.parametrize("bucket", [None, "   "])
def test_missing_or_blank_bucket_records_once_before_reader_or_s3(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    bucket: str | None,
) -> None:
    class _Report:
        closed = False

        def close(self) -> None:
            self.closed = True

    report = _Report()
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    if bucket is None:
        monkeypatch.delenv("SITE_BUCKET_NAME", raising=False)
    else:
        monkeypatch.setenv("SITE_BUCKET_NAME", bucket)

    def _callback_38(**kwargs: object) -> object:
        return pytest.fail("reader") if kwargs else report

    monkeypatch.setattr(
        publisher,
        "_connect",
        _callback_38,
    )

    def _callback_39(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_39)

    def _callback_40(_service: object) -> object:
        return pytest.fail("s3")

    monkeypatch.setattr(publisher.boto3, "client", _callback_40)

    def _callback_41(*_args: object) -> object:
        return pytest.fail("source")

    monkeypatch.setattr(publisher, "_publish", _callback_41)

    def _callback_42(*_args: object) -> object:
        return pytest.fail("success")

    monkeypatch.setattr(publisher, "_log_success", _callback_42)
    with pytest.raises((KeyError, ValueError)):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    assert report.closed


@pytest.mark.parametrize("failed_close", ["reader", "report"])
def test_close_failure_after_publication_records_once_and_suppresses_success(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failed_close: str
) -> None:
    class _Connection:
        def __init__(self, name: str) -> None:
            self.name = name
            self.closed = False

        def transaction(self) -> "Self":
            return self

        def cursor(self) -> "Self":
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            return None

        def close(self) -> None:
            self.closed = True
            if self.name == failed_close:
                raise RuntimeError(f"{self.name} close failed")

    report, reader = _Connection("report"), _Connection("reader")
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_43(**_kwargs: object) -> object:
        return next(connections)

    monkeypatch.setattr(publisher, "_connect", _callback_43)

    def _callback_44(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_44)

    def _callback_45(_service: object) -> object:
        return object()

    monkeypatch.setattr(publisher.boto3, "client", _callback_45)

    def _callback_46(*_args: object) -> object:
        return {
            "status": "published",
            "generation_id": "2026-01-12T05:00:00Z",
            "route_count": 246,
            "result_sha256": "a" * 64,
        }

    monkeypatch.setattr(
        publisher,
        "_publish",
        _callback_46,
    )

    def _callback_47(*_args: object) -> object:
        return pytest.fail("success")

    monkeypatch.setattr(publisher, "_log_success", _callback_47)
    with pytest.raises(RuntimeError, match=f"{failed_close} close failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    assert report.closed and reader.closed


def test_close_failure_keeps_underlying_publication_failure_evidence(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Connection:
        def __init__(self, reader: bool = False) -> None:
            self.reader = reader
            self.closed = False

        def transaction(self) -> "Self":
            return self

        def cursor(self) -> "Self":
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            return None

        def close(self) -> None:
            self.closed = True
            if self.reader:
                raise RuntimeError("reader close failed")

    report, reader = _Connection(), _Connection(reader=True)
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_48(**_kwargs: object) -> object:
        return next(connections)

    monkeypatch.setattr(publisher, "_connect", _callback_48)

    def _callback_49(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_49)

    def _callback_50(_service: object) -> object:
        return object()

    monkeypatch.setattr(publisher.boto3, "client", _callback_50)

    def publish_failure(*_args: object) -> None:
        error = RuntimeError("publication failed")
        publisher._record_failure("report_put", error)
        raise error

    monkeypatch.setattr(publisher, "_publish", publish_failure)

    def _callback_51(*_args: object) -> object:
        return pytest.fail("success")

    monkeypatch.setattr(publisher, "_log_success", _callback_51)
    with pytest.raises(RuntimeError, match="reader close failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 2
    assert "phase=report_put" in caplog.text
    assert caplog.text.count("phase=pre_mutation") == 1
    assert report.closed and reader.closed


def test_reader_transaction_exit_after_success_records_once_and_suppresses_success(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Transaction:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            raise RuntimeError("transaction exit failed")

    class _Connection:
        def __init__(self, reader: bool = False) -> None:
            self.reader = reader
            self.closed = False

        def transaction(self) -> "_Transaction | Self":
            return _Transaction() if self.reader else self

        def cursor(self) -> "Self":
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    report, reader = _Connection(), _Connection(reader=True)
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_52(**_kwargs: object) -> object:
        return next(connections)

    monkeypatch.setattr(publisher, "_connect", _callback_52)

    def _callback_53(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_53)

    def _callback_54(_service: object) -> object:
        return object()

    monkeypatch.setattr(publisher.boto3, "client", _callback_54)

    def _callback_55(*_args: object) -> object:
        return {
            "status": "published",
            "generation_id": "2026-01-12T05:00:00Z",
            "route_count": 246,
            "result_sha256": "a" * 64,
        }

    monkeypatch.setattr(
        publisher,
        "_publish",
        _callback_55,
    )

    def _callback_56(*_args: object) -> object:
        return pytest.fail("success")

    monkeypatch.setattr(publisher, "_log_success", _callback_56)
    with pytest.raises(RuntimeError, match="transaction exit failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=reader_finalize") == 1
    assert report.closed and reader.closed


def test_publish_failure_does_not_get_a_second_reader_boundary_record(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Connection:
        def __init__(self) -> None:
            self.closed = False

        def transaction(self) -> "Self":
            return self

        def cursor(self) -> "Self":
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    report, reader = _Connection(), _Connection()
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_57(**_kwargs: object) -> object:
        return next(connections)

    monkeypatch.setattr(publisher, "_connect", _callback_57)

    def _callback_58(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_58)

    def _callback_59(_service: object) -> object:
        return object()

    monkeypatch.setattr(publisher.boto3, "client", _callback_59)

    def publish_failure(*_args: object) -> None:
        error = RuntimeError("publication failed")
        publisher._record_failure("report_put", error)
        raise error

    monkeypatch.setattr(publisher, "_publish", publish_failure)

    def _callback_60(*_args: object) -> object:
        return pytest.fail("success")

    monkeypatch.setattr(publisher, "_log_success", _callback_60)
    with pytest.raises(RuntimeError, match="publication failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 1
    assert "phase=report_put" in caplog.text
    assert "phase=pre_mutation" not in caplog.text
    assert report.closed and reader.closed


@pytest.mark.parametrize("inner_failure", ["publish", "s3"])
def test_reader_exit_records_a_distinct_unwinding_failure_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    inner_failure: str,
) -> None:
    class _Transaction:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            raise RuntimeError("reader transaction exit failed")

    class _Connection:
        def __init__(self, reader: bool = False) -> None:
            self.reader = reader
            self.closed = False

        def transaction(self) -> "_Transaction | Self":
            return _Transaction() if self.reader else self

        def cursor(self) -> "Self":
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    report, reader = _Connection(), _Connection(reader=True)
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_61(**_kwargs: object) -> object:
        return next(connections)

    monkeypatch.setattr(publisher, "_connect", _callback_61)

    def _callback_62(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_62)

    def _callback_63(*_args: object) -> object:
        return pytest.fail("success")

    monkeypatch.setattr(publisher, "_log_success", _callback_63)
    if inner_failure == "s3":

        def _callback_79(_service: object) -> object:
            raise RuntimeError("s3 construction failed")

        monkeypatch.setattr(
            publisher.boto3,
            "client",
            _callback_79,
        )

        def _callback_80(*_args: object) -> object:
            return pytest.fail("publish")

        monkeypatch.setattr(publisher, "_publish", _callback_80)
    else:

        def _callback_81(_service: object) -> object:
            return object()

        monkeypatch.setattr(publisher.boto3, "client", _callback_81)

        def publish_failure(*_args: object) -> None:
            error = RuntimeError("publication failed")
            publisher._record_failure("report_put", error)
            raise error

        monkeypatch.setattr(publisher, "_publish", publish_failure)
    with pytest.raises(RuntimeError, match="reader transaction exit failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 2
    assert caplog.text.count("phase=reader_finalize") == 1
    assert report.closed and reader.closed


def test_malformed_event_and_invalid_switch_record_once_before_io(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _callback_64(**_kwargs: object) -> object:
        return pytest.fail("io")

    monkeypatch.setattr(publisher, "_connect", _callback_64)
    with pytest.raises(ValueError, match="unsupported"):
        publisher.handler({"source": "unknown"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    caplog.clear()
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "sometimes")
    with pytest.raises(ValueError, match="true or false"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1


def test_disabled_valid_event_returns_without_record_or_io(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "false")

    def _callback_65(**_kwargs: object) -> object:
        return pytest.fail("io")

    monkeypatch.setattr(publisher, "_connect", _callback_65)
    assert publisher.handler({"trigger": "watchdog"}, None) == {
        "status": "disabled",
        "facility_scope": "both",
    }
    assert "V2_REPORT_PUBLICATION_FAILED" not in caplog.text


def test_emf_failure_records_once_without_generation_or_smoke_success(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Connection:
        def transaction(self) -> "Self":
            return self

        def cursor(self) -> "Self":
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            return None

        def close(self) -> None:
            return None

    connections = iter((_Connection(), _Connection()))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_66(**_kwargs: object) -> object:
        return next(connections)

    monkeypatch.setattr(publisher, "_connect", _callback_66)

    def _callback_67(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_67)

    def _callback_68(_service: object) -> object:
        return object()

    monkeypatch.setattr(publisher.boto3, "client", _callback_68)

    def _callback_69(*_args: object) -> object:
        return {
            "status": "published",
            "generation_id": "2026-01-12T05:00:00Z",
            "route_count": 246,
            "result_sha256": "a" * 64,
        }

    monkeypatch.setattr(
        publisher,
        "_publish",
        _callback_69,
    )

    def _callback_70(*_args: object) -> object:
        raise RuntimeError("emf failed")

    monkeypatch.setattr(
        "builtins.print",
        _callback_70,
    )
    with pytest.raises(RuntimeError, match="emf failed"):
        publisher.handler(
            {"trigger": "watchdog", "smoke_id": "123e4567-e89b-12d3-a456-426614174000"},
            None,
        )
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=success_emit") == 1
    assert "V2_REPORT_GENERATION_OK" not in caplog.text
    assert "V2_REPORT_SMOKE_OK" not in caplog.text


def test_smoke_emission_failure_records_once_and_propagates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Connection:
        def transaction(self) -> "Self":
            return self

        def cursor(self) -> "Self":
            return self

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            return None

        def close(self) -> None:
            return None

    connections = iter((_Connection(), _Connection()))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")

    def _callback_71(**_kwargs: object) -> object:
        return next(connections)

    monkeypatch.setattr(publisher, "_connect", _callback_71)

    def _callback_72(_connection: object) -> object:
        return _valid_rows()

    monkeypatch.setattr(publisher, "_read_report_rows", _callback_72)

    def _callback_73(_service: object) -> object:
        return object()

    monkeypatch.setattr(publisher.boto3, "client", _callback_73)

    def _callback_74(*_args: object) -> object:
        return {
            "status": "published",
            "generation_id": "2026-01-12T05:00:00Z",
            "route_count": 246,
            "result_sha256": "a" * 64,
        }

    monkeypatch.setattr(
        publisher,
        "_publish",
        _callback_74,
    )

    def _callback_75(*_args: object) -> object:
        return None

    monkeypatch.setattr(publisher, "_log_success", _callback_75)

    def _callback_76(*_args: object) -> object:
        raise RuntimeError("smoke failed")

    monkeypatch.setattr(
        publisher.logger,
        "info",
        _callback_76,
    )
    with pytest.raises(RuntimeError, match="smoke failed"):
        publisher.handler(
            {"trigger": "watchdog", "smoke_id": "123e4567-e89b-12d3-a456-426614174000"},
            None,
        )
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=smoke_emit") == 1


def _i66_path(
    path_id: str = "i66", *, legs: int = 1, direction: str = "eastbound"
) -> publisher._Path:
    source_direction = "EB" if direction == "eastbound" else "WB"
    return publisher._Path(
        path_id,
        1,
        "Broad origin",
        "Broad destination",
        direction,
        tuple(
            publisher._Leg(
                f"internal-{number}",
                None,
                f"{source_direction}:internal-{number}",
                10 + number,
                20 + number,
            )
            for number in range(legs)
        ),
        "i66",
    )


def _i66_source(
    start: datetime,
    end: datetime,
    *,
    key: str = "source",
    price: str = "1.00",
    calculated: datetime | None = None,
    zones: tuple[int, int | None] = (10, 20),
) -> dict[str, object]:
    return {
        "interval_start_at": start,
        "interval_end_at": end,
        "calculated_at": calculated or end,
        "s3_key": key,
        "start_zone_id": zones[0],
        "end_zone_id": zones[1],
        "zone_toll_rate_usd": price,
    }


def test_i66_schedule_matches_oracle_holidays_and_clipped_six_minute_hours() -> None:
    monday = datetime(2026, 1, 5, 5, tzinfo=EASTERN).astimezone(UTC)
    assert [
        len(
            publisher._i66_expected_slots(monday + timedelta(hours=offset), "eastbound")
        )
        for offset in range(5)
    ] == [5, 10, 10, 10, 5]
    westbound = datetime(2026, 1, 5, 15, tzinfo=EASTERN).astimezone(UTC)
    assert all(
        len(
            publisher._i66_expected_slots(
                westbound + timedelta(hours=offset), "westbound"
            )
        )
        == 10
        for offset in range(4)
    )
    assert (
        publisher._i66_expected_slots(
            datetime(2026, 1, 3, 15, tzinfo=EASTERN), "westbound"
        )
        == ()
    )
    # New Year, MLK, Washington, Memorial, Juneteenth, Independence, Labor,
    # Columbus, Veterans, Thanksgiving, and Christmas (including observed days).
    for holiday in (
        "2026-01-01",
        "2026-01-19",
        "2026-02-16",
        "2026-05-25",
        "2026-06-19",
        "2026-07-03",
        "2026-09-07",
        "2026-10-12",
        "2026-11-11",
        "2026-11-26",
        "2026-12-25",
    ):
        assert publisher._i66_schedule("eastbound", date.fromisoformat(holiday)) is None
    for observed_new_year in (date(2021, 12, 31), date(2027, 12, 31)):
        assert publisher._i66_schedule("eastbound", observed_new_year) is None
        assert publisher._i66_schedule("westbound", observed_new_year) is None
    assert publisher._i66_schedule("eastbound", date(2022, 1, 3)) is not None


@pytest.mark.parametrize("minutes", [5, 6])
def test_i66_source_revision_and_whole_route_alignment_fail_closed(
    minutes: int,
) -> None:
    start = datetime(2026, 1, 5, 10, 30, tzinfo=UTC)
    end = start + timedelta(minutes=minutes)
    bin_end = start + timedelta(minutes=6)
    path = _i66_path()
    selected = publisher._selected_i66_prices(
        [
            _i66_source(start, end, key="a"),
            _i66_source(start, end, key="b", price="2.00"),
        ],
        datetime(2026, 1, 5, tzinfo=EASTERN),
        datetime(2026, 1, 12, tzinfo=EASTERN),
        end,
        path.legs[0],
    )
    assert selected[bin_end].price == Decimal("2.00")
    assert (
        publisher._selected_i66_prices(
            [_i66_source(start, end, calculated=end + timedelta(seconds=1))],
            datetime(2026, 1, 5, tzinfo=EASTERN),
            datetime(2026, 1, 12, tzinfo=EASTERN),
            end,
            path.legs[0],
        )
        == {}
    )
    with pytest.raises(ValueError, match="conflict"):
        publisher._selected_i66_prices(
            [_i66_source(start, end), _i66_source(start, end, price="2.00")],
            datetime(2026, 1, 5, tzinfo=EASTERN),
            datetime(2026, 1, 12, tzinfo=EASTERN),
            end,
            path.legs[0],
        )
    with pytest.raises(ValueError, match="malformed"):
        publisher._selected_i66_prices(
            [_i66_source(start + timedelta(minutes=1), end + timedelta(minutes=1))],
            datetime(2026, 1, 5, tzinfo=EASTERN),
            datetime(2026, 1, 12, tzinfo=EASTERN),
            end,
            path.legs[0],
        )
    later = publisher._selected_i66_prices(
        [
            _i66_source(start - timedelta(minutes=minutes), start, price="1.00"),
            _i66_source(start, end, price="2.00"),
        ],
        datetime(2026, 1, 5, tzinfo=EASTERN),
        datetime(2026, 1, 12, tzinfo=EASTERN),
        end,
        path.legs[0],
    )
    assert later[start].price == Decimal("1.00")
    assert later[bin_end].price == Decimal("2.00")
    rows = publisher._hourly_i66_rows(
        (path,),
        {path.path_id: [selected]},
        datetime(2026, 1, 5, tzinfo=EASTERN),
        datetime(2026, 1, 12, tzinfo=EASTERN),
    )[path.group]
    assert rows[0]["expected_count"] == 5 and rows[0]["observed_count"] == 1
    partial = _i66_path("partial", legs=2)
    assert (
        publisher._hourly_i66_rows(
            (partial,),
            {partial.path_id: [selected, {}]},
            datetime(2026, 1, 5, tzinfo=EASTERN),
            datetime(2026, 1, 12, tzinfo=EASTERN),
        )[partial.group][0]["status"]
        == "missing"
    )


def test_i66_descriptor_direction_collision_and_two_facility_output_are_rejected_or_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _valid_rows()
    rows[1]["direction"] = "westbound"
    cast(
        dict[str, JSON],
        cast(dict[str, JSON], cast(list[JSON], rows[1]["pricing_legs"])[0])[
            "pricing_key"
        ],
    )["source_route_key"] = "WB:collision"
    cast(
        dict[str, JSON],
        cast(dict[str, JSON], cast(list[JSON], rows[1]["pricing_legs"])[0])[
            "pricing_key"
        ],
    )["start_zone_id"] = 1001
    cast(
        dict[str, JSON],
        cast(dict[str, JSON], cast(list[JSON], rows[1]["pricing_legs"])[0])[
            "pricing_key"
        ],
    )["end_zone_id"] = 2001
    rows[17]["direction"] = "westbound"
    cast(
        dict[str, JSON],
        cast(dict[str, JSON], cast(list[JSON], rows[17]["pricing_legs"])[0])[
            "pricing_key"
        ],
    )["source_route_key"] = "WB:route-18"
    with pytest.raises(ValueError, match="ambiguous"):
        publisher._validate_paths(rows)

    class CapturingS3(_S3):
        def __init__(self) -> None:
            super().__init__()
            self.bodies: dict[str, str] = {}

        def put_object(self, **kwargs: object) -> None:
            super().put_object(**kwargs)
            self.bodies[cast(str, kwargs["Key"])] = cast(bytes, kwargs["Body"]).decode()

    def source(
        _reader: object, leg: publisher._Leg, *_args: object
    ) -> list[dict[str, object]]:
        if leg.start_zone_id is None:
            return []
        hour = datetime(2026, 1, 5, 11, tzinfo=UTC)
        return [
            _i66_source(
                hour + timedelta(minutes=6 * slot),
                hour + timedelta(minutes=6 * (slot + 1)),
                zones=(leg.start_zone_id, leg.end_zone_id),
                price=str(slot + 1),
            )
            for slot in range(10)
        ]

    s3 = CapturingS3()
    monkeypatch.setattr(publisher, "_source_rows", source)
    publisher._publish(
        publisher._validate_paths(_valid_rows()),
        object(),
        s3,
        "bucket",
        datetime(2026, 1, 12, tzinfo=EASTERN),
    )
    assert len(s3.bodies) == 529
    sitemap = s3.bodies["sitemap.xml"]
    assert sitemap.count("<url><loc>") == 262
    assert "/tolls/i66/" in sitemap and "/tolls/i95-i495/" in sitemap
    assert "EB:" not in "".join(s3.bodies.values())
    for facility, count in (("i95-i495", 246), ("i66", 16)):
        manifest = json.loads(s3.bodies[f"tolls/{facility}/manifest.json"])
        assert manifest["schema_version"] == "3.0.0"
        assert manifest["route_count"] == count
    reports = [
        json.loads(body)
        for key, body in s3.bodies.items()
        if key.startswith("tolls/i66/") and key.endswith("report.json")
    ]
    assert len(reports) == 16
    for report in reports:
        hour = report["hours"][1]
        assert hour["status"] == "priced"
        assert hour["observed_count"] == hour["expected_count"]
        assert hour["observed_count"] > 0
        assert (hour["minimum"], hour["median"], hour["maximum"]) == (
            "1.00",
            "5.50",
            "10.00",
        )


@pytest.mark.parametrize("minutes, offset", [(4, 0), (7, 0), (5, 1), (6, 1)])
def test_i66_malformed_interval_is_pre_mutation_and_all_facility_scoped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    minutes: int,
    offset: int,
) -> None:
    paths = publisher._validate_paths(_valid_rows())
    invalid_start = datetime(2026, 1, 5, 10, 30, tzinfo=UTC) + timedelta(minutes=offset)
    s3 = _S3()

    def source(
        _reader: object, leg: publisher._Leg, *_args: object
    ) -> list[dict[str, object]]:
        if leg.start_zone_id is None:
            return []
        return [
            _i66_source(
                invalid_start,
                invalid_start + timedelta(minutes=minutes),
                zones=(leg.start_zone_id, leg.end_zone_id),
            )
        ]

    monkeypatch.setattr(publisher, "_source_rows", source)
    with pytest.raises(ValueError, match="malformed"):
        publisher._publish(
            paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    assert s3.calls == []
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 1
    assert "facility_scope=both" in caplog.text
    assert "V2ReportGenerationSuccess" not in caplog.text


@pytest.mark.parametrize(
    "hour, minute, observed_hour",
    [(10, 30, None), (10, 36, 0), (11, 0, 0), (14, 30, 4), (14, 36, None)],
)
def test_i66_publication_counts_only_overlapping_boundary_slots(
    monkeypatch: pytest.MonkeyPatch, hour: int, minute: int, observed_hour: int
) -> None:
    paths = publisher._validate_paths(_valid_rows())
    boundary_end = datetime(2026, 1, 5, hour, minute, tzinfo=UTC)

    class CapturingS3(_S3):
        def __init__(self) -> None:
            super().__init__()
            self.bodies: dict[str, str] = {}

        def put_object(self, **kwargs: object) -> None:
            super().put_object(**kwargs)
            self.bodies[cast(str, kwargs["Key"])] = cast(bytes, kwargs["Body"]).decode()

    def source(
        _reader: object, leg: publisher._Leg, *_args: object
    ) -> list[dict[str, object]]:
        if leg.start_zone_id is None:
            return []
        return [
            _i66_source(
                boundary_end - timedelta(minutes=6),
                boundary_end,
                zones=(leg.start_zone_id, leg.end_zone_id),
            )
        ]

    s3 = CapturingS3()
    monkeypatch.setattr(publisher, "_source_rows", source)
    publisher._publish(
        paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
    )
    i66_report = next(
        json.loads(body)
        for key, body in s3.bodies.items()
        if key.startswith("tolls/i66/") and key.endswith("report.json")
    )
    for index, row in enumerate(i66_report["hours"]):
        assert (row["observed_count"] > 0) == (index == observed_hour)


def test_i66_put_failure_after_i95_puts_skips_cleanup_and_success(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    paths = publisher._validate_paths(_valid_rows())
    first_i66 = next(path for path in paths if path.facility == "i66")
    s3 = _S3(fail_put=f"{publisher._route_key(first_i66)}/report.json")

    def _callback_77(*_args: object) -> object:
        return []

    monkeypatch.setattr(publisher, "_source_rows", _callback_77)
    with pytest.raises(RuntimeError, match="put failed"):
        publisher._publish(
            paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    assert any(cast(str, key).startswith("tolls/i95-i495/") for _, key in s3.calls)
    assert all(call[0] == "put" for call in s3.calls)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 1
    assert "facility_scope=both" in caplog.text
    assert "V2ReportGenerationSuccess" not in caplog.text


@pytest.mark.parametrize("failure", ["list", "delete"])
def test_i66_cleanup_failure_records_once_without_success(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    class I66CleanupS3(_S3):
        def _paginate(self, **kwargs: object) -> Iterator[dict[str, JSON]]:
            if kwargs["Prefix"] == "tolls/i66/":
                if failure == "list":
                    raise RuntimeError("I-66 list failed")
                return iter(
                    list[dict[str, JSON]]([{"Contents": [{"Key": "tolls/i66/stale"}]}])
                )
            return iter(())

        def delete_objects(self, **kwargs: JSON) -> NoReturn:
            self.calls.append(
                (
                    "delete",
                    [
                        str(item["Key"])
                        for item in cast(
                            list[dict[str, JSON]],
                            cast(dict[str, JSON], kwargs["Delete"])["Objects"],
                        )
                    ],
                )
            )
            raise RuntimeError("I-66 delete failed")

    paths = publisher._validate_paths(_valid_rows())
    s3 = I66CleanupS3()

    def _callback_78(*_args: object) -> object:
        return []

    monkeypatch.setattr(publisher, "_source_rows", _callback_78)
    with pytest.raises(RuntimeError, match="I-66"):
        publisher._publish(
            paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    first_list = next(
        index for index, call in enumerate(s3.calls) if call[0] == "paginator"
    )
    assert all(call[0] == "put" for call in s3.calls[:first_list])
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 1
    assert "facility_scope=both" in caplog.text
    assert "V2ReportGenerationSuccess" not in caplog.text
