"""Parser for the I-66 zone-pair XML feed (<opt .../> attribute rows).

Uses the stdlib ElementTree -- XXE-safe on 3.13 (no external entity/DTD
resolution); entity-expansion DoS is an accepted risk given HTTPS-only
delivery from VDOT, so defusedxml is skipped per spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

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


@dataclass(frozen=True)
class I66Row:
    interval_start_at: datetime
    interval_end_at: datetime
    calculated_at: datetime
    corridor_id: int
    corridor_name: str
    start_zone_id: int
    start_zone_name: str | None
    end_zone_id: int
    end_zone_name: str
    zone_toll_rate_usd: Decimal


def _parse_iso_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_trip_pricing_xml(text: str) -> list[I66Row]:
    root = ET.fromstring(text)
    opts = root.findall("opt")
    if not opts:
        raise ValueError("no <opt> rows parsed from XML")

    parsed_rows: list[I66Row] = []
    for opt in opts:
        missing = [attr for attr in REQUIRED_ATTRS if attr not in opt.attrib]
        if missing:
            raise ValueError(
                f"missing XML attributes {missing} (source format drift): {opt.attrib}"
            )

        parsed_rows.append(
            I66Row(
                interval_start_at=_parse_iso_utc(opt.attrib["IntervalDateTime"]),
                interval_end_at=_parse_iso_utc(opt.attrib["IntervalEndDateTime"]),
                calculated_at=_parse_iso_utc(opt.attrib["CalculatedDateTime"]),
                corridor_id=int(opt.attrib["CorridorID"]),
                corridor_name=opt.attrib["CorridorName"],
                start_zone_id=int(opt.attrib["StartZoneID"]),
                start_zone_name=opt.attrib["StartZoneName"] or None,
                end_zone_id=int(opt.attrib["EndZoneID"]),
                end_zone_name=opt.attrib["EndZoneName"],
                zone_toll_rate_usd=Decimal(opt.attrib["ZoneTollRate"]),
            )
        )

    return parsed_rows
