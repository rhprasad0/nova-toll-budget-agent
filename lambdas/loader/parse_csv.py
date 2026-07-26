"""Parser for the I-95 corridor CSV feed (fixed-width-padded, comma-separated).

Ported from ~/hermes-agent/tools/va_toll_ingest/va_toll_ingest/normalize.py,
adapted to the zone-based row shape in docs/poller-spec.md (no source_url or
raw_row columns) and to trip_pricing_i95's own shape (no feed discriminator,
no interval_start_at -- that's an I-66-only field).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

# Source header as VDOT actually spells it — CALULCATEDDATETIM and
# INTERVALENDDATETI are typos/truncations in the upstream feed, not ours.
# Matched exactly so any header drift fails loudly instead of silently
# mis-mapping columns.
EXPECTED_SOURCE_HEADERS = [
    "ZONETOLLRATE",
    "ODPAIRNAME",
    "ODPAIRID",
    "STARTZONENAME",
    "STARTZONEID",
    "INTERVALENDDATETI",
    "CURRENTDATETIME",
    "ENDZONENAME",
    "ENDZONEID",
    "CORRIDORN",
    "CORRIDORID",
    "CALULCATEDDATETIM",
    "LINKSTATUS",
]

SOURCE_TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
MAX_ROWS = 1_000
MAX_FIELD_LENGTH = 256
MAX_TOLL_USD = Decimal("500.00")
MAX_IDENTIFIER = 1_000_000


@dataclass(frozen=True)
class I95Row:
    interval_end_at: datetime
    current_at: datetime
    calculated_at: datetime
    corridor_id: int
    corridor_name: str
    od_pair_id: int
    od_pair_name: str
    start_zone_id: int
    start_zone_name: str | None
    end_zone_id: int
    end_zone_name: str
    zone_toll_rate_usd: Decimal
    link_status: str


def _is_blank_row(row: list[str]) -> bool:
    return not row or all(not cell.strip() for cell in row)


def _is_separator_row(row: list[str]) -> bool:
    tokens = [cell.strip() for cell in row if cell.strip()]
    return bool(tokens) and all(set(token) <= {"-", "."} for token in tokens)


def _parse_timestamp(value: str) -> datetime:
    local_time = datetime.strptime(value.strip(), "%d/%m/%y %H:%M:%S")
    # America/New_York's fall-back DST transition makes one hour ambiguous
    # each November; fold=0 resolves to the first (pre-transition) offset.
    return local_time.replace(tzinfo=SOURCE_TZ, fold=0).astimezone(UTC)


def _bounded_text(value: str, field: str) -> str:
    if len(value) > MAX_FIELD_LENGTH:
        raise ValueError(f"CSV {field} exceeds {MAX_FIELD_LENGTH} characters")
    return value


def _bounded_int(value: str, field: str) -> int:
    parsed = int(_bounded_text(value, field))
    if not 0 < parsed <= MAX_IDENTIFIER:
        raise ValueError(f"CSV {field} outside allowed range")
    return parsed


def _bounded_toll(value: str) -> Decimal:
    try:
        parsed = Decimal(_bounded_text(value, "ZONETOLLRATE"))
    except InvalidOperation as exc:
        raise ValueError("invalid CSV ZONETOLLRATE") from exc
    if not parsed.is_finite() or not Decimal("0") <= parsed <= MAX_TOLL_USD:
        raise ValueError("CSV ZONETOLLRATE outside allowed range")
    return parsed


def parse_trip_pricing_csv(text: str) -> list[I95Row]:
    csv.field_size_limit(MAX_FIELD_LENGTH)
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    while rows and _is_blank_row(rows[0]):
        rows.pop(0)

    if not rows:
        raise ValueError("no CSV content after trimming blank lines")

    header = [cell.strip() for cell in rows.pop(0)]
    if header != EXPECTED_SOURCE_HEADERS:
        raise ValueError(f"unexpected CSV header (source format drift): {header}")

    parsed_rows: list[I95Row] = []
    for row in rows:
        if _is_blank_row(row) or _is_separator_row(row):
            continue
        if len(row) != len(header):
            raise ValueError(f"unexpected column count {len(row)} for row: {row}")

        if len(parsed_rows) >= MAX_ROWS:
            raise ValueError(f"CSV row count exceeds {MAX_ROWS}")

        raw = {
            field: _bounded_text(cell.strip(), field)
            for field, cell in zip(header, row, strict=True)
        }

        parsed_rows.append(
            I95Row(
                interval_end_at=_parse_timestamp(raw["INTERVALENDDATETI"]),
                current_at=_parse_timestamp(raw["CURRENTDATETIME"]),
                calculated_at=_parse_timestamp(raw["CALULCATEDDATETIM"]),
                corridor_id=_bounded_int(raw["CORRIDORID"], "CORRIDORID"),
                corridor_name=raw["CORRIDORN"],
                od_pair_id=_bounded_int(raw["ODPAIRID"], "ODPAIRID"),
                od_pair_name=raw["ODPAIRNAME"],
                start_zone_id=_bounded_int(raw["STARTZONEID"], "STARTZONEID"),
                # Blank for some Prince William OD pairs — nullable, not "fixed".
                start_zone_name=raw["STARTZONENAME"] or None,
                end_zone_id=_bounded_int(raw["ENDZONEID"], "ENDZONEID"),
                end_zone_name=raw["ENDZONENAME"],
                zone_toll_rate_usd=_bounded_toll(raw["ZONETOLLRATE"]),
                # Availability lives here, independent of rate: rows can be
                # CLOSED with a stale nonzero rate, or open with $0.00.
                link_status=raw["LINKSTATUS"],
            )
        )

    if not parsed_rows:
        raise ValueError("no data rows parsed from CSV")

    return parsed_rows
