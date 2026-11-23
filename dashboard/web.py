import sys
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import psycopg

from dashboard import render, report


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
            if parts.path == "/healthz":
                self._send(200, "ok\n", "text/plain")
            elif parts.path == "/":
                self._page(parse_qs(parts.query).get("range", ["30d"])[0])
            else:
                self._send(404, "not found\n", "text/plain")

        def _page(self, range_key: str) -> None:
            if range_key not in report.RANGES:
                self._send(400, "range must be 30d or all\n", "text/plain")
                return
            try:
                with psycopg.connect(database_url, connect_timeout=5) as connection:
                    connection.read_only = True
                    data = report.build(connection, range_key, now())
            except psycopg.Error as error:
                print(f"database error: {error}", file=sys.stderr)
                self._send(
                    503,
                    "The dashboard database is unavailable or not set up; "
                    "run python -m dashboard.migrate.\n",
                    "text/plain",
                )
                return
            self._send(200, render.render(data), "text/html")

        def _send(self, status: int, body: str, content_type: str) -> None:
            payload = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.address_string()} {format % args}", file=sys.stderr)

    return ThreadingHTTPServer((host, port), Handler)
