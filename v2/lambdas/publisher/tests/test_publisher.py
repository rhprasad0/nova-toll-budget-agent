import copy
import hashlib
import importlib.util
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import report_publisher_handler as publisher

_loader_spec = importlib.util.spec_from_file_location(
    "loader_detail_test", Path(__file__).parents[2] / "loader" / "handler.py"
)
sys.path.insert(0, str(Path(__file__).parents[2] / "loader"))
assert _loader_spec and _loader_spec.loader
loader = importlib.util.module_from_spec(_loader_spec)
_loader_spec.loader.exec_module(loader)

EVALUATED_AT = datetime(2026, 8, 25, 16, 5, tzinfo=UTC)
WATERMARK = datetime(2026, 8, 25, 16, 0, tzinfo=UTC)
EASTERN = ZoneInfo("America/New_York")


def _endpoint(
    point_id,
    role,
    *,
    label=None,
    place_name="Newington",
    aliases=None,
    direction="southbound",
):
    return {
        "point_id": point_id,
        "label": label or point_id,
        "place_name": place_name,
        "region": "Virginia",
        "country_code": "US",
        "aliases": aliases or [point_id],
        "nearby_landmarks": ["Ronald Reagan Washington National Airport"],
        "direction": direction,
        "role": role,
        "display_name": f"Newington, Virginia - {point_id}",
        "location": {"type": "Point", "coordinates": [-77.1, 38.8]},
    }


def _report_row(index=0, *, available=True, evaluated_at=EVALUATED_AT):
    origin_id = f"i95:{index}SO"
    destination_id = f"i95:{index}SD"
    route_key = f"Southbound:{index}SO:{index}SD"
    observed_at = WATERMARK if available else WATERMARK.replace(hour=15)
    return {
        "snapshot_evaluated_at": evaluated_at,
        "origin": _endpoint(origin_id, "entry"),
        "destination": _endpoint(destination_id, "exit"),
        "structural_facility_legs": [
            {
                "route_step_id": "step-1",
                "facility": "i95_i495",
                "point_ids": [origin_id, destination_id],
                "connection_ids": [f"source:i95_shared:{route_key}"],
                "pricing_key": {"source_route_key": route_key, "od_pair_id": index + 1},
            }
        ],
        "status": "valid",
        "reason": None,
        "point_ids": [origin_id, destination_id],
        "connection_ids": [f"source:i95_shared:{route_key}"],
        "connection_types": ["within_facility"],
        "general_purpose_gaps": [],
        "i95_evidence": {
            "availability": "southbound",
            "northbound_corridor_name": "Northbound",
            "northbound_link_status": "CLOSED",
            "northbound_interval_end_at": WATERMARK.isoformat(),
            "northbound_calculated_at": observed_at.isoformat(),
            "southbound_corridor_name": "Southbound",
            "southbound_link_status": "OPEN",
            "southbound_interval_end_at": WATERMARK.isoformat(),
            "southbound_calculated_at": observed_at.isoformat(),
        },
        "facility_legs": [
            {
                "route_step_id": "step-1",
                "facility": "i95_i495",
                "point_ids": [origin_id, destination_id],
                "connection_ids": [f"source:i95_shared:{route_key}"],
                "pricing_key": {"source_route_key": route_key, "od_pair_id": index + 1},
            }
        ],
        "route_step_id": "step-1",
        "comparison_kind": "current",
        "comparison_offset": 0,
        "bin_start_at": observed_at,
        "bin_end_at": observed_at.replace(minute=10),
        "interval_end_at": observed_at,
        "observed_at": observed_at,
        "price_usd": Decimal("1.23"),
        "available": available,
        "availability_reason": None if available else "stale_observation",
        "source_kind": "observed",
        "pricing_method": "source_observation",
        "od_pair_id": index + 1,
        "proxy_od_pair_id": None,
        "source_status": "OPEN",
    }


def _report_rows(*, evaluated_at=EVALUATED_AT):
    return [_report_row(index, evaluated_at=evaluated_at) for index in range(685)]


def _load_event(watermark=WATERMARK):
    return {
        "source": "tollchat.pricing-loader",
        "detail-type": "I95 Pricing Load Committed",
        "detail": {
            "environment": "production",
            "schema_version": 1,
            "facility": "i95_i495",
            "source_watermark": watermark.isoformat().replace("+00:00", "Z"),
            "source_key": "raw/feed=i95/date=2026-08-25/1600Z.csv",
            "row_count": 317,
        },
    }


def _observation(
    interval_end_at,
    *,
    price="1.00",
    key="source.csv",
    calculated_at=None,
    series_id="od-1",
    direction="northbound",
):
    return {
        "series_id": series_id,
        "direction": direction,
        "interval_end_at": interval_end_at,
        "calculated_at": calculated_at or interval_end_at,
        "s3_key": key,
        "zone_toll_rate_usd": Decimal(price),
    }


def _weekly_run(year, month, day):
    return datetime(year, month, day, 1, tzinfo=EASTERN)


class _TransactionConnection:
    def transaction(self):
        return self

    def cursor(self, *_args, **_kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, *_args):
        return None

    def close(self):
        return None


class _StreamingCursor:
    def __init__(self, rows):
        self.rows = rows
        self.position = 0
        self.scrolled = False
        self.scroll_count = 0

    def fetchmany(self, size):
        batch = self.rows[self.position : self.position + size]
        self.position += len(batch)
        return batch

    def scroll(self, value, *, mode):
        assert (value, mode) == (0, "absolute")
        self.position = 0
        self.scrolled = True
        self.scroll_count += 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, *_args):
        return None


class _EmptyReaderCursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, *_args):
        return None

    def fetchmany(self, _size):
        return []


class _EmptyReaderConnection:
    def cursor(self, _name):
        return _EmptyReaderCursor()


def test_watchdog_builds_one_complete_generation(monkeypatch, caplog):
    monkeypatch.setattr(publisher, "_read_report_rows", _report_rows)

    with caplog.at_level("INFO"):
        result = publisher.handler({"trigger": "watchdog"}, None)

    assert result == {
        "status": "generated",
        "facility": "i95_i495",
        "generation_id": "2026-08-25T16:05:00Z",
        "source_watermark": "2026-08-25T16:00:00Z",
        "route_count": 685,
    }
    assert "V2_REPORT_GENERATION_OK i95_i495 2026-08-25T16:05:00Z 685" in caplog.text
    generation = publisher.build_generation(_report_rows())
    assert generation.routes[0].structural_facility_legs[0]["facility"] == "i95_i495"


def test_expected_watermark_matrix():
    assert publisher._expected_watermark_action(WATERMARK, WATERMARK) == "build"
    assert (
        publisher._expected_watermark_action(
            WATERMARK.replace(minute=50, hour=15), WATERMARK
        )
        == "superseded"
    )


def test_load_event_environment_must_match_runtime(monkeypatch):
    assert publisher._expected_watermark(_load_event()) == WATERMARK
    monkeypatch.setenv("TOLLCHAT_ENVIRONMENT", "development")
    with pytest.raises(ValueError, match="environment"):
        publisher._expected_watermark(_load_event())
    development = _load_event()
    development["detail"]["environment"] = "development"
    assert publisher._expected_watermark(development) == WATERMARK


