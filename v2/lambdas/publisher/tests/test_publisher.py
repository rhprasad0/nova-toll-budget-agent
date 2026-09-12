import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import report_publisher_handler as publisher

EASTERN = publisher._EASTERN


def _row(order, group=None, *, path_id=None, area=None, leg_count=1):
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


def _valid_rows():
    i66 = [_row(order) for order in range(1, 21)]
    for order, row in enumerate(i66, start=1):
        row["facility"] = "i66"
        row["direction"] = "eastbound"
        row["pricing_legs"][0]["facility"] = "i66"
        row["pricing_legs"][0]["pricing_key"] = {
            "source_route_key": f"EB:route-{order}",
            "start_zone_id": 1000 + order,
            "end_zone_id": 2000 + order,
        }
        row["origin_area"] = f"I66 Origin {(order - 1) % 16}"
        row["destination_area"] = f"I66 Destination {(order - 1) % 16}"
    return i66 + [_row(order, (order - 21) % 246) for order in range(21, 583)]


def _paths(*paths):
    return tuple(paths)


def _path(path_id, *, legs=1, group="A"):
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
    def __init__(self, pages=(), fail_put=None, delete_response=None):
        self.pages, self.fail_put, self.delete_response = (
            list(pages),
            fail_put,
            delete_response,
        )
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(("put", kwargs["Key"]))
        if kwargs["Key"] == self.fail_put:
            raise RuntimeError("put failed")

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        self.calls.append(("paginator", name))
        return SimpleNamespace(paginate=self._paginate)

    def _paginate(self, **kwargs):
        return iter(self.pages if kwargs["Prefix"] == "tolls/i95-i495/" else [])

    def delete_objects(self, **kwargs):
        self.calls.append(
            ("delete", [item["Key"] for item in kwargs["Delete"]["Objects"]])
        )
        return self.delete_response or {"Deleted": kwargs["Delete"]["Objects"]}


@pytest.mark.parametrize(
    ("invoked_at", "hours"),
    [
        (datetime(2026, 1, 12, 0, tzinfo=EASTERN), 168),
        (datetime(2026, 3, 9, 0, tzinfo=EASTERN), 167),
        (datetime(2026, 11, 2, 0, tzinfo=EASTERN), 169),
    ],
)
def test_prior_completed_week_uses_elapsed_utc_hours(invoked_at, hours):
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


