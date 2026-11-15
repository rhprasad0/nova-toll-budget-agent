"""The inbox, poller and runner against a real SQLite file, with only GitHub faked.

Event payloads use the field names of a real `issues/events` page (captured
2026-11-15): id, event, created_at, actor.login, label.name, issue.number, and
issue.pull_request on PRs.
"""

import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from factory.host import inbox

OWNER = inbox.OWNER
T0 = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def event(
    key: int, kind: str, issue: int, *, minutes: float = 0, label: str = "factory",
    actor: str = OWNER, pr: bool = False,
) -> dict[str, Any]:  # fmt: skip
    created = (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
    body: dict[str, Any] = {"number": issue, "user": {"login": OWNER}}
    if pr:
        body["pull_request"] = {"url": f"https://api.github.com/pulls/{issue}"}
    return {
        "id": key, "event": kind, "created_at": created, "actor": {"login": actor},
        "label": {"name": label, "color": "0366d6"} if "label" in kind else None,
        "issue": body,
    }  # fmt: skip


class FakeGitHub:
    """Just enough of the REST API: the feed, issues, branches, PRs, and the writes."""

    def __init__(self) -> None:
        self.feed: list[dict[str, Any]] = []  # newest first, as GitHub serves it
        self.issues: dict[int, dict[str, Any]] = {}
        self.issue_events: dict[int, list[dict[str, Any]]] = {}
        self.branches: set[str] = set()
        self.open_pr_heads: set[str] = set()
        self.writes: list[tuple[str, str]] = []
        self.feed_pages_read = 0

    def issue(self, number: int, *, user: str = OWNER, labeled: bool = True) -> None:
        labels = [{"name": "factory"}] if labeled else []
        self.issues[number] = {"number": number, "state": "open", "title": f"Issue {number}",
                               "user": {"login": user}, "labels": labels}  # fmt: skip

    def api(self, path: str, method: str = "GET", **fields: str) -> Any:  # noqa: ANN401 - GitHub JSON
        url = urlsplit(path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if method != "GET":
            self.writes.append((method, url.path))
            if method == "DELETE" and (
                m := re.fullmatch(r".*/issues/(\d+)/labels/factory", url.path)
            ):
                self.issues[int(m[1])]["labels"] = []
            return {}
        if url.path.endswith("/issues/events"):
            self.feed_pages_read += 1
            page, size = int(query["page"]), int(query["per_page"])
            return self.feed[(page - 1) * size : page * size]
        if m := re.fullmatch(r".*/issues/(\d+)/events", url.path):
            return self.issue_events.get(int(m[1]), [])
        if url.path.endswith(f"/{inbox.REPO}/issues"):
            return [i for i in self.issues.values()
                    if i["state"] == "open" and {"name": "factory"} in i["labels"]]  # fmt: skip
        if m := re.fullmatch(r".*/issues/(\d+)", url.path):
            return self.issues.get(int(m[1]))
        if m := re.fullmatch(r".*/branches/(.+)", url.path):
            return {"name": m[1]} if m[1] in self.branches else None
        if url.path.endswith("/pulls"):
            return (
                [{"number": 1}]
                if query["head"].split(":")[1] in self.open_pr_heads
                else []
            )
        raise AssertionError(f"unfaked GitHub call: {method} {path}")


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return inbox.connect(tmp_path / "inbox.db")


@pytest.fixture
def gh() -> FakeGitHub:
    return FakeGitHub()


def statuses(db: sqlite3.Connection) -> dict[int, str]:
    return {r["id"]: r["status"] for r in db.execute("SELECT id, status FROM events")}


def passed() -> None:
    return None


def never(db: sqlite3.Connection, gh: inbox.GitHub, w: sqlite3.Row) -> str:
    pytest.fail("a work order ran")


def current(db: sqlite3.Connection) -> sqlite3.Row:
    row = inbox.status(db)
    assert row is not None
    return row


def start_polling(db: sqlite3.Connection, gh: FakeGitHub) -> None:
    """A first poll with nothing labeled, so later polls are ordinary ones."""
    gh.feed = [event(1, "assigned", 1, minutes=-60)]
    inbox.poll(db, gh)


def test_only_factory_labels_on_issues_are_recorded(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    gh.feed = [
        event(14, "closed", 9, minutes=4, pr=True),  # not a work order's PR
        event(13, "labeled", 8, minutes=3, pr=True),  # a PR, not an issue
        event(12, "labeled", 7, minutes=2, label="dependencies"),
        event(11, "labeled", 6, minutes=1),
        *gh.feed,
    ]
    inbox.poll(db, gh)
    assert statuses(db) == {11: "pending"}


def test_overlapping_re_read_records_nothing_twice(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    gh.feed = [event(11, "labeled", 6, minutes=1), *gh.feed]
    inbox.poll(db, gh)
    inbox.poll(db, gh)  # the five-minute overlap reads event 11 again
    assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_polling_stops_five_minutes_before_the_last_position(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    gh.feed = [event(1000 - i, "assigned", 1, minutes=-i) for i in range(300)]
    inbox.poll(db, gh)  # position is now T0
    gh.feed_pages_read = 0
    gh.feed = [event(2000, "labeled", 6, minutes=1), *gh.feed]
    inbox.poll(db, gh)
    assert gh.feed_pages_read == 1


def test_cold_start_rebuilds_the_queue_from_labeled_open_issues(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    for number in (5, 4):
        gh.issue(number)
    gh.issue(3, labeled=False)
    gh.issue_events = {
        5: [
            event(21, "labeled", 5),
            event(22, "unlabeled", 5),
            event(23, "labeled", 5),
        ],
        4: [event(10, "labeled", 4)],
        3: [event(9, "labeled", 3)],
    }
    gh.feed = [event(30, "assigned", 1)]
    inbox.poll(db, gh)
    pending = db.execute(
        "SELECT issue FROM events WHERE status = 'pending' ORDER BY id"
    )
    assert [r["issue"] for r in pending] == [4, 5]
    assert current(db)["poll_position"] == "2026-11-15T12:00:00Z"
    assert gh.feed_pages_read == 1


def test_two_labeled_events_run_oldest_first(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    gh.issue(7)
    gh.issue(6)
    gh.feed = [
        event(12, "labeled", 7, minutes=2),
        event(11, "labeled", 6, minutes=1),
        *gh.feed,
    ]
    inbox.poll(db, gh)
    ran: list[int] = []

    def work(db: sqlite3.Connection, _gh: inbox.GitHub, w: sqlite3.Row) -> str:
        ran.append(w["issue"])
        return "pr_ready"

    while inbox.step(db, gh, passed, work):
        pass
    assert ran == [6, 7]
    assert ("DELETE", f"repos/{inbox.REPO}/issues/6/labels/factory") in gh.writes


def test_unlabeled_drops_the_queued_event_but_not_a_newer_re_label(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    # All three arrive in one poll, newest first.
    gh.feed = [event(13, "labeled", 6, minutes=3), event(12, "unlabeled", 6, minutes=2),
               event(11, "labeled", 6, minutes=1), *gh.feed]  # fmt: skip
    inbox.poll(db, gh)
    assert statuses(db) == {11: "dropped", 12: "done", 13: "pending"}


def test_a_labeled_event_listed_after_its_unlabeled_stays_dropped(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    gh.feed = [event(12, "unlabeled", 6, minutes=2), *gh.feed]
    inbox.poll(db, gh)
    gh.feed = [
        event(12, "unlabeled", 6, minutes=2),
        event(11, "labeled", 6, minutes=1),
        *gh.feed[1:],
    ]  # fmt: skip GitHub listed event 11 late
    inbox.poll(db, gh)
    assert statuses(db)[11] == "dropped"


def test_unlabeled_cancels_only_a_work_order_it_postdates(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    gh.issue(6)
    gh.feed = [event(11, "labeled", 6, minutes=1), *gh.feed]
    inbox.poll(db, gh)
    marks: list[bool] = []

    def work(db: sqlite3.Connection, _gh: inbox.GitHub, w: sqlite3.Row) -> str:
        # Mid-run, GitHub shows an unlabel from before this run, then one after it.
        gh.feed = [event(10, "unlabeled", 6, minutes=0.5), *gh.feed]
        inbox.poll(db, gh)
        marks.append(inbox.cancelled(db, w["id"]))
        gh.feed = [event(15, "unlabeled", 6, minutes=4), *gh.feed]
        inbox.poll(db, gh)
        marks.append(inbox.cancelled(db, w["id"]))
        return "cancelled"

    inbox.step(db, gh, passed, work)
    assert marks == [False, True]
    # A cancel leaves the label alone: Ryan removed it, and may have re-added it.
    assert all(method != "DELETE" for method, _ in gh.writes)


def test_a_stale_event_whose_label_is_gone_is_dropped_silently(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    gh.issue(6, labeled=False)
    gh.feed = [event(11, "labeled", 6, minutes=1), *gh.feed]
    inbox.poll(db, gh)
    assert inbox.step(db, gh, passed, never)
    assert statuses(db)[11] == "dropped"
    assert gh.writes == []


def test_an_issue_another_account_wrote_is_refused_with_a_comment(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    gh.issue(6, user="stranger")
    gh.feed = [event(11, "labeled", 6, minutes=1), *gh.feed]
    inbox.poll(db, gh)
    inbox.step(db, gh, passed, never)
    assert [m for m, _ in gh.writes] == ["POST", "DELETE"]


def test_a_failing_preflight_admits_nothing_and_keeps_the_queue(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    gh.issue(6)
    gh.feed = [event(11, "labeled", 6, minutes=1), *gh.feed]
    inbox.poll(db, gh)
    assert not inbox.step(db, gh, lambda: "proxy preflight failed", never)
    assert statuses(db)[11] == "pending"
    assert "proxy preflight failed" in current(db)["preflight"]


def test_a_second_runner_exits_on_the_lock(tmp_path: Path) -> None:
    held = inbox.lock(tmp_path / "inbox.lock")
    second = subprocess.run(
        [sys.executable, "-c", "import sys; from factory.host import inbox; "
         f"inbox.lock(__import__('pathlib').Path({str(tmp_path / 'inbox.lock')!r}))"],
        cwd=Path(inbox.__file__).parents[2], capture_output=True, text=True,
    )  # fmt: skip
    held.close()
    assert second.returncode == 1
    assert "another runner holds" in second.stderr


def test_the_runner_refuses_to_start_before_stage_6(
    tmp_path: Path, gh: FakeGitHub
) -> None:
    with pytest.raises(SystemExit, match="Stage 6"):
        inbox.run_forever(tmp_path / "inbox.db", gh, passed, lambda _: None)
    assert gh.writes == []


def died(db: sqlite3.Connection, gh: FakeGitHub, issue: int) -> str:
    """Take issue's event and die inside the work order, as a killed runner would."""

    class Killed(BaseException):  # not an Exception, so step() cannot record an outcome
        pass

    def work(db: sqlite3.Connection, _gh: inbox.GitHub, w: sqlite3.Row) -> str:
        raise Killed

    with pytest.raises(Killed):
        inbox.step(db, gh, passed, work)
    return db.execute(
        "SELECT id FROM work_orders ORDER BY started DESC, rowid DESC"
    ).fetchone()[0]


def test_restart_settles_what_a_dead_runner_left(
    db: sqlite3.Connection, gh: FakeGitHub
) -> None:
    start_polling(db, gh)
    for number in (6, 7, 8):
        gh.issue(number)
    gh.feed = [event(13, "labeled", 8, minutes=3), event(12, "labeled", 7, minutes=2),
               event(11, "labeled", 6, minutes=1), *gh.feed]  # fmt: skip
    inbox.poll(db, gh)
    cleaned: list[str] = []

    # Issue 6 dies with nothing pushed: queued again once, then crashed the second time.
    first = died(db, gh, 6)
    inbox.settle(db, gh, cleaned.append)
    assert statuses(db)[11] == "pending"
    assert gh.writes == []
    second = died(db, gh, 6)
    inbox.settle(db, gh, cleaned.append)
    assert statuses(db)[11] == "done"
    assert gh.writes[-1] == ("DELETE", f"repos/{inbox.REPO}/issues/6/labels/factory")
    assert cleaned == [first, second]

    # Issue 7 dies after its first push: crashed, never retried.
    died(db, gh, 7)
    gh.branches.add("factory/issue-7")
    inbox.settle(db, gh, cleaned.append)
    outcome = db.execute(
        "SELECT outcome, outcome_posted FROM work_orders WHERE issue = 7"
    )
    assert tuple(outcome.fetchone()) == ("crashed", 1)
    assert statuses(db)[12] == "done"

    # An event left `running` with no work order goes back to pending.
    db.execute("UPDATE events SET status = 'running' WHERE id = 13")
    inbox.settle(db, gh, cleaned.append)
    assert statuses(db)[13] == "pending"