def test_loader_detail_is_accepted_only_by_the_matching_publisher_environment(
    monkeypatch,
):
    detail = loader._i95_success_detail(
        watermark="2026-08-25T16:00:00Z",
        s3_key="raw/feed=i95/date=2026-08-25/1600Z.csv",
        row_count=1,
    )
    event = {
        "source": "tollchat.pricing-loader",
        "detail-type": "I95 Pricing Load Committed",
        "detail": detail,
    }
    assert publisher._expected_watermark(event) == WATERMARK
    monkeypatch.setenv("TOLLCHAT_ENVIRONMENT", "development")
    with pytest.raises(ValueError, match="environment"):
        publisher._expected_watermark(event)
    detail["environment"] = "development"
    assert publisher._expected_watermark(event) == WATERMARK
    with pytest.raises(RuntimeError, match="not visible"):
        publisher._expected_watermark_action(WATERMARK.replace(minute=10), WATERMARK)
    with pytest.raises(RuntimeError, match="not visible"):
        publisher._expected_watermark_action(WATERMARK, None)


def test_duplicate_load_events_are_side_effect_safe(monkeypatch):
    reads = iter(
        [
            _report_rows(),
            _report_rows(evaluated_at=EVALUATED_AT.replace(minute=6)),
        ]
    )
    monkeypatch.setattr(publisher, "_read_report_rows", lambda: next(reads))

    first = publisher.handler(_load_event(), None)
    second = publisher.handler(_load_event(), None)

    for result in (first, second):
        assert result["status"] == "generated"
        assert result["source_watermark"] == "2026-08-25T16:00:00Z"
        assert result["route_count"] == 685


def test_delayed_load_event_is_a_noop(monkeypatch):
    monkeypatch.setattr(publisher, "_read_report_rows", _report_rows)
    result = publisher.handler(_load_event(WATERMARK.replace(hour=15, minute=50)), None)
    assert result["status"] == "superseded"
    assert result["source_watermark"] == "2026-08-25T16:00:00Z"


def test_unknown_event_fails_before_database_access(monkeypatch):
    monkeypatch.setattr(
        publisher,
        "_read_report_rows",
        lambda: pytest.fail("database should not be read"),
    )
    with pytest.raises(ValueError, match="unsupported publisher event"):
        publisher.handler({"source": "not-the-loader"}, None)


def test_generation_rejects_inconsistent_snapshot_times():
    rows = _report_rows()
    rows[-1] = _report_row(684, evaluated_at=EVALUATED_AT.replace(minute=6))
    with pytest.raises(ValueError, match="evaluation timestamp"):
        publisher.build_generation(rows)


def test_stale_watchdog_result_stays_unavailable(monkeypatch):
    rows = _report_rows()
    rows[0] = _report_row(0, available=False)
    monkeypatch.setattr(publisher, "_read_report_rows", lambda: rows)

    result = publisher.handler({"trigger": "watchdog"}, None)

    assert result["status"] == "generated"
    generation = publisher.build_generation(rows)
    assert generation.routes[0].current_price["reason"] == "incomplete_route_price"
    assert (
        generation.routes[0].current_price["unavailable_components"][0]["reason"]
        == "stale_observation"
    )


def test_report_read_uses_one_bounded_repeatable_read(monkeypatch):
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql):
            calls.append(sql)

        def fetchall(self):
            return []

    class Connection:
        def transaction(self):
            return self

        def cursor(self):
            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            calls.append("close")

    monkeypatch.setattr(publisher, "_connect", lambda: Connection())
    assert publisher._read_report_rows() == []
    assert calls == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET LOCAL statement_timeout = '180s'",
        "SELECT * FROM oracle.get_i95_i495_report_inputs()",
        "close",
    ]


def test_descriptive_slugs_are_frozen_and_collision_safe():
    dumfries = publisher.Endpoint.model_validate(
        _endpoint(
            "i95:218NO",
            "entry",
            label="I-95 Near Dumfries Road/Route 234",
            place_name="Dumfries",
            aliases=["Dumfries Road", "Route 234"],
            direction="northbound",
        )
    )
    dumfries_south = publisher.Endpoint.model_validate(
        _endpoint(
            "i95:217SD",
            "exit",
            label="I-95 Near Dumfries Road/Route 234",
            place_name="Dumfries",
            aliases=["Dumfries Road", "Route 234"],
        )
    )
    tysons = publisher.Endpoint.model_validate(
        _endpoint(
            "i495:185ND",
            "exit",
            label="Westpark Drive",
            place_name="Tysons",
            aliases=["Westpark Drive", "Tysons Corner"],
            direction="northbound",
        )
    )
    newington = publisher.Endpoint.model_validate(
        _endpoint(
            "i95:208SO",
            "entry",
            label="Fairfax County Parkway/Route 286",
            aliases=["Fairfax County Parkway", "Route 286"],
        )
    )
    tp1nb = publisher.Endpoint.model_validate(
        _endpoint(
            "i495:192NO",
            "entry",
            label="Springfield Interchange",
            place_name="Lincolnia",
            aliases=["TP1NB", "Springfield Interchange"],
            direction="northbound",
        )
    )
    mclean = publisher.Endpoint.model_validate(
        _endpoint(
            "i495:180SO",
            "entry",
            label="George Washington Memorial Parkway",
            place_name="McLean",
            aliases=["George Washington Memorial Parkway", "GW Parkway"],
        )
    )
    tp1sb = publisher.Endpoint.model_validate(
        _endpoint(
            "i495:192SD",
            "exit",
            label="Springfield Interchange",
            place_name="Lincolnia",
            aliases=["TP1SB", "Springfield Interchange"],
        )
    )
    first = publisher.Endpoint.model_validate(
        _endpoint(
            "i95:1SO",
            "entry",
            label="Fairfax County Parkway/Route 286",
            place_name="Duplicate",
            aliases=["Fairfax County Parkway", "Route 286"],
        )
    )
    second = publisher.Endpoint.model_validate(
        _endpoint(
            "i95:2SO",
            "entry",
            label="Fairfax County Parkway/Route 286",
            place_name="Duplicate",
            aliases=["Fairfax County Parkway", "Route 286"],
        )
    )

    slugs = publisher._build_slug_map(
        [
            dumfries,
            dumfries_south,
            tysons,
            newington,
            tp1nb,
            mclean,
            tp1sb,
            first,
            second,
        ]
    )

    assert slugs["i95:218NO"] == ("dumfries-dumfries-road-route-234-northbound")
    assert slugs["i495:185ND"] == ("tysons-westpark-drive-tysons-corner-northbound")
    assert slugs["i95:208SO"] == (
        "newington-fairfax-county-parkway-route-286-southbound"
    )
    assert slugs["i495:192NO"] == ("lincolnia-tp1nb-springfield-interchange-northbound")
    assert slugs["i495:180SO"] == (
        "mclean-george-washington-memorial-parkway-gw-parkway-southbound"
    )
    assert slugs["i495:192SD"] == ("lincolnia-tp1sb-springfield-interchange-southbound")
    assert (
        f"{slugs['i95:218NO']}/{slugs['i495:185ND']}/"
        == "dumfries-dumfries-road-route-234-northbound/"
        "tysons-westpark-drive-tysons-corner-northbound/"
    )
    assert (
        f"{slugs['i95:208SO']}/{slugs['i95:217SD']}/"
        == "newington-fairfax-county-parkway-route-286-southbound/"
        "dumfries-dumfries-road-route-234-southbound/"
    )
    assert (
        f"{slugs['i495:192NO']}/{slugs['i495:185ND']}/"
        == "lincolnia-tp1nb-springfield-interchange-northbound/"
        "tysons-westpark-drive-tysons-corner-northbound/"
    )
    assert (
        f"{slugs['i495:180SO']}/{slugs['i495:192SD']}/"
        == "mclean-george-washington-memorial-parkway-gw-parkway-southbound/"
        "lincolnia-tp1sb-springfield-interchange-southbound/"
    )
    assert slugs["i95:1SO"] == ("duplicate-fairfax-county-parkway-route-286-southbound")
    assert slugs["i95:2SO"].endswith("-i95-2so")
    assert len(set(slugs.values())) == len(slugs)
    assert publisher._build_slug_map([dumfries, tysons], slugs) == slugs
    with pytest.raises(ValueError, match="incomplete"):
        publisher._build_slug_map(
            [dumfries, tysons], {dumfries.point_id: slugs[dumfries.point_id]}
        )


