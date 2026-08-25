import copy
import io
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import report_publisher_handler as publisher

EVALUATED_AT = datetime(2026, 8, 25, 16, 5, tzinfo=UTC)
WATERMARK = datetime(2026, 8, 25, 16, 0, tzinfo=UTC)


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
            "schema_version": 1,
            "facility": "i95_i495",
            "source_watermark": watermark.isoformat().replace("+00:00", "Z"),
            "source_key": "raw/feed=i95/date=2026-08-25/1600Z.csv",
            "row_count": 317,
        },
    }


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


def test_report_document_and_html_lead_with_the_direct_answer():
    generation = publisher.build_generation(_report_rows())
    route = generation.routes[0]
    published_at = EVALUATED_AT.replace(minute=7)
    document = publisher._build_report_document(generation, route, published_at)

    assert document["availability"] == "available"
    assert document["evaluated_at"] == "2026-08-25T16:05:00Z"
    assert document["current_price"] == route.current_price
    assert document["route"]["origin"]["nearby_landmarks"] == [
        "Ronald Reagan Washington National Airport"
    ]

    canonical_url = "https://tollchat.ai/tolls/i95-i495/origin/destination/"
    page = publisher._render_report_html(document, canonical_url)
    assert page.index("Current I-95/I-495 toll") < page.index("Route details")
    assert "$1.23" in page
    assert "As of" in page
    assert "Ronald Reagan Washington National Airport" in page
    assert (
        '<link rel="icon" type="image/png" sizes="64x64" href="/assets/favicon.png">'
    ) in page
    assert page.count(f'<link rel="canonical" href="{canonical_url}">') == 1
    assert '<link rel="alternate" type="application/json" href="report.json">' in page
    assert "noindex" not in page.lower()
    assert "<script" not in page

    hostile = copy.deepcopy(document)
    hostile["route"]["origin"]["place_name"] = "<script>alert(1)</script>"
    escaped_page = publisher._render_report_html(hostile, canonical_url)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in escaped_page
    assert "<script" not in escaped_page


def test_report_html_includes_complete_component_evidence():
    generation = publisher.build_generation(_report_rows())
    document = publisher._build_report_document(
        generation, generation.routes[0], EVALUATED_AT.replace(minute=7)
    )
    component = document["current_price"]["components"][0]
    component["recent_movement"] = {
        "method": "same_facility_leg_three_cycles",
        "direction": "rising",
        "samples": [
            {"cycle_offset": -2, "price_usd": "0.80"},
            {"cycle_offset": -1, "price_usd": "1.00"},
            {"cycle_offset": 0, "price_usd": "1.23"},
        ],
        "net_change_usd": "0.43",
        "net_change_percent": "53.8",
    }
    component["prior_week_comparison"] = {
        "method": "same_weekday_same_facility_bins",
        "comparable_period_count": 2,
        "expected_comparable_period_count": 3,
        "comparable_prices": [],
        "median_usd": "1.10",
        "minimum_usd": "0.90",
        "maximum_usd": "1.20",
        "current_delta_usd": "0.13",
        "current_delta_percent": "11.8",
        "position": "above_recent_range",
        "higher_than_count": 2,
    }

    page = publisher._render_report_html(
        document, "https://tollchat.ai/tolls/i95-i495/origin/destination/"
    )

    assert f"{component['bin_start']} to {component['bin_end']}" in page
    assert component["interval_end_at"] in page
    assert "Cycle -2: $0.80; Cycle -1: $1.00; Cycle 0: $1.23" in page
    assert "net change $0.43 (53.8%)" in page
    assert "range $0.90 to $1.20" in page
    assert "current delta $0.13 (11.8%)" in page
    assert "2 of 3 comparable periods" in page


def test_unavailable_report_has_no_current_total():
    rows = _report_rows()
    rows[0] = _report_row(0, available=False)
    generation = publisher.build_generation(rows)
    document = publisher._build_report_document(
        generation, generation.routes[0], EVALUATED_AT.replace(minute=7)
    )

    assert document["availability"] == "unavailable"
    assert "total_usd" not in document["current_price"]
    page = publisher._render_report_html(
        document, "https://tollchat.ai/tolls/i95-i495/origin/destination/"
    )
    assert "Current pricing is unavailable" in page
    assert "Current total" not in page
    assert "stale observation" in page.lower()


