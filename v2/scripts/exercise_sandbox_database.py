"""Exercise a sandbox database end to end and leave only review_check behind.

usage: exercise_sandbox_database.py URL --schema issue_N [--expect-cap N] [--reader-role ROLE]
"""

import argparse
import sys
import threading
import time
from dataclasses import dataclass
from typing import LiteralString
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

REVIEW_ROWS = [(1, "alpha", 11), (2, "bravo", 22), (3, "charlie", 33)]
HOLD_SECONDS = 4
CONNECTIONS = 20
ROWS = 3000
REFUSED_USER = "phoenix_factory"
REFUSED_DATABASES = ("phoenix", "nova_toll_development")
SHA256_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
BACKENDS = (
    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
    " AND usename = current_user AND backend_type = 'client backend'"
)


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def step(self, title: str) -> None:
        print(f"\n== {title}", flush=True)

    def line(self, text: str) -> None:
        print(text, flush=True)

    def check(self, ok: bool, text: str) -> None:
        self.line(f"{'PASS' if ok else 'FAIL'}: {text}")
        if not ok:
            self.failures.append(text)


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True, connect_timeout=60)


def scalar(
    conn: psycopg.Connection,
    query: LiteralString | sql.SQL | sql.Composed,
    *params: object,
) -> object:
    row = conn.execute(query, params or None).fetchone()
    assert row is not None
    return row[0]


def first_line(error: Exception) -> str:
    return str(error).strip().splitlines()[0]