def test_schema_two_document_and_accessible_html_expose_only_evidence():
    route = publisher.build_generation(_report_rows()).routes[0]
    component = {
        "route_step_id": "step-1",
        "window": {
            "window_start_at": "2026-07-27T04:00:00Z",
            "window_end_at": "2026-08-24T04:00:00Z",
        },
        "provenance": {
            "target_od_pair_id": 1,
            "source_od_pair_id": 9,
            "proxy_od_pair_id": 9,
            "source_kind": "modeled",
            "pricing_method": "identity_proxy_v1",
            "direction": "southbound",
            "required_status": "OPEN",
        },
        "coverage": {
            "expected_rush_observations": 960,
            "observed_rush_observations": 1,
            "expected_off_rush_bins": 512,
            "observed_off_rush_bins": 1,
        },
        "rush_observations": [
            {
                "corridor_name": "<&",
                "od_pair_id": 9,
                "start_zone": {"id": 1, "name": "Start"},
                "end_zone": {"id": 2, "name": "End"},
                "interval_end_at": "2026-08-01T12:00:00Z",
                "observed_at": "2026-08-01T12:01:00Z",
                "price_usd": "1.23",
                "link_status": "OPEN",
            }
        ],
        "hourly_bins": [],
    }
    document = publisher._build_stream_document(
        EVALUATED_AT, WATERMARK, route, EVALUATED_AT.replace(minute=7), [component]
    )
    assert list(document) == [
        "schema",
        "generation",
        "facility",
        "coverage",
        "route",
        "components",
    ]
    assert document["schema"] == "2.0.0"
    encoded = json.dumps(document)
    assert all(
        value not in encoded
        for value in ("current_price", "availability", "s3_key", "ingested_at")
    )
    page = publisher._render_report_html(
        document, "https://tollchat.ai/tolls/i95-i495/origin/destination/"
    )
    assert "<caption>" in page and "<thead>" in page and 'scope="col"' in page
    assert "&lt;&amp;" in page and "Current total" not in page
    assert '<link rel="alternate" type="application/json" href="report.json">' in page


def test_result_fingerprint_ignores_generation_times(monkeypatch):
    document = {"generation": {"generation_id": "a", "published_at": "b"}, "route": {}}
    later = {"generation": {"generation_id": "c", "published_at": "d"}, "route": {}}
    fingerprint = publisher._result_fingerprint([document], {})
    assert fingerprint == publisher._result_fingerprint([later], {})
    monkeypatch.setattr(publisher, "PUBLICATION_FORMAT_VERSION", "2")
    assert publisher._result_fingerprint([document], {}) != fingerprint


class _MissingObject(Exception):
    def __init__(self):
        super().__init__("missing object")
        self.response = {"Error": {"Code": "NoSuchKey"}}


class _FakeS3:
    def __init__(self, *, fail_suffix=None, fail_bucket=None):
        self.objects = {}
        self.puts = []
        self.lists = []
        self.fail_suffix = fail_suffix
        self.fail_bucket = fail_bucket

    def list_objects_v2(self, **kwargs):
        self.lists.append(kwargs)
        prefix = kwargs["Prefix"]
        return {
            "Contents": [
                {"Key": key} for key in self.objects if key.startswith(prefix)
            ][: kwargs["MaxKeys"]]
        }

    def get_object(self, *, Bucket, Key):
        del Bucket
        try:
            body = self.objects[Key]
        except KeyError as error:
            raise _MissingObject from error
        return {"Body": io.BytesIO(body)}

    def put_object(self, **kwargs):
        key = kwargs["Key"]
        if (
            self.fail_suffix
            and key.endswith(self.fail_suffix)
            and (self.fail_bucket is None or kwargs["Bucket"] == self.fail_bucket)
        ):
            raise RuntimeError("injected upload failure")
        body = kwargs["Body"]
        if isinstance(body, str):
            body = body.encode()
        self.objects[key] = body
        self.puts.append(kwargs)


def test_malformed_frozen_slug_map_fails_closed():
    s3 = _FakeS3()
    s3.objects[publisher.MANIFEST_KEY] = json.dumps(
        {
            "schema_version": "2.0.0",
            "facility": "i95_i495",
            "result_sha256": "a" * 64,
            "point_slugs": {"i95:1SO": 1},
        }
    ).encode()

    with pytest.raises(ValueError, match="manifest is malformed"):
        publisher._read_manifest(s3, "site-bucket")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("generation_id", None),
        ("generation_id", "2026-08-25T16:05:00"),
        ("published_at", None),
        ("published_at", "not-a-timestamp"),
        ("source_watermark", 1),
        ("source_watermark", "2026-08-25T16:00:00"),
        ("route_count", 684),
        ("publication_format_version", 1),
    ],
)
def test_manifest_rejects_malformed_publication_metadata(field, value):
    manifest = {
        "schema_version": "2.0.0",
        "publication_format_version": "2.0.0",
        "facility": "i95_i495",
        "generation_id": "2026-08-25T16:05:00Z",
        "published_at": "2026-08-25T16:07:00Z",
        "source_watermark": "2026-08-25T16:00:00Z",
        "result_sha256": "a" * 64,
        "route_count": 685,
        "point_slugs": {"i95:1SO": "one"},
    }
    manifest[field] = value
    s3 = _FakeS3()
    s3.objects[publisher.MANIFEST_KEY] = json.dumps(manifest).encode()

    with pytest.raises(ValueError, match="manifest is malformed"):
        publisher._read_manifest(s3, "site-bucket")


def test_manifest_requires_an_explicit_source_watermark():
    s3 = _FakeS3()
    s3.objects[publisher.MANIFEST_KEY] = json.dumps(
        {
            "schema_version": "2.0.0",
            "facility": "i95_i495",
            "generation_id": "2026-08-25T16:05:00Z",
            "published_at": "2026-08-25T16:07:00Z",
            "result_sha256": "a" * 64,
            "route_count": 685,
            "point_slugs": {"i95:1SO": "one"},
        }
    ).encode()

    with pytest.raises(ValueError, match="manifest is malformed"):
        publisher._read_manifest(s3, "site-bucket")


def _stream_manifest(source_watermark):
    return {
        "schema_version": "2.0.0",
        "publication_format_version": publisher.PUBLICATION_FORMAT_VERSION,
        "facility": "i95_i495",
        "generation_id": "2026-08-25T16:05:00Z",
        "published_at": "2026-08-25T16:07:00Z",
        "source_watermark": source_watermark,
        "result_sha256": "a" * 64,
        "route_count": 2,
        "point_slugs": {
            "i95:0SO": "zero",
            "i95:0SD": "zero-d",
            "i95:1SO": "one",
            "i95:1SD": "one-d",
        },
    }


def _legacy_stream_manifest(source_watermark):
    return {
        **_stream_manifest(source_watermark),
        "schema_version": "1.0.0",
        "publication_format_version": "1.0.0",
    }


