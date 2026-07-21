"""Parser for the I-95 corridor CSV feed (fixed-width-padded, comma-separated).

Ported from ~/hermes-agent/tools/va_toll_ingest/va_toll_ingest/normalize.py,
adapted to the zone-based row shape in docs/poller-spec.md (no source_url or
raw_row columns; feed/interval_start_at added for the shared trip_pricing
table).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
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


@dataclass(frozen=True)
class TripPricingRow:
    feed: str
    interval_start_at: datetime | None
    interval_end_at: datetime
    current_at: datetime | None
    calculated_at: datetime
    corridor_id: int
    corridor_name: str
    od_pair_id: int | None
    od_pair_name: str | None
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


def parse_trip_pricing_csv(text: str) -> list[TripPricingRow]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    while rows and _is_blank_row(rows[0]):
        rows.pop(0)

    if not rows:
        raise ValueError("no CSV content after trimming blank lines")

    header = [cell.strip() for cell in rows.pop(0)]
    if header != EXPECTED_SOURCE_HEADERS:
        raise ValueError(f"unexpected CSV header (source format drift): {header}")

    parsed_rows: list[TripPricingRow] = []
    for row in rows:
        if _is_blank_row(row) or _is_separator_row(row):
            continue
        if len(row) != len(header):
            raise ValueError(f"unexpected column count {len(row)} for row: {row}")

        raw = dict(zip(header, (cell.strip() for cell in row), strict=True))

        parsed_rows.append(
            TripPricingRow(
                feed="i95",
                interval_start_at=None,
                interval_end_at=_parse_timestamp(raw["INTERVALENDDATETI"]),
                current_at=_parse_timestamp(raw["CURRENTDATETIME"]),
                calculated_at=_parse_timestamp(raw["CALULCATEDDATETIM"]),
                corridor_id=int(raw["CORRIDORID"]),
                corridor_name=raw["CORRIDORN"],
                od_pair_id=int(raw["ODPAIRID"]),
                od_pair_name=raw["ODPAIRNAME"],
                start_zone_id=int(raw["STARTZONEID"]),
                # Blank for some Prince William OD pairs — nullable, not "fixed".
                start_zone_name=raw["STARTZONENAME"] or None,
                end_zone_id=int(raw["ENDZONEID"]),
                end_zone_name=raw["ENDZONENAME"],
                zone_toll_rate_usd=Decimal(raw["ZONETOLLRATE"]),
                # Availability lives here, independent of rate: rows can be
                # CLOSED with a stale nonzero rate, or open with $0.00.
                link_status=raw["LINKSTATUS"],
            )
        )

    if not parsed_rows:
        raise ValueError("no data rows parsed from CSV")

    return parsed_rows
