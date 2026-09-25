"""Shared signed currency parsing for offline evaluation checks."""

import re
from decimal import Decimal

CURRENCY_PATTERN = re.compile(
    r"(?P<sign_before>[+\-\u2212]?)\s*\$\s*"
    r"(?P<sign_after>[+\-\u2212]?)\s*(?P<amount>[\d,]+(?:\.\d+)?)"
)


def currency_decimal(match: re.Match[str]) -> Decimal:
    sign = match.group("sign_before") or match.group("sign_after")
    value = Decimal(match.group("amount").replace(",", ""))
    return -value if sign in ("-", "\u2212") else value
