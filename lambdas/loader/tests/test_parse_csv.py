from decimal import Decimal

import pytest
from conftest import SAMPLE_DATA_DIR
from parse_csv import EXPECTED_SOURCE_HEADERS, parse_trip_pricing_csv

SAMPLE_CSV = (SAMPLE_DATA_DIR / "tollingTripPricing_I95.csv").read_text()


def test_parses_sample_file_completely():
    rows = parse_trip_pricing_csv(SAMPLE_CSV)
    assert len(rows) == 317
    assert all(row.feed == "i95" for row in rows)
    # CSV has no interval start; that's an I-66-only field.
    assert all(row.interval_start_at is None for row in rows)


def test_blank_startzonename_is_nullable():
    rows = parse_trip_pricing_csv(SAMPLE_CSV)
    row = next(
        r
        for r in rows
        if r.od_pair_name == "PRINCE WILLIAM TO FAIRFAX COUNTY PKWY (286)"
    )
    assert row.start_zone_name is None


def test_corridor_952_stored_as_is_under_i95_nb():
    # Five Opitz-bound OD pairs carry corridor_id 952 under corridor_name
    # I-95-NB (952 usually pairs with I-95-SB) — not "fixed" by the parser.
    rows = parse_trip_pricing_csv(SAMPLE_CSV)
    row = next(r for r in rows if r.od_pair_name == "CARDINAL to Opitz")
    assert row.corridor_name == "I-95-NB"
    assert row.corridor_id == 952


def test_closed_with_nonzero_rate_and_open_with_zero_rate_both_preserved():
    rows = parse_trip_pricing_csv(SAMPLE_CSV)
    closed_nonzero = [
        r for r in rows if r.link_status == "CLOSED" and r.zone_toll_rate_usd > 0
    ]
    open_zero = [
        r for r in rows if r.link_status != "CLOSED" and r.zone_toll_rate_usd == 0
    ]
    assert closed_nonzero
    assert open_zero


def test_header_drift_fails_loudly():
    bad_csv = SAMPLE_CSV.replace("CALULCATEDDATETIM", "CALCULATEDDATETIME")
    with pytest.raises(ValueError, match="unexpected CSV header"):
        parse_trip_pricing_csv(bad_csv)


def test_expected_headers_match_typo_and_truncation():
    assert "CALULCATEDDATETIM" in EXPECTED_SOURCE_HEADERS
    assert "INTERVALENDDATETI" in EXPECTED_SOURCE_HEADERS


def test_dst_fall_back_resolves_with_fold_zero():
    # 2026-11-01 is the US fall-back date: 01:30 local occurs twice.
    # fold=0 must pick the first (pre-transition, EDT/UTC-4) occurrence.
    header = ",".join(EXPECTED_SOURCE_HEADERS)
    row = (
        "1.00,SOME OD PAIR,1,,100,01/11/26 01:30:00,01/11/26 01:30:00,"
        "SOME END ZONE,200,I-95-NB,951,01/11/26 01:30:00,NO_DETERMINATION"
    )
    csv_text = f"{header}\n{row}\n"
    rows = parse_trip_pricing_csv(csv_text)
    assert len(rows) == 1
    assert rows[0].interval_end_at.isoformat() == "2026-11-01T05:30:00+00:00"


def test_dash_separator_and_blank_lines_are_skipped():
    header = ",".join(EXPECTED_SOURCE_HEADERS)
    dashes = ",".join("-" * len(h) for h in EXPECTED_SOURCE_HEADERS)
    row = "1.00,OD,1,,100,19/07/26 15:00:00,19/07/26 14:55:00,END,200,I-95-NB,951,19/07/26 14:50:00,CLOSED"
    csv_text = f"\n\n{header}\n{dashes}\n\n{row}\n\n"
    rows = parse_trip_pricing_csv(csv_text)
    assert len(rows) == 1
    assert rows[0].zone_toll_rate_usd == Decimal("1.00")