def test_descriptor_contract_validates_all_counts_and_collisions_before_s3():
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
    rows[20]["pricing_legs"][0]["unexpected"] = "no"
    with pytest.raises(ValueError, match="leg"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    rows[20]["pricing_legs"][0]["pricing_key"]["source_route_key"] = (
        "Southbound:wrong-series"
    )
    with pytest.raises(ValueError, match="leg"):
        publisher._validate_paths(rows)


def test_descriptor_filters_global_i66_orders_and_rejects_other_facilities():
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
        row["path_order"] += 1
    with pytest.raises(ValueError, match="global order"):
        publisher._validate_paths(rows)
    rows = _valid_rows()
    rows[19], rows[20] = rows[20], rows[19]
    with pytest.raises(ValueError, match="global"):
        publisher._validate_paths(rows)


def test_revision_dedupe_cutoff_and_complete_multi_leg_totals():
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
    monkeypatch, caplog
):
    paths = publisher._validate_paths(_valid_rows())
    start = datetime(2026, 1, 5, tzinfo=EASTERN)
    interval = start.astimezone(UTC).replace(minute=1)
    s3 = _S3()
    monkeypatch.setattr(
        publisher,
        "_source_rows",
        lambda *_args: [
            {
                "interval_end_at": interval,
                "calculated_at": interval,
                "s3_key": "source",
                "zone_toll_rate_usd": "1.00",
            }
        ],
    )
    with pytest.raises(ValueError, match="ten-minute cadence"):
        publisher._publish(
            paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    assert s3.calls == []
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1


def test_multi_path_partial_coverage_and_even_median_are_honest():
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


def test_public_document_and_html_contain_only_broad_data_and_escape_text():
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


def test_publish_is_manifest_last_then_paginates_and_deletes_only_stale(monkeypatch):
    paths = publisher._validate_paths(_valid_rows())
    s3 = _S3(
        pages=[
            {"Contents": [{"Key": "tolls/i95-i495/old"}]},
            {"Contents": [{"Key": "tolls/i95-i495/old-two"}]},
        ]
    )
    monkeypatch.setattr(publisher, "_source_rows", lambda *_args: [])
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
def test_precommit_put_failures_never_list_or_delete(monkeypatch, failed_key, caplog):
    paths = publisher._validate_paths(_valid_rows())
    key = (
        f"{publisher._route_key(paths[0])}/report.json"
        if failed_key == "report"
        else failed_key
    )
    s3 = _S3(fail_put=key)
    monkeypatch.setattr(publisher, "_source_rows", lambda *_args: [])
    with pytest.raises(RuntimeError, match="put failed"):
        publisher._publish(
            paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    assert all(call[0] == "put" for call in s3.calls)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 1


def test_aggregation_failure_is_pre_mutation_and_recorded_once(monkeypatch, caplog):
    paths = publisher._validate_paths(_valid_rows())
    monkeypatch.setattr(
        publisher,
        "_source_rows",
        lambda *_args: (_ for _ in ()).throw(ValueError("bad source")),
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
def test_list_and_delete_failures_propagate_once(monkeypatch, failure, caplog):
    paths = publisher._validate_paths(_valid_rows())
    s3 = _S3(
        pages=[{"Contents": [{"Key": "tolls/i95-i495/old"}]}],
        delete_response=failure if isinstance(failure, dict) else {},
    )
    if str(failure) == "list failed":
        s3._paginate = lambda **_kwargs: (_ for _ in ()).throw(failure)
    if str(failure) == "delete failed":
        s3.delete_objects = lambda **_kwargs: (_ for _ in ()).throw(failure)
    monkeypatch.setattr(publisher, "_source_rows", lambda *_args: [])
    with pytest.raises(RuntimeError):
        publisher._publish(
            paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    assert ("put", publisher.MANIFEST_KEY) in s3.calls
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 1


def test_cleanup_batches_no_more_than_one_thousand_keys():
    keys = [{"Key": f"tolls/i95-i495/old-{number}"} for number in range(1001)]
    s3 = _S3(pages=[{"Contents": keys}])
    publisher._cleanup_stale(s3, "bucket", set())
    deleted = [call[1] for call in s3.calls if call[0] == "delete"]
    assert [len(batch) for batch in deleted] == [1000, 1]


def test_cleanup_rejects_partial_success_response_once(caplog):
    s3 = _S3(
        pages=[{"Contents": [{"Key": "tolls/i95-i495/old"}]}],
        delete_response={"Deleted": []},
    )
    with pytest.raises(ValueError, match="partial"):
        publisher._cleanup_stale(s3, "bucket", set())
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=delete") == 1


def test_handler_rejects_invalid_publication_switch_before_connections(monkeypatch):
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "sometimes")
    monkeypatch.setattr(
        publisher, "_connect", lambda **_kwargs: pytest.fail("connected")
    )
    with pytest.raises(ValueError, match="true or false"):
        publisher.handler({"trigger": "watchdog"}, None)


def test_loader_event_keeps_its_strict_source_key_boundary():
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


def test_smoke_log_uses_the_exact_correlated_digest_shape(monkeypatch, caplog):
    class _Connection:
        def cursor(self):
            return self

        def transaction(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            return None

        def close(self):
            return None

    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: _Connection())
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())
    monkeypatch.setattr(publisher, "_read_report_rows", lambda _connection: [])
    monkeypatch.setattr(publisher, "_validate_paths", lambda _rows: ())
    digest = "a" * 64
    monkeypatch.setattr(
        publisher,
        "_publish",
        lambda *_args: {
            "status": "published",
            "generation_id": "2026-01-12T05:00:00Z",
            "route_count": 246,
            "result_sha256": digest,
        },
    )
    monkeypatch.setattr(publisher, "_log_success", lambda *_args: None)
    smoke_id = "123e4567-e89b-12d3-a456-426614174000"
    result = publisher.handler({"trigger": "watchdog", "smoke_id": smoke_id}, None)
    assert result["result_sha256"] == digest
    assert (
        f"V2_REPORT_SMOKE_OK {smoke_id} published 2026-01-12T05:00:00Z {digest}"
        in caplog.text
    )


def test_reader_transaction_setup_precedes_source_reads_and_connections_close(
    monkeypatch,
):
    calls = []

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql):
            calls.append(sql)

    class _Connection:
        def __init__(self):
            self.closed = False

        def transaction(self):
            return self

        def cursor(self):
            return _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            self.closed = True

    report, reader = _Connection(), _Connection()
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(
        publisher,
        "_publish",
        lambda *_args: (
            calls.append("source")
            or (_ for _ in ()).throw(RuntimeError("source failed"))
        ),
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
    monkeypatch, caplog, failure
):
    calls = []

    class _Transaction:
        def __enter__(self):
            if failure == "transaction":
                raise RuntimeError("transaction entry failed")
            return self

        def __exit__(self, *_args):
            return None

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql):
            calls.append(sql)
            if failure == "timeout" and "statement_timeout" in sql:
                raise RuntimeError("timeout setup failed")

    class _Connection:
        def __init__(self):
            self.closed = False

        def transaction(self):
            return _Transaction()

        def cursor(self):
            return _Cursor()

        def close(self):
            self.closed = True

    report, reader = _Connection(), _Connection()
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(
        publisher, "_publish", lambda *_args: pytest.fail("source read")
    )
    monkeypatch.setattr(
        publisher.boto3, "client", lambda _service: pytest.fail("s3 client")
    )
    monkeypatch.setattr(
        publisher, "_log_success", lambda *_args: pytest.fail("success")
    )
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
    monkeypatch, caplog
):
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setattr(
        publisher,
        "_connect",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("report connect failed")),
    )
    monkeypatch.setattr(publisher, "_publish", lambda *_args: pytest.fail("source"))
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: pytest.fail("s3"))
    monkeypatch.setattr(
        publisher, "_log_success", lambda *_args: pytest.fail("success")
    )
    with pytest.raises(RuntimeError, match="report connect failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1


def test_reader_connection_acquisition_records_once_and_closes_report(
    monkeypatch, caplog
):
    class _Report:
        closed = False

        def close(self):
            self.closed = True

    report = _Report()
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(
        publisher,
        "_connect",
        lambda **kwargs: (
            (_ for _ in ()).throw(RuntimeError("reader connect failed"))
            if kwargs
            else report
        ),
    )
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(publisher, "_publish", lambda *_args: pytest.fail("source"))
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: pytest.fail("s3"))
    monkeypatch.setattr(
        publisher, "_log_success", lambda *_args: pytest.fail("success")
    )
    with pytest.raises(RuntimeError, match="reader connect failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    assert report.closed


def test_s3_client_construction_records_once_and_closes_connections(
    monkeypatch, caplog
):
    class _Connection:
        def __init__(self):
            self.closed = False

        def transaction(self):
            return self

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            return None

        def close(self):
            self.closed = True

    report, reader = _Connection(), _Connection()
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(
        publisher.boto3,
        "client",
        lambda _service: (_ for _ in ()).throw(RuntimeError("s3 construction failed")),
    )
    monkeypatch.setattr(publisher, "_publish", lambda *_args: pytest.fail("source"))
    monkeypatch.setattr(
        publisher, "_log_success", lambda *_args: pytest.fail("success")
    )
    with pytest.raises(RuntimeError, match="s3 construction failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    assert report.closed and reader.closed


@pytest.mark.parametrize("bucket", [None, "   "])
def test_missing_or_blank_bucket_records_once_before_reader_or_s3(
    monkeypatch, caplog, bucket
):
    class _Report:
        closed = False

        def close(self):
            self.closed = True

    report = _Report()
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    if bucket is None:
        monkeypatch.delenv("SITE_BUCKET_NAME", raising=False)
    else:
        monkeypatch.setenv("SITE_BUCKET_NAME", bucket)
    monkeypatch.setattr(
        publisher,
        "_connect",
        lambda **kwargs: pytest.fail("reader") if kwargs else report,
    )
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: pytest.fail("s3"))
    monkeypatch.setattr(publisher, "_publish", lambda *_args: pytest.fail("source"))
    monkeypatch.setattr(
        publisher, "_log_success", lambda *_args: pytest.fail("success")
    )
    with pytest.raises((KeyError, ValueError)):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    assert report.closed


@pytest.mark.parametrize("failed_close", ["reader", "report"])
def test_close_failure_after_publication_records_once_and_suppresses_success(
    monkeypatch, caplog, failed_close
):
    class _Connection:
        def __init__(self, name):
            self.name = name
            self.closed = False

        def transaction(self):
            return self

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            return None

        def close(self):
            self.closed = True
            if self.name == failed_close:
                raise RuntimeError(f"{self.name} close failed")

    report, reader = _Connection("report"), _Connection("reader")
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())
    monkeypatch.setattr(
        publisher,
        "_publish",
        lambda *_args: {
            "status": "published",
            "generation_id": "2026-01-12T05:00:00Z",
            "route_count": 246,
            "result_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        publisher, "_log_success", lambda *_args: pytest.fail("success")
    )
    with pytest.raises(RuntimeError, match=f"{failed_close} close failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    assert report.closed and reader.closed


def test_close_failure_keeps_underlying_publication_failure_evidence(
    monkeypatch, caplog
):
    class _Connection:
        def __init__(self, reader=False):
            self.reader = reader
            self.closed = False

        def transaction(self):
            return self

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            return None

        def close(self):
            self.closed = True
            if self.reader:
                raise RuntimeError("reader close failed")

    report, reader = _Connection(), _Connection(reader=True)
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())

    def publish_failure(*_args):
        error = RuntimeError("publication failed")
        publisher._record_failure("report_put", error)
        raise error

    monkeypatch.setattr(publisher, "_publish", publish_failure)
    monkeypatch.setattr(
        publisher, "_log_success", lambda *_args: pytest.fail("success")
    )
    with pytest.raises(RuntimeError, match="reader close failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 2
    assert "phase=report_put" in caplog.text
    assert caplog.text.count("phase=pre_mutation") == 1
    assert report.closed and reader.closed


def test_reader_transaction_exit_after_success_records_once_and_suppresses_success(
    monkeypatch, caplog
):
    class _Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            raise RuntimeError("transaction exit failed")

    class _Connection:
        def __init__(self, reader=False):
            self.reader = reader
            self.closed = False

        def transaction(self):
            return _Transaction() if self.reader else self

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            return None

        def close(self):
            self.closed = True

    report, reader = _Connection(), _Connection(reader=True)
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())
    monkeypatch.setattr(
        publisher,
        "_publish",
        lambda *_args: {
            "status": "published",
            "generation_id": "2026-01-12T05:00:00Z",
            "route_count": 246,
            "result_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        publisher, "_log_success", lambda *_args: pytest.fail("success")
    )
    with pytest.raises(RuntimeError, match="transaction exit failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=reader_finalize") == 1
    assert report.closed and reader.closed


def test_publish_failure_does_not_get_a_second_reader_boundary_record(
    monkeypatch, caplog
):
    class _Connection:
        def __init__(self):
            self.closed = False

        def transaction(self):
            return self

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            return None

        def close(self):
            self.closed = True

    report, reader = _Connection(), _Connection()
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())

    def publish_failure(*_args):
        error = RuntimeError("publication failed")
        publisher._record_failure("report_put", error)
        raise error

    monkeypatch.setattr(publisher, "_publish", publish_failure)
    monkeypatch.setattr(
        publisher, "_log_success", lambda *_args: pytest.fail("success")
    )
    with pytest.raises(RuntimeError, match="publication failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 1
    assert "phase=report_put" in caplog.text
    assert "phase=pre_mutation" not in caplog.text
    assert report.closed and reader.closed


@pytest.mark.parametrize("inner_failure", ["publish", "s3"])
def test_reader_exit_records_a_distinct_unwinding_failure_once(
    monkeypatch, caplog, inner_failure
):
    class _Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            raise RuntimeError("reader transaction exit failed")

    class _Connection:
        def __init__(self, reader=False):
            self.reader = reader
            self.closed = False

        def transaction(self):
            return _Transaction() if self.reader else self

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            return None

        def close(self):
            self.closed = True

    report, reader = _Connection(), _Connection(reader=True)
    connections = iter((report, reader))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(
        publisher, "_log_success", lambda *_args: pytest.fail("success")
    )
    if inner_failure == "s3":
        monkeypatch.setattr(
            publisher.boto3,
            "client",
            lambda _service: (_ for _ in ()).throw(
                RuntimeError("s3 construction failed")
            ),
        )
        monkeypatch.setattr(
            publisher, "_publish", lambda *_args: pytest.fail("publish")
        )
    else:
        monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())

        def publish_failure(*_args):
            error = RuntimeError("publication failed")
            publisher._record_failure("report_put", error)
            raise error

        monkeypatch.setattr(publisher, "_publish", publish_failure)
    with pytest.raises(RuntimeError, match="reader transaction exit failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 2
    assert caplog.text.count("phase=reader_finalize") == 1
    assert report.closed and reader.closed


def test_malformed_event_and_invalid_switch_record_once_before_io(monkeypatch, caplog):
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: pytest.fail("io"))
    with pytest.raises(ValueError, match="unsupported"):
        publisher.handler({"source": "unknown"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1
    caplog.clear()
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "sometimes")
    with pytest.raises(ValueError, match="true or false"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=pre_mutation") == 1


def test_disabled_valid_event_returns_without_record_or_io(monkeypatch, caplog):
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "false")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: pytest.fail("io"))
    assert publisher.handler({"trigger": "watchdog"}, None) == {
        "status": "disabled",
        "facility_scope": "both",
    }
    assert "V2_REPORT_PUBLICATION_FAILED" not in caplog.text


def test_emf_failure_records_once_without_generation_or_smoke_success(
    monkeypatch, caplog
):
    class _Connection:
        def transaction(self):
            return self

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            return None

        def close(self):
            return None

    connections = iter((_Connection(), _Connection()))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())
    monkeypatch.setattr(
        publisher,
        "_publish",
        lambda *_args: {
            "status": "published",
            "generation_id": "2026-01-12T05:00:00Z",
            "route_count": 246,
            "result_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        "builtins.print",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("emf failed")),
    )
    with pytest.raises(RuntimeError, match="emf failed"):
        publisher.handler(
            {"trigger": "watchdog", "smoke_id": "123e4567-e89b-12d3-a456-426614174000"},
            None,
        )
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=success_emit") == 1
    assert "V2_REPORT_GENERATION_OK" not in caplog.text
    assert "V2_REPORT_SMOKE_OK" not in caplog.text


def test_smoke_emission_failure_records_once_and_propagates(monkeypatch, caplog):
    class _Connection:
        def transaction(self):
            return self

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            return None

        def close(self):
            return None

    connections = iter((_Connection(), _Connection()))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "bucket")
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setattr(
        publisher, "_read_report_rows", lambda _connection: _valid_rows()
    )
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())
    monkeypatch.setattr(
        publisher,
        "_publish",
        lambda *_args: {
            "status": "published",
            "generation_id": "2026-01-12T05:00:00Z",
            "route_count": 246,
            "result_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(publisher, "_log_success", lambda *_args: None)
    monkeypatch.setattr(
        publisher.logger,
        "info",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("smoke failed")),
    )
    with pytest.raises(RuntimeError, match="smoke failed"):
        publisher.handler(
            {"trigger": "watchdog", "smoke_id": "123e4567-e89b-12d3-a456-426614174000"},
            None,
        )
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED phase=smoke_emit") == 1


def _i66_path(path_id="i66", *, legs=1, direction="eastbound"):
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
    start, end, *, key="source", price="1.00", calculated=None, zones=(10, 20)
):
    return {
        "interval_start_at": start,
        "interval_end_at": end,
        "calculated_at": calculated or end,
        "s3_key": key,
        "start_zone_id": zones[0],
        "end_zone_id": zones[1],
        "zone_toll_rate_usd": price,
    }