def test_streamed_publication_rewinds_one_cursor_and_writes_one_route_at_a_time(
    monkeypatch,
):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 2)
    cursor = _StreamingCursor([_report_row(0), _report_row(1)])
    s3 = _FakeS3()

    result, _, _ = publisher._publish_streamed(
        cursor,
        _EmptyReaderConnection(),
        s3,
        "site-bucket",
        EVALUATED_AT.replace(minute=7),
        "analytics-bucket",
    )

    assert result["status"] == "published"
    assert cursor.scrolled
    assert cursor.scroll_count == 2
    keys = [item["Key"] for item in s3.puts if item["Bucket"] == "site-bucket"]
    assert [key.rsplit("/", 1)[-1] for key in keys[:4]] == [
        "report.json",
        "index.html",
        "report.json",
        "index.html",
    ]
    assert keys[-1] == publisher.MANIFEST_KEY


def test_streamed_publication_migrates_a_complete_legacy_manifest(monkeypatch):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 2)
    s3 = _FakeS3()
    s3.objects[publisher.MANIFEST_KEY] = json.dumps(
        _legacy_stream_manifest("2026-08-25T15:00:00Z")
    ).encode()

    result, _, _ = publisher._publish_streamed(
        _StreamingCursor([_report_row(0), _report_row(1)]),
        _EmptyReaderConnection(),
        s3,
        "site-bucket",
        EVALUATED_AT.replace(minute=7),
        "analytics-bucket",
    )

    manifest = json.loads(s3.objects[publisher.MANIFEST_KEY])
    assert result["status"] == "published"
    assert manifest["schema_version"] == "2.0.0"
    assert manifest["publication_format_version"] == "2.0.0"
    assert {put["Key"] for put in s3.puts if put["Bucket"] == "site-bucket"} >= {
        "tolls/i95-i495/zero/zero-d/report.json",
        "tolls/i95-i495/one/one-d/report.json",
    }


@pytest.mark.parametrize(
    "manifest",
    [
        {**_legacy_stream_manifest("2026-08-25T15:00:00Z"), "published_at": None},
        {**_stream_manifest("2026-08-25T15:00:00Z"), "schema_version": "3.0.0"},
    ],
)
def test_streamed_publication_rejects_bad_legacy_or_unknown_manifest_before_writes(
    monkeypatch, manifest
):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 2)
    s3 = _FakeS3()
    s3.objects[publisher.MANIFEST_KEY] = json.dumps(manifest).encode()

    with pytest.raises(ValueError, match="publication manifest is malformed"):
        publisher._publish_streamed(
            _StreamingCursor([_report_row(0), _report_row(1)]),
            _EmptyReaderConnection(),
            s3,
            "site-bucket",
            EVALUATED_AT.replace(minute=7),
            "analytics-bucket",
        )
    assert not s3.puts


def test_streamed_publication_rejects_stale_manifest_before_route_writes(monkeypatch):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 2)
    cursor = _StreamingCursor([_report_row(0), _report_row(1)])
    s3 = _FakeS3()
    s3.objects[publisher.MANIFEST_KEY] = json.dumps(
        _stream_manifest("2026-08-25T16:10:00Z")
    ).encode()

    result, _, _ = publisher._publish_streamed(
        cursor,
        _EmptyReaderConnection(),
        s3,
        "site-bucket",
        EVALUATED_AT.replace(minute=7),
        "analytics-bucket",
    )

    assert result == {"status": "superseded"}
    assert not cursor.scrolled
    assert not s3.puts


def test_streamed_publication_rejects_a_later_rewound_snapshot_mismatch(monkeypatch):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 2)

    class DivergingCursor(_StreamingCursor):
        def scroll(self, value, *, mode):
            super().scroll(value, mode=mode)
            self.rows[1] = {
                **self.rows[1],
                "snapshot_evaluated_at": EVALUATED_AT.replace(minute=6),
            }

    rows = [_report_row(0), copy.deepcopy(_report_row(0)), _report_row(1)]
    s3 = _FakeS3()
    with pytest.raises(
        ValueError, match="report publish pass disagrees with preflight evaluation"
    ):
        publisher._publish_streamed(
            DivergingCursor(rows),
            _EmptyReaderConnection(),
            s3,
            "site-bucket",
            EVALUATED_AT.replace(minute=7),
            "analytics-bucket",
        )
    assert not s3.puts


def test_streamed_publication_uses_the_supplied_invocation_time(monkeypatch):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 2)
    seen = []
    weekly_run_at = publisher._weekly_run_at
    monkeypatch.setattr(
        publisher,
        "_weekly_run_at",
        lambda value: seen.append(value) or datetime(2026, 3, 2, 1, tzinfo=EASTERN),
    )
    published_at = datetime(2026, 3, 9, 5, 59, tzinfo=UTC)
    publisher._publish_streamed(
        _StreamingCursor([_report_row(0), _report_row(1)]),
        _EmptyReaderConnection(),
        _FakeS3(),
        "site-bucket",
        published_at,
        "analytics-bucket",
    )
    assert seen == [published_at]
    assert weekly_run_at(datetime(2026, 3, 9, 4, 59, tzinfo=UTC)) == datetime(
        2026, 3, 2, 1, tzinfo=EASTERN
    )
    assert weekly_run_at(datetime(2026, 3, 9, 5, tzinfo=UTC)) == datetime(
        2026, 3, 9, 1, tzinfo=EASTERN
    )
    assert weekly_run_at(datetime(2026, 11, 2, 6, tzinfo=UTC)) == datetime(
        2026, 11, 2, 1, tzinfo=EASTERN
    )


def test_weekly_component_binds_proxy_and_raw_history_queries():
    calls = []

    class Cursor:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, params):
            calls.append((self.name, sql, params))

        def fetchmany(self, _size):
            if self.name == "proxy_lookup":
                return [{"proxy_od_pair_id": 9, "required_status": "OPEN"}]
            return []

    component = publisher._weekly_component(
        SimpleNamespace(cursor=lambda name: Cursor(name)),
        SimpleNamespace(
            route_step_id="step-1",
            pricing_key=SimpleNamespace(
                od_pair_id=1, source_route_key="Northbound:a:b"
            ),
        ),
        datetime(2026, 1, 26, 1, tzinfo=EASTERN),
    )

    assert component["provenance"]["proxy_od_pair_id"] == 9
    assert component["provenance"]["source_kind"] == "modeled"
    assert component["rush_observations"] == []
    assert set(component["coverage"]) == {
        "expected_rush_observations",
        "observed_rush_observations",
        "expected_off_rush_bins",
        "observed_off_rush_bins",
    }
    _, raw_sql, raw_params = calls[1]
    assert "od_pair_id = %(source_od_pair_id)s" in raw_sql
    assert "link_status = %(required_status)s" in raw_sql
    assert raw_params["source_od_pair_id"] == 9
    assert raw_params["required_status"] == "OPEN"


@pytest.mark.parametrize(
    ("mappings", "error"),
    [
        ([], None),
        ([{"proxy_od_pair_id": 9, "required_status": "OPEN"}] * 2, "duplicate"),
        ([{"proxy_od_pair_id": "9", "required_status": "OPEN"}], "malformed"),
    ],
)
def test_weekly_component_handles_observed_and_rejects_bad_proxy_mappings(
    mappings, error
):
    class Cursor:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            return None

        def fetchmany(self, _size):
            return mappings if self.name == "proxy_lookup" else []

    connection = SimpleNamespace(cursor=lambda name: Cursor(name))
    leg = SimpleNamespace(
        route_step_id="step-1",
        pricing_key=SimpleNamespace(od_pair_id=1, source_route_key="Southbound:a:b"),
    )
    if error:
        with pytest.raises(ValueError, match=error):
            publisher._weekly_component(connection, leg, _weekly_run(2026, 1, 26))
    else:
        component = publisher._weekly_component(
            connection, leg, _weekly_run(2026, 1, 26)
        )
        assert component["provenance"]["source_kind"] == "observed"
        assert component["provenance"]["proxy_od_pair_id"] is None


