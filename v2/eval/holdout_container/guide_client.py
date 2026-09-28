"""Send one bounded JSON action to the host guide; no arbitrary host commands."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any, cast

SOCKET = Path("/control/guide.sock")
MAX_REQUEST = 16 * 1024
MAX_RESPONSE = 1024 * 1024


def request(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("send one JSON object containing an action")
    value = cast(dict[str, Any], value)
    if not isinstance(value.get("action"), str):
        raise ValueError("send one JSON object containing an action")
    payload = json.dumps(value, allow_nan=False).encode() + b"\n"
    if len(payload) > MAX_REQUEST:
        raise ValueError("guide request exceeds 16 KiB")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(120)
        connection.connect(str(SOCKET))
        connection.sendall(payload)
        connection.shutdown(socket.SHUT_WR)
        chunks = bytearray()
        while True:
            part = connection.recv(min(65536, MAX_RESPONSE + 1 - len(chunks)))
            if not part:
                break
            chunks.extend(part)
            if len(chunks) > MAX_RESPONSE:
                raise ValueError("guide response exceeds 1 MiB")
    result = json.loads(chunks)
    if not isinstance(result, dict):
        raise ValueError("guide returned an invalid response")
    return cast(dict[str, Any], result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "request",
        nargs="?",
        help='JSON object, e.g. {"action":"status"}; defaults to stdin',
    )
    args = parser.parse_args()
    raw = args.request if args.request is not None else sys.stdin.read(MAX_REQUEST + 1)
    try:
        if len(raw.encode()) > MAX_REQUEST:
            raise ValueError("guide request exceeds 16 KiB")
        result = request(json.loads(raw))
    except (OSError, ValueError) as error:
        parser.exit(
            1,
            f"Guide unavailable: {error}. Reconnect through the host guide; do not repeat a paid operation.\n",
        )
    print(json.dumps(result, indent=2, allow_nan=False))
    if "error" in result:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
