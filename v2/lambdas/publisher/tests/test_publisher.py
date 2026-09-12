import json
from datetime import UTC, datetime
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
    for row in i66:
        row["facility"] = "i66"
        row["direction"] = "eastbound"
        row["pricing_legs"][0]["facility"] = "i66"
        row["pricing_legs"][0]["pricing_key"] = {"charge_index": 1}
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
            delete_response or {},
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
        assert kwargs["Prefix"] == "tolls/i95-i495/"
        return iter(self.pages)

    def delete_objects(self, **kwargs):
        self.calls.append(
            ("delete", [item["Key"] for item in kwargs["Delete"]["Objects"]])
        )
        return self.delete_response


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
    assert len(paths) == 562
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
    assert publisher._validate_paths(rows)[0].order == 21
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
    manifest_at = s3.calls.index(("put", publisher.MANIFEST_KEY))
    assert all(call[0] == "put" for call in s3.calls[: manifest_at + 1])
    assert s3.calls[manifest_at + 1][0] == "paginator"
    assert s3.calls[-1] == ("delete", ["tolls/i95-i495/old", "tolls/i95-i495/old-two"])


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
        "facility": "i95_i495",
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