def test_weekly_component_public_evidence_and_html_parity():
    rush_at = datetime(2026, 1, 5, 11, tzinfo=UTC)
    bin_at = datetime(2026, 1, 3, 12, tzinfo=UTC)

    def raw(price, key, calculated_at):
        return {
            "corridor_name": "I-95 <north>",
            "od_pair_id": 9,
            "start_zone_id": 10,
            "start_zone_name": "Start & one",
            "end_zone_id": 20,
            "end_zone_name": "End",
            "interval_end_at": bin_at,
            "calculated_at": calculated_at,
            "s3_key": key,
            "zone_toll_rate_usd": Decimal(price),
            "link_status": "OPEN",
        }

    raw_rows = [
        {**raw("1.23", "rush", rush_at), "interval_end_at": rush_at},
        raw("1.00", "a", bin_at),
        raw("1.00", "b", bin_at + timedelta(minutes=1)),
        raw("2.00", "c", bin_at + timedelta(minutes=2)),
        raw("2.00", "d", bin_at + timedelta(minutes=3)),
    ]

    class Cursor:
        def __init__(self, name):
            self.name, self.sent = name, False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            return None

        def fetchmany(self, _size):
            if self.sent:
                return []
            self.sent = True
            return (
                [{"proxy_od_pair_id": 9, "required_status": "OPEN"}]
                if self.name == "proxy_lookup"
                else raw_rows
            )

    leg = SimpleNamespace(
        route_step_id="step-1",
        pricing_key=SimpleNamespace(od_pair_id=1, source_route_key="Northbound:a:b"),
    )
    component = publisher._weekly_component(
        SimpleNamespace(cursor=lambda name: Cursor(name)), leg, _weekly_run(2026, 1, 26)
    )
    assert component["provenance"] == {
        "target_od_pair_id": 1,
        "source_od_pair_id": 9,
        "proxy_od_pair_id": 9,
        "source_kind": "modeled",
        "pricing_method": "identity_proxy_v1",
        "direction": "northbound",
        "required_status": "OPEN",
    }
    assert component["coverage"] == {
        "expected_rush_observations": 960,
        "observed_rush_observations": 1,
        "expected_off_rush_bins": 512,
        "observed_off_rush_bins": 1,
    }
    assert component["rush_observations"][0]["price_usd"] == "1.23"
    bin_document = component["hourly_bins"][0]
    assert bin_document["source_count"] == 4
    assert [
        bin_document[role]["price_usd"] for role in ("minimum", "maximum", "last")
    ] == ["1.00", "2.00", "2.00"]
    assert {
        role: bin_document[role]["observed_at"]
        for role in ("minimum", "maximum", "last")
    } == {
        "minimum": "2026-01-03T12:01:00Z",
        "maximum": "2026-01-03T12:03:00Z",
        "last": "2026-01-03T12:03:00Z",
    }
    assert all(
        private not in json.dumps(component) for private in ("s3_key", "ingested_at")
    )

    route = publisher.build_generation(_report_rows()).routes[0]
    document = publisher._build_stream_document(
        EVALUATED_AT, WATERMARK, route, EVALUATED_AT, [component]
    )
    page = publisher._render_report_html(
        document, "https://tollchat.ai/tolls/i95-i495/origin/destination/"
    )
    for role, observed_at in {
        "minimum": "2026-01-03T12:01:00Z",
        "maximum": "2026-01-03T12:03:00Z",
        "last": "2026-01-03T12:03:00Z",
    }.items():
        assert (
            f'<tr><th scope="row">{role}</th><td>I-95 &lt;north&gt;</td><td>9</td>'
            f"<td>10</td><td>Start &amp; one</td><td>20</td><td>End</td>"
            f"<td>2026-01-03T12:00:00Z</td><td>{observed_at}</td>" in page
        )
    for endpoint in (document["route"]["origin"], document["route"]["destination"]):
        for value in (
            endpoint["point_id"],
            endpoint["country_code"],
            endpoint["display_name"],
            "&quot;coordinates&quot;",
            "&quot;type&quot;",
        ):
            assert value in page
    for value in (
        "i95_i495",
        "2026-08-25T16:00:00Z",
        "I-95 &lt;north&gt;",
        "Start &amp; one",
        "minimum",
        "maximum",
        "last",
    ):
        assert value in page
    assert '<th scope="row">minimum</th>' in page


