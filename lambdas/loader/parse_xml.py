"""Parser for the I-66 zone-pair XML feed (<opt .../> attribute rows).

Uses defusedxml and explicit record/field limits. Transport security alone is
not sufficient protection against a malformed or compromised upstream feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree as ET

MAX_ROWS = 1_000
MAX_FIELD_LENGTH = 256
MAX_TOLL_USD = Decimal("500.00")
MAX_IDENTIFIER = 1_000_000

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


def _bounded_text(value: str, field: str) -> str:
    if len(value) > MAX_FIELD_LENGTH:
        raise ValueError(f"XML {field} exceeds {MAX_FIELD_LENGTH} characters")
    return value


def _bounded_int(value: str, field: str) -> int:
    parsed = int(_bounded_text(value, field))
    if not 0 < parsed <= MAX_IDENTIFIER:
        raise ValueError(f"XML {field} outside allowed range")
    return parsed


def _bounded_toll(value: str) -> Decimal:
    try:
        parsed = Decimal(_bounded_text(value, "ZoneTollRate"))
    except InvalidOperation as exc:
        raise ValueError("invalid XML ZoneTollRate") from exc
    if not parsed.is_finite() or not Decimal("0") <= parsed <= MAX_TOLL_USD:
        raise ValueError("XML ZoneTollRate outside allowed range")
    return parsed


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
                interval_start_at=_parse_iso_utc(
                    _bounded_text(opt.attrib["IntervalDateTime"], "IntervalDateTime")
                ),
                interval_end_at=_parse_iso_utc(
                    _bounded_text(
                        opt.attrib["IntervalEndDateTime"], "IntervalEndDateTime"
                    )
                ),
                calculated_at=_parse_iso_utc(
                    _bounded_text(
                        opt.attrib["CalculatedDateTime"], "CalculatedDateTime"
                    )
                ),
                corridor_id=_bounded_int(opt.attrib["CorridorID"], "CorridorID"),
                corridor_name=_bounded_text(opt.attrib["CorridorName"], "CorridorName"),
                start_zone_id=_bounded_int(opt.attrib["StartZoneID"], "StartZoneID"),
                start_zone_name=_bounded_text(
                    opt.attrib["StartZoneName"], "StartZoneName"
                )
                or None,
                end_zone_id=_bounded_int(opt.attrib["EndZoneID"], "EndZoneID"),
                end_zone_name=_bounded_text(opt.attrib["EndZoneName"], "EndZoneName"),
                zone_toll_rate_usd=_bounded_toll(opt.attrib["ZoneTollRate"]),
            )
        )

    return parsed_rows
