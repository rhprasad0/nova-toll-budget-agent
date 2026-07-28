"""Parser for Transurban's live Express Lanes snapshot
(maps-api/infra-price-confirmed-all), used to fill od_pair_ids VDOT's feed
has never published -- see docs/oracle-findings.md section 2 and
docs/poller-spec.md's "Secondary live source" section.

Unlike parse_csv.py/parse_xml.py this source has no per-row timestamp: one
"time" value is shared across the whole response, America/New_York truncated
to the hour (confirmed over 273 consecutive captures, zero counterexamples).

The truncation is a property of the label, not the data -- prices change every
10 minutes. That is why trip_pricing_i95_live keys on captured_at rather than
on the observed_at derived here (docs/poller-spec.md, "Secondary live source").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from _bounds import MAX_IDENTIFIER, MAX_ROWS, bounded_text, bounded_toll

SOURCE_TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class I95LiveRow:
    observed_at: datetime
    od_pair_id: int
    price_usd: Decimal
    status: str | None
    road: str | None
    direction: str | None


def _parse_time(value: str) -> datetime:
    local_time = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    # Same ambiguous-DST-hour convention as parse_csv.py's _parse_timestamp.
    return local_time.replace(tzinfo=SOURCE_TZ, fold=0).astimezone(UTC)


def _or_none(value: str | None) -> str | None:
    """The feed spells SQL NULL as the literal string "null"."""
    return None if value is None or value == "null" else value


def parse_express_lanes_live_json(text: str) -> list[I95LiveRow]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Express Lanes payload must be a JSON object")
    rows = payload.get("response")
    if not rows:
        raise ValueError("no 'response' rows in Express Lanes live snapshot")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError(f"JSON row count is invalid or exceeds {MAX_ROWS}")

    if not isinstance(rows[0], dict):
        raise ValueError("JSON row is not an object")
    observed_at = _parse_time(bounded_text(rows[0].get("time"), "JSON time"))

    parsed_rows: list[I95LiveRow] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("JSON row is not an object")
        if bounded_text(row.get("time"), "JSON time") != rows[0]["time"]:
            raise ValueError("JSON response contains mixed observation times")
        # A row with no price carries nothing priceable to store -- distinct
        # from status "closed", which does have a real price and must not be
        # dropped (availability is status's job, not price's).
        if row.get("price") == "null":
            continue

        parsed_rows.append(
            I95LiveRow(
                observed_at=observed_at,
                od_pair_id=_bounded_identifier(row.get("od")),
                price_usd=bounded_toll(row.get("price"), "JSON price"),
                status=_or_none(bounded_text(row.get("status"), "JSON status")),
                road=_or_none(bounded_text(row.get("road"), "JSON road")),
                direction=_or_none(
                    bounded_text(row.get("direction"), "JSON direction")
                ),
            )
        )

    if not parsed_rows:
        raise ValueError("no priced rows parsed from Express Lanes live snapshot")

    return parsed_rows


def _bounded_identifier(value: object) -> int:
    raw = bounded_text(value, "JSON od")
    if not raw.startswith("od_"):
        raise ValueError("JSON od must start with od_")
    parsed = int(raw.removeprefix("od_"))
    if not 0 < parsed <= MAX_IDENTIFIER:
        raise ValueError("JSON od outside allowed range")
    return parsed