def test_incremental_digest_matches_independent_canonical_json():
    documents = [
        {"route": {"name": "é"}, "published_at": "2026-01-01T00:00:00Z"},
        {"route": {"name": "b"}, "generation_id": "2026-01-01T00:00:00Z"},
    ]
    slugs = {"b": "two", "a": "one"}
    stable_documents = [
        {
            key: value
            for key, value in document.items()
            if key not in {"published_at", "generation_id"}
        }
        for document in documents
    ]
    digest = hashlib.sha256(publisher._incremental_prefix(slugs))
    for index, _document in enumerate(documents):
        if index:
            digest.update(b",")
        digest.update(
            json.dumps(
                stable_documents[index],
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
    digest.update(b"]}")
    canonical = json.dumps(
        {
            "point_slugs": slugs,
            "publication_format_version": publisher.PUBLICATION_FORMAT_VERSION,
            "reports": stable_documents,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert digest.hexdigest() == hashlib.sha256(canonical.encode()).hexdigest()


def test_streamed_digest_matches_independent_canonical_bytes_and_is_stable(monkeypatch):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 2)

    def publish(rows, published_at):
        s3 = _FakeS3()
        result, _, _ = publisher._publish_streamed(
            _StreamingCursor(rows),
            _EmptyReaderConnection(),
            s3,
            "site-bucket",
            published_at,
            "analytics-bucket",
        )
        documents = [
            json.loads(s3.objects[put["Key"]])
            for put in s3.puts
            if put["Bucket"] == "site-bucket" and put["Key"].endswith("report.json")
        ]
        manifest = json.loads(s3.objects[publisher.MANIFEST_KEY])
        return result, documents, manifest

    def stable(value):
        if isinstance(value, dict):
            return {
                key: stable(item)
                for key, item in value.items()
                if key
                not in {
                    "component_evaluated_at",
                    "evaluated_at",
                    "generation_id",
                    "published_at",
                }
            }
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    rows = [_report_row(0), _report_row(1)]
    result, documents, manifest = publish(rows, EVALUATED_AT.replace(minute=7))
    canonical = json.dumps(
        {
            "point_slugs": manifest["point_slugs"],
            "publication_format_version": publisher.PUBLICATION_FORMAT_VERSION,
            "reports": stable(documents),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    assert result["result_sha256"] == hashlib.sha256(canonical).hexdigest()
    later, _, _ = publish(rows, EVALUATED_AT.replace(minute=8))
    assert later["result_sha256"] == result["result_sha256"]


@pytest.mark.parametrize(
    "failed_suffix",
    [
        "report.json",
        "index.html",
        "tolls/i95-i495/index.html",
        "sitemap.xml",
        publisher.MANIFEST_KEY,
    ],
)
def test_streamed_failure_leaves_manifest_uncommitted_and_retry_converges(
    monkeypatch, failed_suffix
):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 2)
    published_at = EVALUATED_AT.replace(minute=7)
    s3 = _FakeS3(fail_suffix=failed_suffix)
    old_manifest = json.dumps(_stream_manifest("2026-08-25T15:00:00Z")).encode()
    s3.objects[publisher.MANIFEST_KEY] = old_manifest
    with pytest.raises(RuntimeError, match="injected upload failure"):
        publisher._publish_streamed(
            _StreamingCursor([_report_row(0), _report_row(1)]),
            _EmptyReaderConnection(),
            s3,
            "site-bucket",
            published_at,
            "analytics-bucket",
        )
    assert s3.objects[publisher.MANIFEST_KEY] == old_manifest
    s3.fail_suffix = None
    result, _, _ = publisher._publish_streamed(
        _StreamingCursor([_report_row(0), _report_row(1)]),
        _EmptyReaderConnection(),
        s3,
        "site-bucket",
        published_at,
        "analytics-bucket",
    )
    assert result["status"] == "published"
    assert s3.puts[-2]["Key"] == publisher.MANIFEST_KEY
    assert s3.puts[-1]["Bucket"] == "analytics-bucket"


def test_streamed_marker_failure_repairs_the_committed_manifest(monkeypatch):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 2)
    published_at = EVALUATED_AT.replace(minute=7)
    s3 = _FakeS3(fail_suffix=".json", fail_bucket="analytics-bucket")
    s3.objects[publisher.MANIFEST_KEY] = json.dumps(
        _stream_manifest("2026-08-25T15:00:00Z")
    ).encode()
    with pytest.raises(RuntimeError, match="injected upload failure"):
        publisher._publish_streamed(
            _StreamingCursor([_report_row(0), _report_row(1)]),
            _EmptyReaderConnection(),
            s3,
            "site-bucket",
            published_at,
            "analytics-bucket",
        )
    committed = s3.objects[publisher.MANIFEST_KEY]
    site_objects = {
        key: value
        for key, value in s3.objects.items()
        if key.startswith("tolls/") or key == "sitemap.xml"
    }
    s3.fail_suffix = None
    put_count = len(s3.puts)
    result, _, _ = publisher._publish_streamed(
        _StreamingCursor([_report_row(0), _report_row(1)]),
        _EmptyReaderConnection(),
        s3,
        "site-bucket",
        published_at.replace(minute=8),
        "analytics-bucket",
    )
    assert result["status"] == "unchanged"
    assert s3.objects[publisher.MANIFEST_KEY] == committed
    assert {
        key: value
        for key, value in s3.objects.items()
        if key.startswith("tolls/") or key == "sitemap.xml"
    } == site_objects
    assert not [put for put in s3.puts[put_count:] if put["Bucket"] == "site-bucket"]
    assert s3.puts[-1]["Bucket"] == "analytics-bucket"
    marker = json.loads(s3.puts[-1]["Body"])
    manifest = json.loads(committed)
    assert marker["generation_id"] == manifest["generation_id"]
    assert marker["published_at"] == manifest["published_at"]
    assert marker["result_sha256"] == manifest["result_sha256"]


def test_reader_connection_failure_closes_the_oracle_connection(monkeypatch):
    class ReportConnection(_TransactionConnection):
        closed = False

        def close(self):
            self.closed = True

    report = ReportConnection()

    def connect(*, reader=False):
        if reader:
            raise RuntimeError("reader connect failed")
        return report

    monkeypatch.setattr(publisher, "_connect", connect)
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    with pytest.raises(RuntimeError, match="reader connect failed"):
        publisher.handler({"trigger": "watchdog"}, None)
    assert report.closed


def test_enabled_handler_captures_invocation_before_setup(monkeypatch):
    invoked_at = datetime(2026, 3, 9, 4, 59, 59, tzinfo=UTC)
    assert publisher._weekly_run_at(invoked_at) == datetime(
        2026, 3, 2, 1, tzinfo=EASTERN
    )
    calls = []

    class Clock:
        @classmethod
        def now(cls, tz):
            assert tz is UTC
            calls.append("clock")
            return invoked_at

    def connect(**_kwargs):
        assert calls[0] == "clock"
        calls.append("connect")
        return _TransactionConnection()

    seen = []
    monkeypatch.setattr(publisher, "datetime", Clock)
    monkeypatch.setattr(publisher, "_expected_watermark", lambda _event: None)
    monkeypatch.setattr(publisher, "_connect", connect)
    monkeypatch.setattr(
        publisher,
        "_publish_streamed",
        lambda *_args: (
            seen.append(_args[4])
            or (
                {"status": "published", "result_sha256": "a" * 64},
                EVALUATED_AT,
                WATERMARK,
            )
        ),
    )
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "site-bucket")
    monkeypatch.setenv("AGENT_MEASUREMENT_BUCKET", "analytics-bucket")
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())

    publisher.handler({"trigger": "watchdog"}, None)

    assert calls == ["clock", "connect", "connect"]
    assert seen == [invoked_at]


@pytest.mark.parametrize(
    ("event", "old_manifest", "logs_supersession"),
    [
        (_load_event(WATERMARK.replace(minute=50, hour=15)), None, True),
        (_load_event(), _stream_manifest("2026-08-25T16:10:00Z"), False),
        ({"trigger": "watchdog"}, _stream_manifest("2026-08-25T16:10:00Z"), False),
    ],
)
def test_enabled_supersession_logging_preserves_its_reason(
    monkeypatch, caplog, event, old_manifest, logs_supersession
):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 2)
    report_cursor = _StreamingCursor([_report_row(0), _report_row(1)])

    class Connection(_TransactionConnection):
        def __init__(self, cursor=None):
            self.report_cursor = cursor
            self.closed = False

        def cursor(self, *args, **kwargs):
            if args == ("report_snapshot",) and kwargs == {"scrollable": True}:
                return self.report_cursor
            return self

        def close(self):
            self.closed = True

    report = Connection(report_cursor)
    reader = Connection()
    s3 = _FakeS3()
    if old_manifest:
        s3.objects[publisher.MANIFEST_KEY] = json.dumps(old_manifest).encode()
    connections = iter((report, reader))
    monkeypatch.setattr(publisher, "_connect", lambda **_kwargs: next(connections))
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "site-bucket")
    monkeypatch.setenv("AGENT_MEASUREMENT_BUCKET", "analytics-bucket")
    monkeypatch.setenv("TOLLCHAT_ENVIRONMENT", "production")
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: s3)

    with caplog.at_level("INFO"):
        result = publisher.handler(event, None)

    assert result["status"] == "superseded"
    assert ("V2_REPORT_GENERATION_SUPERSEDED" in caplog.text) is logs_supersession
    assert "V2_REPORT_GENERATION_OK" not in caplog.text
    assert report.closed and reader.closed


