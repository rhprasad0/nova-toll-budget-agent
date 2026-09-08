#!/usr/bin/env python3
"""Classify bounded private deployment diagnostics without printing them."""

from __future__ import annotations

import re
import sys
from pathlib import Path

MAX_BYTES = 64 * 1024
REASONS = (
    "access_denied",
    "expired_credentials",
    "network",
    "dns",
    "tls",
    "backend_config",
    "state_lock",
    "provider_installation",
    "checksum",
    "malformed_input",
    "unclassified",
    "diagnostic_unavailable",
)

PATTERNS = (
    (
        "access_denied",
        (
            r"\baccess ?denied(?:exception)?\b",
            r"\bpermission denied\b",
            r"\bunauthori[sz]ed\b",
            r"\bforbidden\b",
        ),
    ),
    (
        "expired_credentials",
        (
            r"expired (?:credentials?|token)",
            r"\bexpired(?:token|credentials?)(?:exception)?\b",
            r"token (?:has )?expired",
            r"security token included in the request is expired",
        ),
    ),
    (
        "dns",
        (
            r"could not resolve host",
            r"name or service not known",
            r"no such host",
            r"temporary failure in name resolution",
            r"\bdns\b",
        ),
    ),
    ("tls", (r"\btls\b", r"\bssl\b", r"certificate verify failed", r"x509")),
    (
        "state_lock",
        (
            r"state lock",
            r"acquiring the state lock",
            r"conditionalcheckfailedexception",
            r"failed to lock",
        ),
    ),
    (
        "checksum",
        (r"checksum", r"doesn'?t match any of the checksums", r"integrity check"),
    ),
    (
        "provider_installation",
        (
            r"failed to install provider",
            r"provider installation",
            r"could not retrieve providers",
            r"could not find provider",
        ),
    ),
    (
        "backend_config",
        (
            r"backend configuration",
            r"configuring the backend",
            r"invalid backend",
            r"backend.*(?:bucket|key)",
        ),
    ),
    (
        "malformed_input",
        (
            r"malformed",
            r"invalid input",
            r"invalid character",
            r"unexpected end",
            r"(?:json|input).*invalid",
            r"invalid.*json",
            r"parse error",
        ),
    ),
    (
        "network",
        (
            r"\bnetwork\b",
            r"connection (?:reset|refused|timed out)",
            r"i/o timeout",
            r"timeout while connecting",
        ),
    ),
)


def _read(path: str) -> str:
    file_path = Path(path)
    with file_path.open("rb") as handle:
        data = handle.read(MAX_BYTES)
    return data.decode("utf-8")


def classify(paths: list[str]) -> str:
    if not paths:
        return "diagnostic_unavailable"
    try:
        text = "\n".join(_read(path) for path in paths)
    except (OSError, UnicodeError):
        return "diagnostic_unavailable"
    lowered = text.casefold()
    for reason, patterns in PATTERNS:
        if any(re.search(pattern, lowered) for pattern in patterns):
            return reason
    return "unclassified"


def main(argv: list[str]) -> int:
    reason = classify(argv[1:])
    print(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
