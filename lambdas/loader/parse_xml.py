"""Parser for the I-66 zone-pair XML feed (<opt .../> attribute rows).

Uses the stdlib ElementTree — XXE-safe on 3.13 (no external entity/DTD
resolution); entity-expansion DoS is an accepted risk given HTTPS-only
delivery from VDOT, so defusedxml is skipped per spec.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

from parse_csv import TripPricingRow

# I-66 has no ODPAIRID/ODPAIRNAME or LINKSTATUS, but does carry
# IntervalDateTime (interval start), which the CSV feed lacks.
REQUIRED_ATTRS = (
    "IntervalDateTime",
    "IntervalEndDateTime",
    "CalculatedDateTime",
    "CorridorID",
    "CorridorName",
    "StartZoneID",
    "StartZoneName",
    "EndZoneID",
    "EndZoneName",
    "ZoneTollRate",
)


def _parse_iso_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_trip_pricing_xml(text: str) -> list[TripPricingRow]:
    root = ET.fromstring(text)
    opts = root.findall("opt")
    if not opts:
        raise ValueError("no <opt> rows parsed from XML")

    parsed_rows: list[TripPricingRow] = []
    for opt in opts:
        missing = [attr for attr in REQUIRED_ATTRS if attr not in opt.attrib]
        if missing:
            raise ValueError(
                f"missing XML attributes {missing} (source format drift): {opt.attrib}"
            )

        parsed_rows.append(
            TripPricingRow(
                feed="i66",
                interval_start_at=_parse_iso_utc(opt.attrib["IntervalDateTime"]),
                interval_end_at=_parse_iso_utc(opt.attrib["IntervalEndDateTime"]),
                current_at=None,
                calculated_at=_parse_iso_utc(opt.attrib["CalculatedDateTime"]),
                corridor_id=int(opt.attrib["CorridorID"]),
                corridor_name=opt.attrib["CorridorName"],
                od_pair_id=None,
                od_pair_name=None,
                start_zone_id=int(opt.attrib["StartZoneID"]),
                start_zone_name=opt.attrib["StartZoneName"] or None,
                end_zone_id=int(opt.attrib["EndZoneID"]),
                end_zone_name=opt.attrib["EndZoneName"],
                zone_toll_rate_usd=Decimal(opt.attrib["ZoneTollRate"]),
                link_status="NOT_APPLICABLE",
            )
        )

    return parsed_rows