def test_publication_uses_phase_barriers_manifest_last_and_then_noops(monkeypatch):
    monkeypatch.setattr(publisher, "EXPECTED_ROUTE_COUNT", 685)
    generation = publisher.build_generation(_report_rows())
    s3 = _FakeS3()
    result, _, _ = publisher._publish_streamed(
        _StreamingCursor(
            sorted(
                _report_rows(),
                key=lambda row: (
                    row["origin"]["point_id"],
                    row["destination"]["point_id"],
                ),
            )
        ),
        _EmptyReaderConnection(),
        s3,
        "site-bucket",
        EVALUATED_AT.replace(minute=7),
        "analytics-bucket",
    )
    assert result["status"] == "published"
    keys = [put["Key"] for put in s3.puts if put["Bucket"] == "site-bucket"]
    assert len(keys) == 1373
    assert sum(key.endswith("report.json") for key in keys) == 685
    assert sum(key.endswith("/index.html") for key in keys) == 686
    assert keys[-3:] == [
        "tolls/i95-i495/index.html",
        "sitemap.xml",
        publisher.MANIFEST_KEY,
    ]
    manifest = json.loads(s3.objects[publisher.MANIFEST_KEY])
    assert manifest["route_count"] == 685 and len(manifest["point_slugs"]) == 1370
    assert s3.objects["sitemap.xml"].count(b"<url>") == 685
    assert s3.objects["tolls/i95-i495/index.html"].count(b"<li>") == 685
    assert all(
        put["CacheControl"] == publisher.PUBLIC_CACHE_CONTROL
        for put in s3.puts
        if put["Bucket"] == "site-bucket" and put["Key"] != publisher.MANIFEST_KEY
    )
    assert s3.puts[-2]["Key"] == publisher.MANIFEST_KEY
    assert s3.puts[-2]["CacheControl"] == publisher.MANIFEST_CACHE_CONTROL
    return

    result = publisher._publish_generation(
        generation, s3, "site-bucket", EVALUATED_AT.replace(minute=7)
    )

    assert result["status"] == "published"
    assert s3.lists == [
        {
            "Bucket": "site-bucket",
            "Prefix": publisher.MANIFEST_KEY,
            "MaxKeys": 1,
        }
    ]
    keys = [put["Key"] for put in s3.puts]
    assert len(keys) == 1373
    assert all(key.endswith("report.json") for key in keys[:685])
    assert all(key.endswith("index.html") for key in keys[685:1370])
    assert keys[-3:] == [
        "tolls/i95-i495/index.html",
        "sitemap.xml",
        "tolls/i95-i495/manifest.json",
    ]
    manifest = json.loads(s3.objects[keys[-1]])
    assert (
        manifest["publication_format_version"] == publisher.PUBLICATION_FORMAT_VERSION
    )
    assert manifest["route_count"] == 685
    assert len(manifest["point_slugs"]) == 1370
    assert s3.objects["sitemap.xml"].count(b"<url>") == 685
    assert s3.objects["tolls/i95-i495/index.html"].count(b"<li>") == 685
    assert (
        b'<link rel="canonical" href="https://tollchat.ai/tolls/i95-i495/">'
        in s3.objects["tolls/i95-i495/index.html"]
    )
    report_key = next(key for key in keys if key.endswith("/index.html"))
    assert (
        f'<link rel="canonical" href="https://tollchat.ai/{report_key.removesuffix("index.html")}">'.encode()
        in s3.objects[report_key]
    )
    assert s3.puts[0]["CacheControl"] == "public, max-age=300"
    assert s3.puts[-1]["CacheControl"] == "no-cache"

    put_count = len(s3.puts)
    no_op = publisher._publish_generation(
        generation, s3, "site-bucket", EVALUATED_AT.replace(minute=8)
    )
    assert no_op["status"] == "unchanged"
    assert len(s3.puts) == put_count

    manifest["source_watermark"] = "2026-08-25T16:10:00Z"
    s3.objects[publisher.MANIFEST_KEY] = json.dumps(manifest).encode()
    superseded = publisher._publish_generation(
        generation, s3, "site-bucket", EVALUATED_AT.replace(minute=9)
    )
    assert superseded["status"] == "superseded"
    assert len(s3.puts) == put_count


def test_completed_publication_writes_and_repairs_private_generation_marker():
    generation = publisher.build_generation(_report_rows())
    published_at = EVALUATED_AT.replace(minute=7)
    s3 = _FakeS3()
    with pytest.raises(RuntimeError, match="legacy"):
        publisher._publish_generation(generation, s3, "site-bucket", published_at)
    return

    result = publisher._publish_generation(
        generation,
        s3,
        "site-bucket",
        published_at,
        analytics_bucket="analytics-bucket",
    )

    assert result["status"] == "published"
    marker_put = next(put for put in s3.puts if put["Bucket"] == "analytics-bucket")
    assert marker_put["Key"].startswith("generations/date=2026-08-25/")
    marker = json.loads(marker_put["Body"])
    route_keys = marker.pop("route_keys")
    assert marker == {
        "schema_version": 1,
        "facility": "i95_i495",
        "generation_id": "2026-08-25T16:05:00Z",
        "published_at": "2026-08-25T16:07:00Z",
        "result_sha256": result["result_sha256"],
    }
    published_route_keys = {
        key.removesuffix("/report.json")
        for key in s3.objects
        if key.startswith("tolls/i95-i495/") and key.endswith("/report.json")
    }
    assert len(route_keys) == 685
    assert set(route_keys) == published_route_keys

    marker_key = marker_put["Key"]
    del s3.objects[marker_key]
    repair = publisher._publish_generation(
        generation,
        s3,
        "site-bucket",
        published_at.replace(minute=8),
        analytics_bucket="analytics-bucket",
    )
    assert repair["status"] == "unchanged"
    assert marker_key in s3.objects


@pytest.mark.parametrize(
    "failed_suffix",
    [
        "report.json",
        "index.html",
        "tolls/i95-i495/index.html",
        "sitemap.xml",
        "tolls/i95-i495/manifest.json",
    ],
)
def test_failed_publication_does_not_advance_manifest(failed_suffix):
    generation = publisher.build_generation(_report_rows())
    s3 = _FakeS3(fail_suffix=failed_suffix)
    with pytest.raises(RuntimeError, match="legacy"):
        publisher._publish_generation(generation, s3, "site-bucket", EVALUATED_AT)
    return

    with pytest.raises(RuntimeError, match="injected"):
        publisher._publish_generation(
            generation, s3, "site-bucket", EVALUATED_AT.replace(minute=7)
        )

    assert "tolls/i95-i495/manifest.json" not in s3.objects


def test_retry_repairs_an_interrupted_publication():
    original = publisher.build_generation(_report_rows())
    with pytest.raises(RuntimeError, match="legacy"):
        publisher._publish_generation(original, _FakeS3(), "site-bucket", EVALUATED_AT)
    return
    changed = original.model_copy(deep=True)
    changed.routes[0].current_price["components"][0]["price_usd"] = "2.34"
    changed.routes[0].current_price["total_usd"] = "2.34"
    first_published_at = EVALUATED_AT.replace(minute=7)
    changed_published_at = EVALUATED_AT.replace(minute=8)
    s3 = _FakeS3()
    publisher._publish_generation(original, s3, "site-bucket", first_published_at)

    expected = _FakeS3()
    expected.objects = copy.deepcopy(s3.objects)
    publisher._publish_generation(
        changed, expected, "site-bucket", changed_published_at
    )

    s3.fail_suffix = "index.html"
    with pytest.raises(RuntimeError, match="injected"):
        publisher._publish_generation(changed, s3, "site-bucket", changed_published_at)
    s3.fail_suffix = None

    result = publisher._publish_generation(
        changed, s3, "site-bucket", changed_published_at
    )

    assert result["status"] == "published"
    assert len(s3.objects) == 1373
    assert s3.objects == expected.objects


def test_disabled_handler_never_opens_s3(monkeypatch):
    monkeypatch.setattr(publisher, "_read_report_rows", _report_rows)
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "false")
    monkeypatch.setattr(
        publisher.boto3,
        "client",
        lambda service: pytest.fail(f"unexpected {service} client"),
    )

    result = publisher.handler({"trigger": "watchdog"}, None)

    assert result["status"] == "generated"


def test_publication_failure_never_logs_success(monkeypatch, caplog):
    monkeypatch.setattr(
        publisher, "_connect", lambda **_kwargs: _TransactionConnection()
    )
    monkeypatch.setattr(
        publisher,
        "_publish_streamed",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("publish failed")),
    )
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "site-bucket")
    monkeypatch.setenv("AGENT_MEASUREMENT_BUCKET", "analytics-bucket")
    monkeypatch.setenv("DB_READER_USER", "pricing_reader")
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())

    with caplog.at_level("INFO"), pytest.raises(RuntimeError, match="publish failed"):
        publisher.handler({"trigger": "watchdog"}, None)

    assert "V2_REPORT_GENERATION_OK" not in caplog.text


