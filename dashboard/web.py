import sys
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import psycopg

from dashboard import render, report

Response = tuple[int, str, str]


def respond(
    connect: Callable[[], psycopg.Connection], path: str, query: str, now: datetime
) -> Response:
    if path == "/healthz":
        return 200, "ok\n", "text/plain"
    if path != "/":
        return 404, "not found\n", "text/plain"
    range_key = parse_qs(query).get("range", ["30d"])[0]
    if range_key not in report.RANGES:
        return 400, "range must be 30d or all\n", "text/plain"
    try:
        with connect() as connection:
            connection.read_only = True
            data = report.build(connection, range_key, now)
    except psycopg.Error as error:
        print(f"database error: {error}", file=sys.stderr)
        return (
            503,
            "The dashboard database is unavailable or not set up; "
            "run python -m dashboard.migrate.\n",
            "text/plain",
        )
    return 200, render.render(data), "text/html"


def make_server(
    database_url: str,
    host: str,
    port: int,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            status, body, content_type = respond(
                lambda: psycopg.connect(database_url, connect_timeout=5),
                parts.path,
                parts.query,
                now(),
            )
            payload = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.address_string()} {format % args}", file=sys.stderr)

    return ThreadingHTTPServer((host, port), Handler)
