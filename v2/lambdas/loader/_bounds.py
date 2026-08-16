"""Shared record and field limits for the v2 pricing loader."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

MAX_ROWS = 1_000
MAX_FIELD_LENGTH = 256
MAX_TOLL_USD = Decimal("500.00")
MAX_IDENTIFIER = 1_000_000


def bounded_text(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_FIELD_LENGTH:
        raise ValueError(f"{field} is invalid or exceeds {MAX_FIELD_LENGTH} characters")
    return value


def bounded_int(value: object, field: str) -> int:
    parsed = int(bounded_text(value, field))
    if not 0 < parsed <= MAX_IDENTIFIER:
        raise ValueError(f"{field} outside allowed range")
    return parsed


def bounded_toll(value: object, field: str) -> Decimal:
    try:
        parsed = Decimal(bounded_text(value, field))
    except InvalidOperation as exc:
        raise ValueError(f"invalid {field}") from exc
    if not parsed.is_finite() or not Decimal(0) <= parsed <= MAX_TOLL_USD:
        raise ValueError(f"{field} outside allowed range")
    return parsed
