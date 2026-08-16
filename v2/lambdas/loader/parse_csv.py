"""Parser for the I-95 corridor CSV feed."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from _bounds import MAX_FIELD_LENGTH, MAX_ROWS, bounded_int, bounded_text, bounded_toll

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
    local_time = datetime.strptime(value.strip(), "%d/%m/%y %H:%M:%S")  # noqa: DTZ007
    return local_time.replace(tzinfo=SOURCE_TZ, fold=0).astimezone(UTC)


def parse_trip_pricing_csv(text: str) -> list[I95Row]:
    csv.field_size_limit(MAX_FIELD_LENGTH)
    rows = list(csv.reader(io.StringIO(text)))
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
            field: bounded_text(cell.strip(), f"CSV {field}")
            for field, cell in zip(header, row, strict=True)
        }
        parsed_rows.append(
            I95Row(
                interval_end_at=_parse_timestamp(raw["INTERVALENDDATETI"]),
                current_at=_parse_timestamp(raw["CURRENTDATETIME"]),
                calculated_at=_parse_timestamp(raw["CALULCATEDDATETIM"]),
                corridor_id=bounded_int(raw["CORRIDORID"], "CSV CORRIDORID"),
                corridor_name=raw["CORRIDORN"],
                od_pair_id=bounded_int(raw["ODPAIRID"], "CSV ODPAIRID"),
                od_pair_name=raw["ODPAIRNAME"],
                start_zone_id=bounded_int(raw["STARTZONEID"], "CSV STARTZONEID"),
                start_zone_name=raw["STARTZONENAME"] or None,
                end_zone_id=bounded_int(raw["ENDZONEID"], "CSV ENDZONEID"),
                end_zone_name=raw["ENDZONENAME"],
                zone_toll_rate_usd=bounded_toll(
                    raw["ZONETOLLRATE"], "CSV ZONETOLLRATE"
                ),
                link_status=raw["LINKSTATUS"],
            )
        )

    if not parsed_rows:
        raise ValueError("no data rows parsed from CSV")
    return parsed_rows