def test_i66_schedule_matches_oracle_holidays_and_clipped_six_minute_hours():
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


def test_i66_source_revision_and_whole_route_alignment_fail_closed():
    start = datetime(2026, 1, 5, 10, 30, tzinfo=UTC)
    end = start + timedelta(minutes=6)
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
    assert selected[end].price == Decimal("2.00")
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
    monkeypatch,
):
    rows = _valid_rows()
    rows[1]["direction"] = "westbound"
    rows[1]["pricing_legs"][0]["pricing_key"]["source_route_key"] = "WB:collision"
    rows[1]["pricing_legs"][0]["pricing_key"]["start_zone_id"] = 1001
    rows[1]["pricing_legs"][0]["pricing_key"]["end_zone_id"] = 2001
    rows[17]["direction"] = "westbound"
    rows[17]["pricing_legs"][0]["pricing_key"]["source_route_key"] = "WB:route-18"
    with pytest.raises(ValueError, match="ambiguous"):
        publisher._validate_paths(rows)

    class CapturingS3(_S3):
        def __init__(self):
            super().__init__()
            self.bodies = {}

        def put_object(self, **kwargs):
            super().put_object(**kwargs)
            self.bodies[kwargs["Key"]] = kwargs["Body"].decode()

    s3 = CapturingS3()
    monkeypatch.setattr(publisher, "_source_rows", lambda *_args: [])
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


