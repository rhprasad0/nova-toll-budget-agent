"""Read-only factory dashboard on 127.0.0.1:6007 (FACTORY-SPEC, Dashboard).

One HTML page from the inbox, reloaded every 10 seconds. It answers only GET; the
controls stay on GitHub (the label) and in systemd. No JavaScript, no assets.
"""

import sqlite3
from collections.abc import Sequence
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROUNDS = 3


def rows(path: Path, sql: str) -> list[sqlite3.Row]:
    if not path.exists():
        return []
    # Read-only: the dashboard never writes, and it must work with the runner stopped.
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql).fetchall()
    except sqlite3.OperationalError:  # tables not created yet
        return []
    finally:
        db.close()


def table(headers: Sequence[str], body: Sequence[Sequence[object]]) -> str:
    if not body:
        return "<p>none</p>"
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    cells = "".join(
        "<tr>"
        + "".join(f"<td>{escape('' if c is None else str(c))}</td>" for c in row)
        + "</tr>"
        for row in body
    )
    return f"<table><tr>{head}</tr>{cells}</table>"


def render(path: Path) -> str:
    status = rows(path, "SELECT * FROM status WHERE id = 1")
    s = status[0] if status else None
    health = [
        ["last poll", s and s["last_poll"]],
        ["runner heartbeat", s and s["heartbeat"]],
        ["last preflight", s and s["preflight"]],
        ["rate-limit pause until", s and s["paused_until"]],
    ]
    now = [
        [
            w["issue"],
            w["title"],
            w["station"],
            f"{w['round']} of {ROUNDS}",
            w["started"],
            w["trace_id"],
        ]
        for w in rows(
            path, "SELECT * FROM work_orders WHERE outcome IS NULL ORDER BY started"
        )
    ]
    queue = [
        [e["issue"], e["title"], e["at"]]
        for e in rows(
            path,
            "SELECT e.issue, e.at, (SELECT title FROM work_orders w WHERE w.issue = e.issue"
            " AND w.title IS NOT NULL ORDER BY started DESC LIMIT 1) AS title"
            " FROM events e WHERE kind = 'labeled' AND status = 'pending' ORDER BY id",
        )
    ]
    history = [
        [w["issue"], w["title"], w["outcome"], w["round"], w["tokens"], w["cost_usd"],
         w["pr"], {None: "", 1: "yes", 0: "no"}[w["merged"]], w["ended"]]
        for w in rows(
            path, "SELECT * FROM work_orders WHERE outcome IS NOT NULL ORDER BY ended DESC LIMIT 20"
        )
    ]  # fmt: skip
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="10">
<title>Factory</title>
<style>body{{font:14px system-ui,sans-serif;margin:1rem}}table{{border-collapse:collapse}}
td,th{{border:1px solid #888;padding:.2rem .5rem;text-align:left}}</style></head><body>
<h1>Factory</h1>
<h2>Health</h2>{table(["", ""], health)}
<h2>Now</h2>{table(["issue", "title", "station", "fix rounds", "started", "trace"], now)}
<h2>Queue</h2>{table(["issue", "title", "labeled"], queue)}
<h2>History</h2>{table(["issue", "title", "outcome", "rounds", "tokens", "list USD", "PR", "merged", "ended"], history)}
</body></html>"""


def server(path: Path, port: int = 6007) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = render(path).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