def with_user(url: str, user: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(
        parts._replace(netloc=f"{user}@{parts.netloc.rpartition('@')[2]}")
    )


def with_database(url: str, database: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{database}"))


def refusal(url: str) -> str | None:
    try:
        with connect(url) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as error:
        return first_line(error)
    return None


def connection_facts(conn: psycopg.Connection, report: Report) -> None:
    report.step("1. connection")
    report.line(f"current_user = {scalar(conn, 'SELECT current_user')}")
    report.line(f"current_database() = {scalar(conn, 'SELECT current_database()')}")
    report.line(f"version = {scalar(conn, 'SELECT version()')}")
    tls = scalar(conn, "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
    report.line(f"server session uses TLS (pg_stat_ssl.ssl) = {tls}")
    report.line(
        f"client link to the URL's host uses TLS (libpq) = {conn.pgconn.ssl_in_use}"
    )


def create_tables(conn: psycopg.Connection, s: sql.Identifier) -> None:
    for statement in (
        "CREATE TABLE {s}.route (id integer PRIMARY KEY, name text NOT NULL)",
        "CREATE TABLE {s}.trip (id integer PRIMARY KEY,"
        " route_id integer NOT NULL REFERENCES {s}.route (id),"
        " toll numeric(6, 2) NOT NULL, touched_at timestamptz)",
        "CREATE INDEX trip_route_idx ON {s}.trip (route_id)",
        "CREATE FUNCTION {s}.touch() RETURNS trigger LANGUAGE plpgsql AS"
        " $$ BEGIN NEW.touched_at := now(); RETURN NEW; END $$",
        "CREATE TRIGGER trip_touch BEFORE INSERT ON {s}.trip"
        " FOR EACH ROW EXECUTE FUNCTION {s}.touch()",
        "INSERT INTO {s}.route SELECT g, 'route ' || g FROM generate_series(1, 50) g",
    ):
        conn.execute(sql.SQL(statement).format(s=s))
    conn.execute(
        sql.SQL(
            "INSERT INTO {s}.trip (id, route_id, toll)"
            " SELECT g, 1 + mod(g, 50), mod(g, 40) / 4.0 FROM generate_series(1, %s) g"
        ).format(s=s),
        (ROWS,),
    )


def tables(
    url: str, conn: psycopg.Connection, s: sql.Identifier, report: Report
) -> None:
    report.step("2. tables, rows and transactions")
    create_tables(conn, s)
    count = scalar(conn, sql.SQL("SELECT count(*) FROM {s}.trip").format(s=s))
    report.check(count == ROWS, f"{count} trip rows inserted and read back")
    stamped = scalar(
        conn,
        sql.SQL("SELECT count(*) FROM {s}.trip WHERE touched_at IS NOT NULL").format(
            s=s
        ),
    )
    report.check(stamped == ROWS, f"trigger stamped touched_at on {stamped} rows")
    top = conn.execute(
        sql.SQL(
            "SELECT r.name, count(*), sum(t.toll) FROM {s}.trip t"
            " JOIN {s}.route r ON r.id = t.route_id"
            " GROUP BY r.name ORDER BY 3 DESC, 1 LIMIT 3"
        ).format(s=s)
    ).fetchall()
    report.line(f"top three routes by total toll (name, trips, toll): {top}")
    try:
        conn.execute(
            sql.SQL(
                "INSERT INTO {s}.trip (id, route_id, toll) VALUES (-1, 999, 1)"
            ).format(s=s)
        )
        report.check(False, "foreign key accepted a trip for a missing route")
    except psycopg.errors.ForeignKeyViolation:
        report.check(True, "foreign key refused a trip for a missing route")

    insert = sql.SQL(
        "INSERT INTO {s}.trip (id, route_id, toll) VALUES (%s, 1, 1)"
    ).format(s=s)
    seen = sql.SQL("SELECT count(*) FROM {s}.trip WHERE id = %s").format(s=s)
    committed_id, rolled_back_id = ROWS + 1, ROWS + 2
    with psycopg.connect(url) as txn:
        txn.execute(insert, (committed_id,))
    with connect(url) as observer:
        found = scalar(observer, seen, committed_id)
    report.check(found == 1, "a committed transaction is visible to a new session")
    try:
        with psycopg.connect(url) as txn:
            txn.execute(insert, (rolled_back_id,))
            inside = scalar(txn, seen, rolled_back_id)
            report.line(
                f"row visible inside the transaction before rollback = {inside}"
            )
            raise RuntimeError("roll back")
    except RuntimeError:
        pass
    with connect(url) as observer:
        found = scalar(observer, seen, rolled_back_id)
    report.check(found == 0, "a rolled-back transaction left nothing behind")


def extensions(conn: psycopg.Connection, s: sql.Identifier, report: Report) -> None:
    report.step("3. extensions")
    conn.execute(sql.SQL("CREATE EXTENSION pgcrypto SCHEMA {s}").format(s=s))
    digest = scalar(
        conn, sql.SQL("SELECT encode({s}.digest('abc', 'sha256'), 'hex')").format(s=s)
    )
    report.check(
        digest == SHA256_ABC,
        "trusted extension pgcrypto created in the schema; sha256('abc') matches",
    )
    try:
        conn.execute(sql.SQL("CREATE EXTENSION postgis SCHEMA {s}").format(s=s))
        report.check(False, "untrusted extension postgis was created")
    except psycopg.Error as error:
        report.check(True, f"postgis refused: {first_line(error)}")


@dataclass
class Hold:
    error: str | None = None
    start: float = 0.0
    end: float = 0.0
    backends: int = 0


def hold(url: str, results: list[Hold], index: int) -> None:
    result = results[index]
    try:
        with connect(url) as conn:
            result.backends = int(str(scalar(conn, BACKENDS)))
            result.start = time.monotonic()
            conn.execute("SELECT pg_sleep(%s)", (HOLD_SECONDS,))
            result.end = time.monotonic()
            result.backends = max(result.backends, int(str(scalar(conn, BACKENDS))))
    except Exception as error:
        result.error = f"{type(error).__name__}: {first_line(error)}"


def concurrency(url: str, report: Report, cap: int | None) -> None:
    report.step(
        f"4. {CONNECTIONS} concurrent connections, each holding {HOLD_SECONDS} s"
    )
    results = [Hold() for _ in range(CONNECTIONS)]
    threads = [
        threading.Thread(target=hold, args=(url, results, i))
        for i in range(CONNECTIONS)
    ]
    began = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - began
    failed = [r.error for r in results if r.error]
    done = [r for r in results if not r.error]
    events = [(r.start, 1) for r in done] + [(r.end, -1) for r in done]
    running = peak = 0
    for _, delta in sorted(events):
        running += delta
        peak = max(peak, running)
    backends = max([r.backends for r in done] + [0])
    report.line(
        f"connections attempted = {CONNECTIONS}, completed = {len(done)}, failed = {len(failed)}"
    )
    for error in failed:
        report.line(f"  failure: {error}")
    report.line(
        f"most holding a running query at the same moment (client clock) = {peak}"
    )
    report.line(
        f"most client backends this user showed in pg_stat_activity = {backends}"
    )
    report.line(f"wall time for all {CONNECTIONS} = {elapsed:.1f} s")
    report.check(not failed, "no connection failed")
    if cap is not None:
        report.check(peak <= cap and backends <= cap, f"no more than {cap} ran at once")
        waves = -(-CONNECTIONS // cap)
        report.check(
            elapsed >= HOLD_SECONDS * (waves - 0.1),
            f"the connections beyond {cap} queued and ran in {waves} waves",
        )


def refusals(url: str, report: Report) -> None:
    report.step("5. refusals")
    message = refusal(with_user(url, REFUSED_USER))
    report.check(message is not None, f"user {REFUSED_USER} refused: {message}")
    for database in REFUSED_DATABASES:
        message = refusal(with_database(url, database))
        report.check(message is not None, f"database {database} refused: {message}")


def cleanup(
    conn: psycopg.Connection,
    s: sql.Identifier,
    schema: str,
    report: Report,
    reader_role: str | None,
) -> None:
    report.step("6. cleanup, leaving review_check")
    conn.execute("DROP EXTENSION IF EXISTS pgcrypto")
    conn.execute(sql.SQL("DROP TABLE IF EXISTS {s}.trip, {s}.route").format(s=s))
    conn.execute(sql.SQL("DROP FUNCTION IF EXISTS {s}.touch()").format(s=s))
    conn.execute(sql.SQL("DROP TABLE IF EXISTS {s}.review_check").format(s=s))
    conn.execute(
        sql.SQL(
            "CREATE TABLE {s}.review_check"
            " (id integer PRIMARY KEY, label text NOT NULL, value integer NOT NULL)"
        ).format(s=s)
    )
    for row in REVIEW_ROWS:
        conn.execute(
            sql.SQL("INSERT INTO {s}.review_check VALUES (%s, %s, %s)").format(s=s), row
        )
    if reader_role:
        role = sql.Identifier(reader_role)
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {s} TO {r}").format(s=s, r=role))
        conn.execute(
            sql.SQL("GRANT SELECT ON {s}.review_check TO {r}").format(s=s, r=role)
        )
        report.line(f"granted read on review_check to {reader_role}")
    rows = conn.execute(
        sql.SQL("SELECT id, label, value FROM {s}.review_check ORDER BY id").format(s=s)
    ).fetchall()
    report.line(f"review_check rows (id, label, value): {rows}")
    report.check(rows == REVIEW_ROWS, "review_check holds the expected rows")
    relations = [
        row[0]
        for row in conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = %s ORDER BY 1",
            (schema,),
        )
    ]
    report.line(f"relations in schema {schema}: {relations}")
    report.check(
        relations == ["review_check", "review_check_pkey"],
        "only review_check and its primary key index remain",
    )
    leftovers = scalar(
        conn,
        "SELECT (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
        " WHERE n.nspname = %s) + (SELECT count(*) FROM pg_extension WHERE extname IN ('pgcrypto', 'postgis'))"
        " + (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace"
        " WHERE n.nspname = %s AND t.typtype NOT IN ('c', 'b') AND t.typname NOT LIKE '\\_%%')",
        schema,
        schema,
    )
    report.line(f"functions, types and extensions left over = {leftovers}")
    report.check(leftovers == 0, "the extension, function and other objects are gone")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--expect-cap", type=int)
    parser.add_argument("--reader-role")
    args = parser.parse_args()
    report = Report()
    s = sql.Identifier(args.schema)
    with connect(args.url) as conn:
        connection_facts(conn, report)
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {s} CASCADE").format(s=s))
        conn.execute(sql.SQL("CREATE SCHEMA {s}").format(s=s))
        try:
            tables(args.url, conn, s, report)
            extensions(conn, s, report)
            concurrency(args.url, report, args.expect_cap)
            refusals(args.url, report)
        finally:
            cleanup(conn, s, args.schema, report, args.reader_role)
    print(
        f"\n{'FAILED' if report.failures else 'OK'}: {len(report.failures)} failed checks"
    )
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
