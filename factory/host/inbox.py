"""The factory's event inbox, and the poller and runner around it (FACTORY-SPEC, Inbox).

The poller records `factory` label events and closed work-order PRs from GitHub's
issue events feed, then exits. The runner takes them one at a time. Both share a
SQLite file in the host state directory; the sandbox never sees it.

Stage 3 builds the inbox only. The work order itself (stations, push, outcome
comment) is Stage 6, so until then the runner refuses to start without a `work`.
"""

import fcntl
import json
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, TextIO

REPO = "rhprasad0/nova-toll-budget-agent"
OWNER = REPO.split("/")[0]
LABEL = "factory"
DETAIL_LIMIT = 50_000
OVERLAP = timedelta(minutes=5)  # GitHub lists some events late; re-read this far back
HEARTBEAT_SECONDS = 60
IDLE_SECONDS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,  -- GitHub's event ID: unique, and larger means later
    kind TEXT NOT NULL CHECK (kind IN ('labeled', 'unlabeled', 'closed')),
    issue INTEGER NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'dropped')),
    retried INTEGER NOT NULL DEFAULT 0  -- re-queued once after a runner died
);
CREATE TABLE IF NOT EXISTS work_orders (
    id TEXT PRIMARY KEY,
    issue INTEGER NOT NULL,
    title TEXT,
    event INTEGER NOT NULL REFERENCES events (id),
    started TEXT NOT NULL,
    ended TEXT,
    base TEXT,
    station TEXT,
    round INTEGER NOT NULL DEFAULT 0,
    trace_id TEXT,
    pr INTEGER,
    cancelled INTEGER NOT NULL DEFAULT 0,
    outcome TEXT,
    outcome_posted INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER,
    cost_usd REAL,
    merged INTEGER,
    closed TEXT,
    transcripts TEXT,
    started_comment INTEGER,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS status (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    poll_position TEXT,
    last_poll TEXT,
    heartbeat TEXT,
    preflight TEXT,
    paused_until TEXT
);
"""


type Json = dict[str, Any]


class GitHub(Protocol):
    """Everything the inbox asks of GitHub. Tests fake this; it is a credentialed service."""

    def api(self, path: str, method: str = "GET", **fields: str) -> Any: ...  # noqa: ANN401 - GitHub JSON


class GhCli:
    """GitHub through the host's `gh` login."""

    def api(self, path: str, method: str = "GET", **fields: str) -> Any:  # noqa: ANN401 - GitHub JSON
        args = ["gh", "api", "--method", method, path]
        for key, value in fields.items():
            args += ["--raw-field", f"{key}={value}"]
        done = subprocess.run(args, text=True, capture_output=True, timeout=60)
        if done.returncode != 0:
            if "HTTP 404" in done.stderr:
                return None
            raise RuntimeError(f"gh api {method} {path}: {done.stderr.strip()}")
        if not done.stdout.strip():
            return None
        if done.stdout.lstrip()[:1] in {"{", "["}:
            return json.loads(done.stdout)
        return done.stdout


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    columns = {row[1] for row in db.execute("PRAGMA table_info(work_orders)")}
    for column in ("started_comment INTEGER", "detail TEXT"):
        if column.split()[0] not in columns:
            db.execute(f"ALTER TABLE work_orders ADD COLUMN {column}")
    return db


class transaction:
    """BEGIN IMMEDIATE, so the poller and the runner never interleave a read and a write."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, kind: object, *_: object) -> None:
        self.db.execute("ROLLBACK" if kind else "COMMIT")


def status(db: sqlite3.Connection) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM status WHERE id = 1").fetchone()


def set_status(db: sqlite3.Connection, **fields: str | None) -> None:
    db.execute("INSERT OR IGNORE INTO status (id) VALUES (1)")
    for key, value in fields.items():
        db.execute(
            f"UPDATE status SET {key} = ? WHERE id = 1", (value,)
        )  # keys are ours


# Poller


def field(obj: Json | None, *keys: str) -> Any:  # noqa: ANN401 - GitHub JSON
    """obj[k1][k2]..., or None where a level is missing."""
    value: Any = obj
    for key in keys:
        value = value.get(key) if value else None
    return value


def items(gh: GitHub, path: str) -> list[Json]:
    found: list[Json] = gh.api(path) or []
    return found


def classify(event: Json, issue: int, prs: set[int]) -> str | None:
    """The inbox kind of one GitHub issue event, or None to ignore it."""
    kind = field(event, "event")
    if kind in {"labeled", "unlabeled"}:
        is_pr = bool(field(event, "issue", "pull_request"))
        if field(event, "label", "name") == LABEL and not is_pr:
            return kind
    elif kind == "closed" and issue in prs:
        return "closed"
    return None


def record(db: sqlite3.Connection, event: Json, issue: int, kind: str) -> None:
    """Record one event; an `unlabeled` event is applied in the same transaction."""
    key = event["id"]
    actor = field(event, "actor", "login") or ""
    with transaction(db):
        if kind == "labeled":
            # A late `labeled` event whose `unlabeled` is already here was cancelled
            # before it ran; record it as dropped so a re-read keeps it dropped.
            undone = db.execute(
                "SELECT 1 FROM events WHERE kind = 'unlabeled' AND issue = ? AND id > ?",
                (issue, key),
            ).fetchone()
            state = "dropped" if undone else "pending"
        else:
            state = "done" if kind == "unlabeled" else "pending"
        added = db.execute(
            "INSERT OR IGNORE INTO events (id, kind, issue, actor, at, status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (key, kind, issue, actor, event["created_at"], state),
        ).rowcount
        if kind == "unlabeled" and added:
            db.execute(
                "UPDATE events SET status = 'dropped' WHERE kind = 'labeled'"
                " AND issue = ? AND id < ? AND status = 'pending'",
                (issue, key),
            )
            db.execute(
                "UPDATE work_orders SET cancelled = 1 WHERE issue = ? AND event < ?"
                " AND outcome IS NULL",
                (issue, key),
            )


def cold_start(db: sqlite3.Connection, gh: GitHub) -> None:
    """Rebuild the queue from open issues that carry the label, oldest first."""
    found: list[tuple[Json, int]] = []
    for issue in items(
        gh, f"repos/{REPO}/issues?labels={LABEL}&state=open&per_page=100"
    ):
        if field(issue, "pull_request"):
            continue
        # shortcut: reads an issue's first 100 events only; page if an issue ever has more.
        events = items(gh, f"repos/{REPO}/issues/{issue['number']}/events?per_page=100")
        labeled = [
            e for e in events
            if field(e, "event") == "labeled" and field(e, "label", "name") == LABEL
        ]  # fmt: skip
        if labeled:
            found.append((max(labeled, key=lambda e: e["id"]), issue["number"]))
    for event, number in sorted(found, key=lambda pair: pair[0]["id"]):
        record(db, event, number, "labeled")


def poll(db: sqlite3.Connection, gh: GitHub) -> int:
    """Record new events; return how many were seen. Each call finishes in seconds."""
    current = status(db)
    position: str | None = current["poll_position"] if current else None
    if position is None:  # never polled: the runner's heartbeat may have made the row
        cold_start(db, gh)
    stop = datetime.fromisoformat(position) - OVERLAP if position else None
    query = "SELECT pr FROM work_orders WHERE pr IS NOT NULL"
    prs: set[int] = {row[0] for row in db.execute(query)}
    seen: list[Json] = []
    page = 1
    while True:
        batch = items(gh, f"repos/{REPO}/issues/events?per_page=100&page={page}")
        seen += batch
        older = stop is None or any(
            datetime.fromisoformat(e["created_at"]) < stop for e in batch
        )
        # shortcut: GitHub serves at most a few hundred recent events; a poller down
        # for days reads only those, and the cold start covers what matters.
        if older or len(batch) < 100 or page >= 10:
            break
        page += 1
    # Oldest first, so an `unlabeled` event applies after the `labeled` it follows.
    for event in sorted(seen, key=lambda e: e["id"]):
        number: int | None = field(event, "issue", "number")
        kind = classify(event, number, prs) if number else None
        if number and kind:
            record(db, event, number, kind)
    newest = max((e["created_at"] for e in seen), default=position or now())
    with transaction(db):
        set_status(db, poll_position=newest, last_poll=now())
    return len(seen)


# Runner


class Admission:
    ADMIT, DROP, REFUSE = "admit", "drop", "refuse"


def admit(gh: GitHub, event: sqlite3.Row) -> tuple[str, str, Json | None]:
    """Decide on a queued `labeled` event at dequeue: (verdict, reason, issue)."""
    issue: Json | None = gh.api(f"repos/{REPO}/issues/{event['issue']}")
    found: list[Json] = field(issue, "labels") or []
    labels = {label["name"] for label in found}
    if not issue or issue.get("state") != "open" or LABEL not in labels:
        return Admission.DROP, "the label is gone", issue
    if issue["user"]["login"] != OWNER or event["actor"] != OWNER:
        return (
            Admission.REFUSE,
            f"only issues that {OWNER} wrote and labeled are admitted",
            issue,
        )
    branch = f"factory/issue-{event['issue']}"
    if gh.api(f"repos/{REPO}/branches/{branch}") is not None:
        return Admission.REFUSE, f"branch `{branch}` already exists", issue
    if gh.api(f"repos/{REPO}/pulls?head={OWNER}:{branch}&state=open"):
        return Admission.REFUSE, f"an open PR already comes from `{branch}`", issue
    return Admission.ADMIT, "", issue


def outcome_text(work_order: sqlite3.Row) -> str:
    lines = [
        f"Factory work order `{work_order['id']}` ended: **{work_order['outcome']}**."
    ]
    if work_order["detail"]:
        detail = str(work_order["detail"])[:DETAIL_LIMIT]
        runs = re.findall(r"`+", detail)
        fence = "`" * max(3, max((len(run) for run in runs), default=0) + 1)
        lines.append(f"{fence}text\n{detail}\n{fence}")
    if work_order["pr"]:
        lines.append(f"Pull request: #{work_order['pr']}")
    lines.append(f"Fix rounds used: {work_order['round']} of 3")
    if work_order["tokens"]:
        cost = (
            f", about ${work_order['cost_usd']:.2f} at list price"
            if work_order["cost_usd"]
            else ""
        )
        lines.append(f"Tokens: {work_order['tokens']:,}{cost}")
    if work_order["trace_id"]:
        lines.append(
            f"Trace, through the SSH tunnel: http://localhost:6006/redirects/traces/{work_order['trace_id']}"
        )
    return "\n\n".join(lines)


def post_outcome(db: sqlite3.Connection, gh: GitHub, work_order: sqlite3.Row) -> None:
    issue = work_order["issue"]
    text = outcome_text(work_order)
    try:
        edited = None
        if work_order["started_comment"]:
            comment = work_order["started_comment"]
            edited = gh.api(
                f"repos/{REPO}/issues/comments/{comment}", "PATCH", body=text
            )
        if edited is None:
            gh.api(f"repos/{REPO}/issues/{issue}/comments", "POST", body=text)
        if work_order["outcome"] != "cancelled":
            gh.api(f"repos/{REPO}/issues/{issue}/labels/{LABEL}", "DELETE")
    except RuntimeError as error:
        print(f"posting the outcome of {work_order['id']} failed: {error}", flush=True)
    with transaction(db):
        db.execute(
            "UPDATE work_orders SET outcome_posted = 1 WHERE id = ?",
            (work_order["id"],),
        )


def sweep(db: sqlite3.Connection, gh: GitHub) -> None:
    for event in db.execute(
        "SELECT * FROM events WHERE kind = 'closed' AND status = 'pending'"
    ).fetchall():
        try:
            pr: Json | None = gh.api(f"repos/{REPO}/pulls/{event['issue']}")
        except RuntimeError:
            continue
        with transaction(db):
            db.execute(
                "UPDATE work_orders SET merged = ?, closed = ? WHERE pr = ?",
                (
                    int(bool(field(pr, "merged"))),
                    field(pr, "closed_at") or event["at"],
                    event["issue"],
                ),
            )
            db.execute("UPDATE events SET status = 'done' WHERE id = ?", (event["id"],))


def settle(db: sqlite3.Connection, gh: GitHub, cleanup: Callable[[str], None]) -> None:
    """Settle what a previous runner left (FACTORY-SPEC, Inbox, Restart)."""
    with transaction(db):
        db.execute(
            "UPDATE events SET status = 'pending' WHERE status = 'running'"
            " AND id NOT IN (SELECT event FROM work_orders WHERE outcome IS NULL)"
        )
    for work_order in db.execute(
        "SELECT * FROM work_orders WHERE outcome IS NULL"
    ).fetchall():
        # shortcut: leftover transcripts are not copied and no span is ended until
        # Stage 6 writes them (FACTORY-PLAN Stages 5 and 6).
        cleanup(work_order["id"])
        event = db.execute(
            "SELECT * FROM events WHERE id = ?", (work_order["event"],)
        ).fetchone()
        pushed = (
            gh.api(f"repos/{REPO}/branches/factory/issue-{work_order['issue']}")
            is not None
        )
        outcome = "cancelled" if work_order["cancelled"] else "crashed"
        retry = outcome == "crashed" and not pushed and not event["retried"]
        with transaction(db):
            db.execute(
                "UPDATE work_orders SET outcome = ?, ended = ?, outcome_posted = ? WHERE id = ?",
                (outcome, now(), int(retry), work_order["id"]),
            )
            db.execute(
                "UPDATE events SET status = ?, retried = retried + ? WHERE id = ?",
                ("pending" if retry else "done", int(retry), event["id"]),
            )
    for work_order in db.execute(
        "SELECT * FROM work_orders WHERE outcome IS NOT NULL AND outcome_posted = 0"
    ).fetchall():
        post_outcome(db, gh, work_order)


def superseded(db: sqlite3.Connection, event: sqlite3.Row) -> bool:
    """Whether the label came off after this event; call inside a transaction."""
    return (
        db.execute(
            "SELECT 1 FROM events WHERE kind = 'unlabeled' AND issue = ? AND id > ?",
            (event["issue"], event["id"]),
        ).fetchone()
        is not None
    )


def step(
    db: sqlite3.Connection,
    gh: GitHub,
    preflight: Callable[[], str | None],
    work: Callable[[sqlite3.Connection, GitHub, sqlite3.Row], str],
) -> bool:
    """Handle at most one event; return whether there was one."""
    sweep(db, gh)
    paused = (status(db) or {"paused_until": None})["paused_until"]
    if paused and paused > now():
        return False
    event = db.execute(
        "SELECT * FROM events WHERE kind = 'labeled' AND status = 'pending' ORDER BY id LIMIT 1"
    ).fetchone()
    if event is None:
        return False
    problem = preflight()
    with transaction(db):
        set_status(db, preflight=f"{now()} {problem or 'passed'}")
    if problem:
        return False  # admit nothing; the event keeps its place
    with transaction(db):
        claimed = db.execute(
            "UPDATE events SET status = 'running' WHERE id = ? AND status = 'pending'",
            (event["id"],),
        ).rowcount
    if not claimed:  # the poller dropped it during the preflight
        return True
    verdict, reason, issue = admit(gh, event)
    work_order_id = f"factory-issue-{event['issue']}-{uuid.uuid4().hex[:6]}"
    with transaction(db):
        # Checked with the insert, so an unlabel the poller records during admit()
        # either drops the event here or finds the work order to cancel.
        if verdict == Admission.DROP or superseded(db, event):
            db.execute(
                "UPDATE events SET status = 'dropped' WHERE id = ?", (event["id"],)
            )
            return True
        if verdict == Admission.ADMIT:
            db.execute(
                "INSERT INTO work_orders (id, issue, title, event, started)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    work_order_id,
                    event["issue"],
                    field(issue, "title"),
                    event["id"],
                    now(),
                ),
            )
    if verdict == Admission.REFUSE:
        gh.api(f"repos/{REPO}/issues/{event['issue']}/comments", "POST",
               body=f"The factory did not start: {reason}.")  # fmt: skip
        gh.api(f"repos/{REPO}/issues/{event['issue']}/labels/{LABEL}", "DELETE")
        with transaction(db):
            db.execute("UPDATE events SET status = 'done' WHERE id = ?", (event["id"],))
        return True
    work_order = db.execute(
        "SELECT * FROM work_orders WHERE id = ?", (work_order_id,)
    ).fetchone()
    try:
        outcome = work(db, gh, work_order)
    except Exception:  # any failure ends the work order, never the runner
        outcome = "crashed"
    with transaction(db):
        db.execute(
            "UPDATE work_orders SET outcome = ?, ended = ? WHERE id = ?",
            (outcome, now(), work_order_id),
        )
        db.execute("UPDATE events SET status = 'done' WHERE id = ?", (event["id"],))
    work_order = db.execute(
        "SELECT * FROM work_orders WHERE id = ?", (work_order_id,)
    ).fetchone()
    post_outcome(db, gh, work_order)
    return True


def cancelled(db: sqlite3.Connection, work_order_id: str) -> bool:
    """The poller's cancel mark; Stage 6's runner checks it between steps."""
    row = db.execute(
        "SELECT cancelled FROM work_orders WHERE id = ?", (work_order_id,)
    ).fetchone()
    return bool(row and row["cancelled"])


def lock(path: Path) -> TextIO:
    """Hold an exclusive lock for the process's life, or exit if another runner has it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"another runner holds {path}") from None
    return handle


def heartbeat(path: Path, stop: threading.Event) -> None:
    """Update the heartbeat every minute, idle or busy, from its own connection."""
    db = connect(path)
    while True:
        try:
            with transaction(db):
                set_status(db, heartbeat=now())
        except sqlite3.Error as error:  # a stale heartbeat on the dashboard says enough
            print(f"heartbeat: {error}", flush=True)
        if stop.wait(HEARTBEAT_SECONDS):
            return


def run_forever(
    path: Path,
    gh: GitHub,
    preflight: Callable[[], str | None],
    cleanup: Callable[[str], None],
    work: Callable[[sqlite3.Connection, GitHub, sqlite3.Row], str] | None = None,
) -> None:
    if work is None:  # fail closed: settle and admission both write to GitHub
        raise SystemExit(
            "the runner has no work order to run until FACTORY-PLAN Stage 6"
        )
    held = lock(path.with_suffix(".lock"))
    db = connect(path)
    settle(db, gh, cleanup)
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(path, stop), daemon=True).start()
    try:
        while True:
            if not step(db, gh, preflight, work):
                time.sleep(IDLE_SECONDS)
    finally:
        stop.set()
        held.close()