def test_success_is_logged_after_publication(monkeypatch, caplog):
    monkeypatch.setattr(
        publisher, "_connect", lambda **_kwargs: _TransactionConnection()
    )
    monkeypatch.setattr(
        publisher,
        "_publish_streamed",
        lambda *_args: (
            {"status": "published", "result_sha256": "a" * 64},
            EVALUATED_AT,
            WATERMARK,
        ),
    )
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "site-bucket")
    monkeypatch.setenv("AGENT_MEASUREMENT_BUCKET", "analytics-bucket")
    monkeypatch.setenv("DB_READER_USER", "pricing_reader")
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())

    with caplog.at_level("INFO"):
        result = publisher.handler({"trigger": "watchdog"}, None)

    assert result["status"] == "published"
    assert "V2_REPORT_GENERATION_OK i95_i495" in caplog.text


def test_weekly_selector_keeps_only_weekday_rush_boundaries_at_source_cadence():
    run_at = _weekly_run(2026, 1, 26)
    cases = (
        ("06:00", datetime(2026, 1, 5, 11, tzinfo=UTC), 1, 0),
        ("10:00", datetime(2026, 1, 5, 15, tzinfo=UTC), 0, 1),
        ("15:00", datetime(2026, 1, 5, 20, tzinfo=UTC), 1, 0),
        ("19:00", datetime(2026, 1, 6, 0, tzinfo=UTC), 0, 1),
        ("tuesday-09:00", datetime(2026, 1, 6, 14, tzinfo=UTC), 1, 0),
        ("saturday-09:00", datetime(2026, 1, 10, 14, tzinfo=UTC), 0, 1),
    )

    for key, interval_end_at, observed_rush, observed_off_rush in cases:
        row = _observation(interval_end_at, key=key)
        result = publisher._select_weekly_observations(
            [row], run_at, series_id="od-1", direction="northbound"
        )

        assert result.rows == (row,)
        assert result.rows[0] is row
        assert result.coverage == publisher._ObservationCoverage(
            960, observed_rush, 512, observed_off_rush
        )


def test_weekly_selector_uses_utc_bins_ties_and_original_rows_without_gaps():
    run_at = _weekly_run(2026, 1, 26)
    hour = datetime(2026, 1, 10, 6, tzinfo=UTC)
    rows = [
        _observation(hour, price="5", key="maximum"),
        _observation(hour + timedelta(minutes=10), price="1", key="old-minimum"),
        _observation(
            hour + timedelta(minutes=10),
            price="1",
            key="latest-minimum",
            calculated_at=hour + timedelta(minutes=11),
        ),
        _observation(
            hour + timedelta(minutes=10),
            price="1",
            key="s3-tiebreak-minimum",
            calculated_at=hour + timedelta(minutes=11),
        ),
        _observation(hour + timedelta(minutes=50), price="3", key="last"),
        _observation(hour + timedelta(hours=2), price="2", key="after-empty-hour"),
    ]

    result = publisher._select_weekly_observations(
        rows, run_at, series_id="od-1", direction="northbound"
    )

    assert [row["s3_key"] for row in result.rows] == [
        "maximum",
        "s3-tiebreak-minimum",
        "last",
        "after-empty-hour",
    ]
    assert result.rows[1] is rows[3]
    assert result.coverage.observed_off_rush_bins == 2
    assert len(result.rows) == 4


def test_weekly_selector_uses_local_calendar_window_for_dst_coverage_and_utc_bins():
    assert (
        publisher._select_weekly_observations(
            [], _weekly_run(2026, 1, 26), series_id="od-1", direction="northbound"
        ).coverage.expected_off_rush_bins
        == 512
    )
    assert (
        publisher._select_weekly_observations(
            [], _weekly_run(2026, 3, 30), series_id="od-1", direction="northbound"
        ).coverage.expected_off_rush_bins
        == 511
    )

    repeated_hour_rows = [
        _observation(datetime(2026, 11, 1, 5, 30, tzinfo=UTC), key="fold-0"),
        _observation(datetime(2026, 11, 1, 6, 30, tzinfo=UTC), key="fold-1"),
    ]
    result = publisher._select_weekly_observations(
        repeated_hour_rows,
        _weekly_run(2026, 11, 2),
        series_id="od-1",
        direction="northbound",
    )

    assert {row["s3_key"] for row in result.rows} == {"fold-0", "fold-1"}
    assert result.coverage == publisher._ObservationCoverage(960, 0, 513, 2)


def test_weekly_selector_partitions_series_and_rejects_invalid_input():
    run_at = _weekly_run(2026, 1, 26)
    northbound = [
        _observation(datetime(2026, 1, 5, 11, tzinfo=UTC), key="north-rush"),
        _observation(datetime(2026, 1, 10, 6, tzinfo=UTC), key="north-off-rush"),
    ]
    southbound = [
        _observation(
            datetime(2026, 1, 6, 14, tzinfo=UTC),
            key="south-rush",
            series_id="od-2",
            direction="southbound",
        ),
        _observation(
            datetime(2026, 1, 10, 7, tzinfo=UTC),
            key="south-off-rush",
            series_id="od-2",
            direction="southbound",
        ),
    ]

    northbound_result = publisher._select_weekly_observations(
        northbound, run_at, series_id="od-1", direction="northbound"
    )
    southbound_result = publisher._select_weekly_observations(
        southbound, run_at, series_id="od-2", direction="southbound"
    )
    assert {row["s3_key"] for row in northbound_result.rows} == {
        "north-rush",
        "north-off-rush",
    }
    assert northbound_result.coverage == publisher._ObservationCoverage(960, 1, 512, 1)
    assert {row["s3_key"] for row in southbound_result.rows} == {
        "south-rush",
        "south-off-rush",
    }
    assert southbound_result.coverage == publisher._ObservationCoverage(960, 1, 512, 1)
    with pytest.raises(ValueError, match="declared directed series"):
        publisher._select_weekly_observations(
            [*northbound, *southbound],
            run_at,
            series_id="od-1",
            direction="northbound",
        )
    with pytest.raises(ValueError, match="Monday 01:00"):
        publisher._select_weekly_observations(
            [],
            datetime(2026, 1, 26, 2, tzinfo=EASTERN),
            series_id="od-1",
            direction="northbound",
        )
    with pytest.raises(ValueError, match="aware"):
        publisher._select_weekly_observations(
            [],
            datetime(2026, 1, 26, 1, tzinfo=UTC).replace(tzinfo=None),
            series_id="od-1",
            direction="northbound",
        )
    with pytest.raises(ValueError, match="outside"):
        publisher._select_weekly_observations(
            [_observation(datetime(2025, 12, 29, 4, 59, tzinfo=UTC))],
            run_at,
            series_id="od-1",
            direction="northbound",
        )
    with pytest.raises(ValueError, match="outside"):
        publisher._select_weekly_observations(
            [_observation(datetime(2026, 1, 26, 5, tzinfo=UTC))],
            run_at,
            series_id="od-1",
            direction="northbound",
        )
    with pytest.raises(ValueError, match="aware"):
        publisher._select_weekly_observations(
            [_observation(datetime(2026, 1, 10, 6, tzinfo=UTC).replace(tzinfo=None))],
            run_at,
            series_id="od-1",
            direction="northbound",
        )
    with pytest.raises(ValueError, match="aware"):
        publisher._select_weekly_observations(
            [
                _observation(
                    datetime(2026, 1, 10, 6, tzinfo=UTC),
                    calculated_at=datetime(2026, 1, 10, 6, tzinfo=UTC).replace(
                        tzinfo=None
                    ),
                )
            ],
            run_at,
            series_id="od-1",
            direction="northbound",
        )