def test_i66_malformed_duration_is_pre_mutation_and_all_facility_scoped(
    monkeypatch, caplog
):
    paths = publisher._validate_paths(_valid_rows())
    invalid_start = datetime(2026, 1, 5, 10, 30, tzinfo=UTC)
    s3 = _S3()

    def source(_reader, leg, *_args):
        if leg.start_zone_id is None:
            return []
        return [
            _i66_source(
                invalid_start,
                invalid_start + timedelta(minutes=5),
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


def test_i66_boundary_slot_is_omitted_by_publication_envelope(monkeypatch):
    paths = publisher._validate_paths(_valid_rows())
    boundary_end = datetime(2026, 1, 5, 10, 30, tzinfo=UTC)

    class CapturingS3(_S3):
        def __init__(self):
            super().__init__()
            self.bodies = {}

        def put_object(self, **kwargs):
            super().put_object(**kwargs)
            self.bodies[kwargs["Key"]] = kwargs["Body"].decode()

    def source(_reader, leg, *_args):
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
    assert i66_report["hours"][0]["observed_count"] == 0


def test_i66_put_failure_after_i95_puts_skips_cleanup_and_success(monkeypatch, caplog):
    paths = publisher._validate_paths(_valid_rows())
    first_i66 = next(path for path in paths if path.facility == "i66")
    s3 = _S3(fail_put=f"{publisher._route_key(first_i66)}/report.json")
    monkeypatch.setattr(publisher, "_source_rows", lambda *_args: [])
    with pytest.raises(RuntimeError, match="put failed"):
        publisher._publish(
            paths, object(), s3, "bucket", datetime(2026, 1, 12, tzinfo=EASTERN)
        )
    assert any(key.startswith("tolls/i95-i495/") for _, key in s3.calls)
    assert all(call[0] == "put" for call in s3.calls)
    assert caplog.text.count("V2_REPORT_PUBLICATION_FAILED") == 1
    assert "facility_scope=both" in caplog.text
    assert "V2ReportGenerationSuccess" not in caplog.text


@pytest.mark.parametrize("failure", ["list", "delete"])
def test_i66_cleanup_failure_records_once_without_success(monkeypatch, caplog, failure):
    class I66CleanupS3(_S3):
        def _paginate(self, **kwargs):
            if kwargs["Prefix"] == "tolls/i66/":
                if failure == "list":
                    raise RuntimeError("I-66 list failed")
                return iter([{"Contents": [{"Key": "tolls/i66/stale"}]}])
            return iter(())

        def delete_objects(self, **kwargs):
            self.calls.append(
                ("delete", [item["Key"] for item in kwargs["Delete"]["Objects"]])
            )
            raise RuntimeError("I-66 delete failed")

    paths = publisher._validate_paths(_valid_rows())
    s3 = I66CleanupS3()
    monkeypatch.setattr(publisher, "_source_rows", lambda *_args: [])
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