def test_result_fingerprint_ignores_run_times_but_not_public_content(monkeypatch):
    generation = publisher.build_generation(_report_rows())
    route = generation.routes[0]
    first = publisher._build_report_document(generation, route, EVALUATED_AT)
    later = copy.deepcopy(first)
    later["generation_id"] = "2026-08-25T16:15:00Z"
    later["published_at"] = "2026-08-25T16:16:00Z"
    later["evaluated_at"] = "2026-08-25T16:15:00Z"
    later["current_price"]["evaluated_at"] = "2026-08-25T16:15:00Z"
    later["current_price"]["components"][0]["component_evaluated_at"] = (
        "2026-08-25T16:15:00Z"
    )
    slugs = {
        route.origin.point_id: "origin",
        route.destination.point_id: "destination",
    }

    assert publisher._result_fingerprint([first], slugs) == (
        publisher._result_fingerprint([later], slugs)
    )

    changed = copy.deepcopy(later)
    changed["current_price"]["total_usd"] = "2.34"
    assert publisher._result_fingerprint([first], slugs) != (
        publisher._result_fingerprint([changed], slugs)
    )

    fingerprint = publisher._result_fingerprint([first], slugs)
    monkeypatch.setattr(publisher, "PUBLICATION_FORMAT_VERSION", "2")
    assert publisher._result_fingerprint([first], slugs) != fingerprint


class _MissingObject(Exception):
    def __init__(self):
        super().__init__("missing object")
        self.response = {"Error": {"Code": "NoSuchKey"}}


class _FakeS3:
    def __init__(self, *, fail_suffix=None):
        self.objects = {}
        self.puts = []
        self.lists = []
        self.fail_suffix = fail_suffix

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
        if self.fail_suffix and key.endswith(self.fail_suffix):
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
            "schema_version": "1.0.0",
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
        "schema_version": "1.0.0",
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
            "schema_version": "1.0.0",
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


def test_publication_uses_phase_barriers_manifest_last_and_then_noops():
    generation = publisher.build_generation(_report_rows())
    s3 = _FakeS3()

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
    assert marker == {
        "schema_version": 1,
        "facility": "i95_i495",
        "generation_id": "2026-08-25T16:05:00Z",
        "published_at": "2026-08-25T16:07:00Z",
        "result_sha256": result["result_sha256"],
    }

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

    with pytest.raises(RuntimeError, match="injected"):
        publisher._publish_generation(
            generation, s3, "site-bucket", EVALUATED_AT.replace(minute=7)
        )

    assert "tolls/i95-i495/manifest.json" not in s3.objects


def test_retry_repairs_an_interrupted_publication():
    original = publisher.build_generation(_report_rows())
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
    monkeypatch.setattr(publisher, "_read_report_rows", _report_rows)
    monkeypatch.setattr(
        publisher,
        "_publish_generation",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("publish failed")),
    )
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "site-bucket")
    monkeypatch.setenv("AGENT_MEASUREMENT_BUCKET", "analytics-bucket")
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())

    with caplog.at_level("INFO"), pytest.raises(RuntimeError, match="publish failed"):
        publisher.handler({"trigger": "watchdog"}, None)

    assert "V2_REPORT_GENERATION_OK" not in caplog.text


def test_success_is_logged_after_publication(monkeypatch, caplog):
    monkeypatch.setattr(publisher, "_read_report_rows", _report_rows)
    monkeypatch.setattr(
        publisher,
        "_publish_generation",
        lambda *_args: {"status": "published", "result_sha256": "a" * 64},
    )
    monkeypatch.setenv("REPORT_PUBLICATION_ENABLED", "true")
    monkeypatch.setenv("SITE_BUCKET_NAME", "site-bucket")
    monkeypatch.setenv("AGENT_MEASUREMENT_BUCKET", "analytics-bucket")
    monkeypatch.setattr(publisher.boto3, "client", lambda _service: object())

    with caplog.at_level("INFO"):
        result = publisher.handler({"trigger": "watchdog"}, None)

    assert result["status"] == "published"
    assert "V2_REPORT_GENERATION_OK i95_i495" in caplog.text
