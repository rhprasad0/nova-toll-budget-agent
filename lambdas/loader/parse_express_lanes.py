"""Parser for Transurban's live Express Lanes snapshot
(maps-api/infra-price-confirmed-all), used to fill od_pair_ids VDOT's feed
has never published -- see docs/oracle-findings.md section 2 and
docs/poller-spec.md's "Secondary live source" section.

Unlike parse_csv.py/parse_xml.py this source has no per-row timestamp: one
"time" value is shared across the whole response. Confirmed empirically
(2026-07-25, live curl) to be America/New_York, truncated to the hour.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

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
    rows = payload.get("response")
    if not rows:
        raise ValueError("no 'response' rows in Express Lanes live snapshot")

    observed_at = _parse_time(rows[0]["time"])

    parsed_rows: list[I95LiveRow] = []
    for row in rows:
        # A row with no price carries nothing priceable to store -- distinct
        # from status "closed", which does have a real price and must not be
        # dropped (availability is status's job, not price's).
        if row["price"] == "null":
            continue

        parsed_rows.append(
            I95LiveRow(
                observed_at=observed_at,
                od_pair_id=int(row["od"].removeprefix("od_")),
                price_usd=Decimal(row["price"]),
                status=_or_none(row["status"]),
                road=_or_none(row["road"]),
                direction=_or_none(row["direction"]),
            )
        )

    if not parsed_rows:
        raise ValueError("no priced rows parsed from Express Lanes live snapshot")

    return parsed_rows
