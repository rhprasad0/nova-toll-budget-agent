"""The dashboard over real HTTP, against a seeded inbox."""

import sqlite3
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from factory.host import dashboard, inbox


@pytest.fixture
def serve(tmp_path: Path) -> Iterator[tuple[Path, str]]:
    path = tmp_path / "inbox.db"
    server = dashboard.server(path, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield path, f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.status == 200
        return response.read().decode()


def seed(path: Path) -> None:
    db = inbox.connect(path)
    db.executescript("""
        INSERT INTO status (id, last_poll, heartbeat, preflight, paused_until)
            VALUES (1, 'poll-time', 'beat-time', 'preflight-result', 'pause-end');
        INSERT INTO events (id, kind, issue, actor, at, status) VALUES
            (1, 'labeled', 41, 'o', 't', 'done'),
            (2, 'labeled', 42, 'o', 't', 'running'),
            (3, 'labeled', 43, 'o', 't', 'pending');
        INSERT INTO work_orders (id, issue, title, event, started, ended, outcome, pr, merged)
            VALUES ('wo-41', 41, '<script>alert(1)</script>', 1, 's', 'e', 'pr_ready', 99, 1);
        INSERT INTO work_orders (id, issue, title, event, started, station, round, trace_id)
            VALUES ('wo-42', 42, 'Running one', 2, 's', 'reviewer', 2, 'trace-42');
    """)
    db.close()


def test_renders_every_section_and_escapes_titles(serve: tuple[Path, str]) -> None:
    path, url = serve
    seed(path)
    page = get(url)
    for text in ("Health", "Now", "Queue", "History", "poll-time", "beat-time",
                 "preflight-result", "pause-end", "reviewer", "2 of 3", "trace-42",
                 "<td>43</td>", "pr_ready", "<td>99</td>", "yes"):  # fmt: skip
        assert text in page, text
    assert "<script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_renders_with_no_writer_and_with_no_inbox(serve: tuple[Path, str]) -> None:
    path, url = serve
    assert "none" in get(url)  # no inbox.db yet
    seed(path)  # closed again: the runner and poller are stopped
    for sidecar in path.parent.glob("inbox.db-*"):
        sidecar.unlink()
    assert "Running one" in get(url)


def test_refuses_post(serve: tuple[Path, str]) -> None:
    path, url = serve
    seed(path)
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(
            urllib.request.Request(url, data=b"x", method="POST"), timeout=5
        )
    assert refused.value.code == 501
    assert (
        sqlite3.connect(path).execute("SELECT count(*) FROM events").fetchone()[0] == 3
    )
