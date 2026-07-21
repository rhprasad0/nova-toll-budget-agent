from decimal import Decimal

import pytest
from conftest import SAMPLE_DATA_DIR
from parse_xml import parse_trip_pricing_xml

SAMPLE_XML = (SAMPLE_DATA_DIR / "tollingTripPricing-I66.xml").read_text()


def test_parses_sample_file_completely():
    rows = parse_trip_pricing_xml(SAMPLE_XML)
    # NOTE: the checked-in sample file has 18 <opt> rows, not the ~44 the
    # work order/spec table describe as typical for a poll. Asserting the
    # real, observed count — see final report for this as a flagged finding.
    assert len(rows) == 18
    assert all(row.feed == "i66" for row in rows)


def test_no_od_pair_or_link_status_but_has_interval_start():
    rows = parse_trip_pricing_xml(SAMPLE_XML)
    assert all(row.od_pair_id is None for row in rows)
    assert all(row.od_pair_name is None for row in rows)
    assert all(row.link_status == "NOT_APPLICABLE" for row in rows)
    # IntervalDateTime (interval start) exists in XML but not CSV.
    assert all(row.interval_start_at is not None for row in rows)


def test_rate_and_zone_fields_parsed():
    rows = parse_trip_pricing_xml(SAMPLE_XML)
    row = rows[0]
    assert row.corridor_id == 1100
    assert row.corridor_name == "I-66 EB"
    assert row.zone_toll_rate_usd == Decimal("0.0000")
    assert row.interval_end_at.isoformat() == "2026-07-20T23:36:00+00:00"
    assert row.interval_start_at is not None
    assert row.interval_start_at.isoformat() == "2026-07-20T23:30:00+00:00"


def test_missing_required_attribute_fails_loudly():
    bad_xml = SAMPLE_XML.replace('CorridorID="1100"', "")
    with pytest.raises(ValueError, match="missing XML attributes"):
        parse_trip_pricing_xml(bad_xml)


def test_no_opt_rows_raises():
    with pytest.raises(ValueError, match="no <opt> rows"):
        parse_trip_pricing_xml("<data></data>")
