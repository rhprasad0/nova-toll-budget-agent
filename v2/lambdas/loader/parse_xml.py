"""Parser for the I-66 zone-pair XML feed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from _bounds import MAX_ROWS, bounded_int, bounded_text, bounded_toll
from defusedxml import ElementTree as ET

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


def parse_trip_pricing_xml(text: str) -> list[I66Row]:
    root = ET.fromstring(text)
    opts = root.findall("opt")
    if not opts:
        raise ValueError("no <opt> rows parsed from XML")
    if len(opts) > MAX_ROWS:
        raise ValueError(f"XML row count exceeds {MAX_ROWS}")

    parsed_rows: list[I66Row] = []
    for opt in opts:
        missing = [attr for attr in REQUIRED_ATTRS if attr not in opt.attrib]
        if missing:
            raise ValueError(
                f"missing XML attributes {missing} (source format drift): {opt.attrib}"
            )
        parsed_rows.append(
            I66Row(
                interval_start_at=datetime.fromisoformat(
                    bounded_text(opt.attrib["IntervalDateTime"], "XML IntervalDateTime")
                ),
                interval_end_at=datetime.fromisoformat(
                    bounded_text(
                        opt.attrib["IntervalEndDateTime"], "XML IntervalEndDateTime"
                    )
                ),
                calculated_at=datetime.fromisoformat(
                    bounded_text(
                        opt.attrib["CalculatedDateTime"], "XML CalculatedDateTime"
                    )
                ),
                corridor_id=bounded_int(opt.attrib["CorridorID"], "XML CorridorID"),
                corridor_name=bounded_text(
                    opt.attrib["CorridorName"], "XML CorridorName"
                ),
                start_zone_id=bounded_int(opt.attrib["StartZoneID"], "XML StartZoneID"),
                start_zone_name=bounded_text(
                    opt.attrib["StartZoneName"], "XML StartZoneName"
                )
                or None,
                end_zone_id=bounded_int(opt.attrib["EndZoneID"], "XML EndZoneID"),
                end_zone_name=bounded_text(
                    opt.attrib["EndZoneName"], "XML EndZoneName"
                ),
                zone_toll_rate_usd=bounded_toll(
                    opt.attrib["ZoneTollRate"], "XML ZoneTollRate"
                ),
            )
        )
    return parsed_rows
