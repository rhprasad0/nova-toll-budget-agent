"""How often does each price source update, and how far behind is VDOT?

    feed_cadence.py archive [--sync]     analyse retained raw S3 objects
    feed_cadence.py watch [--duration]   bounded 60s poll of Transurban's feed

`archive` makes no request to either operator; its floor is the poller's own
10-minute tick. `watch` exists to see below that floor, and only Transurban's
unauthenticated endpoint may be polled that way -- VDOT's keeps its
one-attempt-per-tick etiquette (docs/poller-spec.md).

Findings: docs/feed-cadence-tasks.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# The loader's parsers ship flat next to each other and import as siblings
# ("from _bounds import ..."), so their own directory has to be on sys.path --
# importing them as lambdas.loader.parse_csv would break that sibling import.
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "loader"))

from parse_csv import parse_trip_pricing_csv  # noqa: E402
from parse_express_lanes import parse_express_lanes_live_json  # noqa: E402

RAW_BUCKET = "nova-toll-raw-920534282028"
AWS_PROFILE = "nova-toll"
LIVE_URL = "https://www.expresslanes.com/maps-api/infra-price-confirmed-all"
DEFAULT_CACHE = Path.home() / ".cache" / "nova-toll-raw"
TICK = timedelta(minutes=10)

# raw/feed=i95/date=2026-07-28/1010Z.csv
_KEY_RE = re.compile(r"date=(?P<date>\d{4}-\d{2}-\d{2})/(?P<tick>\d{4})Z\.\w+$")


@dataclass(frozen=True)
class Snapshot:
    tick: datetime  # the UTC 10-minute bucket this object was captured in
    fetched_at: datetime  # when the fetcher actually wrote it (S3 LastModified)
    prices: dict[int, Decimal]  # od_pair_id -> price
    interval_end_at: datetime | None  # VDOT's own label; Transurban has none


def _capture_time(path: Path) -> datetime:
    """mtime (set from S3 LastModified by `aws s3 sync`), NOT the key's tick.

    The key is the fetcher's clock floored by whatever cadence it ran at, and
    that has changed once: on 2026-07-26 the express fetcher ran a 30-minute
    tick, so key "0000Z" holds a payload fetched at 00:23:31. Aligning the two
    feeds by key name manufactures a spurious 30-minute convergence lag.
    """
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _tick_of(path: Path) -> datetime:
    """The 10-minute bucket a capture belongs to. Floor, not round: a fetch at
    :03:31 belongs to the :00 tick whose data it went to collect."""
    fetched = _capture_time(path)
    return fetched.replace(minute=fetched.minute // 10 * 10, second=0, microsecond=0)


def _sync(feed: str, cache: Path) -> None:
    dest = cache / feed
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "aws",
            "s3",
            "sync",
            f"s3://{RAW_BUCKET}/raw/feed={feed}/",
            str(dest),
            "--profile",
            AWS_PROFILE,
            "--only-show-errors",
        ],
        check=True,
    )


def _load(
    feed: str, cache: Path, since: str | None = None, until: str | None = None
) -> list[Snapshot]:
    """Every cached raw object for a feed, parsed, in tick order. since/until
    are inclusive YYYY-MM-DD bounds, for re-running the convergence search over
    disjoint sub-ranges -- an offset that moves between them is noise, not lag."""
    snapshots = []
    for path in sorted((cache / feed).rglob("*")):
        match = _KEY_RE.search(path.as_posix()) if path.is_file() else None
        if match is None:
            continue  # not a raw object (stray file, directory, sync artefact)
        date = match["date"]
        if (since and date < since) or (until and date > until):
            continue
        text = path.read_text()
        if feed == "i95":
            rows = parse_trip_pricing_csv(text)
            ends = {r.interval_end_at for r in rows}
            # One object should carry exactly one interval; more than one means
            # VDOT published a mixed payload, which _interval_integrity reports.
            end = ends.pop() if len(ends) == 1 else None
            prices = {r.od_pair_id: r.zone_toll_rate_usd for r in rows}
        else:
            rows = parse_express_lanes_live_json(text)
            end = None
            prices = {r.od_pair_id: r.price_usd for r in rows}
        snapshots.append(Snapshot(_tick_of(path), _capture_time(path), prices, end))
    snapshots.sort(key=lambda s: s.tick)
    return snapshots


def _offsets(label: str, snapshots: list[Snapshot]) -> None:
    """Where inside its tick each fetch landed, by day -- identifies a schedule
    change after the fact, and confirms a new offset took effect."""
    by_day: dict[str, list[float]] = defaultdict(list)
    for snapshot in snapshots:
        by_day[f"{snapshot.tick:%Y-%m-%d}"].append(
            (snapshot.fetched_at - snapshot.tick).total_seconds()
        )
    print(f"\n### {label}: fetch offset inside the tick\n")
    print("| date | objects | median offset | min | max |")
    print("|---|---|---|---|---|")
    for day in sorted(by_day):
        values = sorted(by_day[day])
        print(
            f"| {day} | {len(values)} | {statistics.median(values):.0f}s | "
            f"{values[0]:.0f}s | {values[-1]:.0f}s |"
        )


def _changes(snapshots: list[Snapshot]) -> list[tuple[datetime, int]]:
    """(tick, how many od pairs changed price since the previous tick)."""
    return [
        (b.tick, sum(1 for od, price in b.prices.items() if a.prices.get(od) != price))
        for a, b in zip(snapshots, snapshots[1:])
    ]


def _cadence_table(label: str, snapshots: list[Snapshot]) -> None:
    changes = _changes(snapshots)
    by_hour: dict[int, list[int]] = defaultdict(list)
    for tick, count in changes:
        by_hour[tick.hour].append(count)

    print(
        f"\n### {label}: changed od pairs per 10-minute tick "
        f"(of {len(snapshots[0].prices)})\n"
    )
    print("| UTC hour | samples | min | median | max |")
    print("|---|---|---|---|---|")
    for hour in sorted(by_hour):
        values = sorted(by_hour[hour])
        print(
            f"| {hour:02d}Z | {len(values)} | {values[0]} | "
            f"{statistics.median(values):.0f} | {values[-1]} |"
        )

    counts = [c for _, c in changes]
    zero = sum(1 for c in counts if c == 0)
    print(
        f"\n{len(counts)} tick-to-tick comparisons, **{zero} with zero change**, "
        f"median {statistics.median(counts):.0f} changed per tick."
    )


def _interval_integrity(snapshots: list[Snapshot]) -> None:
    """VDOT should publish exactly one new interval per tick, labelled with it.
    Separates publish lag (interval != capture tick) from a missed publish
    (consecutive objects repeating an interval)."""
    mismatched, repeated, mixed = [], [], []
    previous = None
    for snapshot in snapshots:
        end = snapshot.interval_end_at
        if end is None:
            mixed.append(snapshot.tick)
            continue
        if end != snapshot.tick:
            mismatched.append((snapshot.tick, end))
        if end == previous:
            repeated.append(snapshot.tick)
        previous = end

    print("\n### i95 interval integrity\n")
    print(f"- objects checked: {len(snapshots)}")
    print(f"- objects carrying more than one interval: **{len(mixed)}**")
    print(f"- interval_end_at != capture tick: **{len(mismatched)}**")
    for tick, end in mismatched[:5]:
        offset = (tick - end) / timedelta(minutes=1)
        print(
            f"    - tick {tick:%m-%d %H:%M}Z carried {end:%H:%M}Z ({offset:+.0f} min)"
        )
    print(f"- consecutive objects repeating an interval: **{len(repeated)}**")


def _convergence(vdot: list[Snapshot], live: list[Snapshot]) -> None:
    """Which Transurban moment does VDOT's published price reflect?

    Both feeds share an EventBridge tick, so snapshots align on tick directly;
    the offset with the best agreement is how far VDOT trails.

    "Movers only" answers the obvious objection to a high exact-match share --
    that prices barely move, so everything matches everything. It keeps only
    (od, tick) cases where Transurban's price changed at that tick. An artifact
    collapses both columns together; a real republish separates them.
    """
    live_by_tick = {s.tick: s.prices for s in live}
    shared = set(vdot[0].prices) & set(live[0].prices)
    moving = sum(
        1 for od in shared if len({s.prices[od] for s in live if od in s.prices}) > 1
    )
    print(
        f"\n### Convergence lag ({len(shared)} od pairs present in both feeds, "
        f"{moving} of them non-flat across the window)\n"
    )
    print(
        "| Transurban offset | paired samples | exact match | movers only | "
        "median abs diff | p90 abs diff |"
    )
    print("|---|---|---|---|---|---|")

    # Ranked on exact-match share, not median: overnight hours barely move, so
    # the median ties at $0.00 across several offsets and whichever is checked
    # first wins by accident. Exact-match share separates them cleanly.
    best = None
    for steps in range(-3, 4):
        diffs, mover_hits, mover_total = [], 0, 0
        for snapshot in vdot:
            other = live_by_tick.get(snapshot.tick + steps * TICK)
            before = live_by_tick.get(snapshot.tick + steps * TICK - TICK)
            if other is None:
                continue
            for od in shared:
                if od not in snapshot.prices or od not in other:
                    continue
                diffs.append(abs(snapshot.prices[od] - other[od]))
                if before is not None and before.get(od) not in (None, other[od]):
                    mover_total += 1
                    mover_hits += snapshot.prices[od] == other[od]
        if not diffs:
            continue
        diffs.sort()
        exact = sum(1 for d in diffs if d == 0) / len(diffs)
        median = statistics.median(diffs)
        p90 = diffs[int(len(diffs) * 0.9)]
        minutes = int(steps * TICK / timedelta(minutes=1))
        movers = (
            f"{mover_hits / mover_total:.1%} of {mover_total}" if mover_total else "n/a"
        )
        print(
            f"| {minutes:+d} min | {len(diffs)} | {exact:.1%} | {movers} | "
            f"${median:.2f} | ${p90:.2f} |"
        )
        if best is None or exact > best[1]:
            best = (minutes, exact, p90)

    if best is not None:
        print(
            f"\nVDOT's published price best matches Transurban's live price from "
            f"**{best[0]:+d} min**: {best[1]:.1%} of comparisons identical to the "
            f"cent, p90 |diff| ${best[2]:.2f}."
        )


def cmd_archive(args: argparse.Namespace) -> int:
    cache = DEFAULT_CACHE
    if args.sync:
        for feed in ("i95", "i95-live"):
            print(f"syncing {feed} ...", file=sys.stderr)
            _sync(feed, cache)

    vdot = _load("i95", cache, args.since, args.until)
    live = _load("i95-live", cache, args.since, args.until)
    if not vdot or not live:
        print("no raw objects cached -- run with --sync first", file=sys.stderr)
        return 1

    print(f"# Feed cadence — generated {datetime.now(UTC):%Y-%m-%d %H:%M}Z")
    print(
        f"\nWindow: i95 {vdot[0].tick:%m-%d %H:%M} → {vdot[-1].tick:%m-%d %H:%M}Z "
        f"({len(vdot)} objects); i95-live {live[0].tick:%m-%d %H:%M} → "
        f"{live[-1].tick:%m-%d %H:%M}Z ({len(live)} objects)"
    )

    _cadence_table("i95 (VDOT)", vdot)
    _cadence_table("i95-live (Transurban)", live)
    _offsets("i95 (VDOT)", vdot)
    _offsets("i95-live (Transurban)", live)
    _interval_integrity(vdot)
    _convergence(vdot, live)
    return 0


def _poll() -> tuple[dict[str, str], bytes]:
    """One GET. This origin sends no ETag and no Age, only `no-cache`, so a
    conditional request would never save anything -- change detection is the
    price hash."""
    with urllib.request.urlopen(LIVE_URL, timeout=30) as response:
        return dict(response.headers), response.read()


def cmd_watch(args: argparse.Namespace) -> int:
    out = Path(args.out)
    deadline = time.time() + args.duration * 60
    previous: dict[int, str] | None = None
    change_times: list[datetime] = []

    print(f"polling {LIVE_URL} every {args.interval}s for {args.duration}m -> {out}")
    with out.open("a") as handle:
        while time.time() < deadline:
            fetched_at = datetime.now(UTC)
            try:
                headers, body = _poll()
            except (urllib.error.URLError, OSError) as exc:
                # Single attempt, no retry -- same etiquette as the fetchers.
                record = {"fetched_at": fetched_at.isoformat(), "error": str(exc)}
            else:
                rows = parse_express_lanes_live_json(body.decode())
                prices = {r.od_pair_id: str(r.price_usd) for r in rows}
                record = {
                    "fetched_at": fetched_at.isoformat(),
                    "age": headers.get("Age"),
                    "date": headers.get("Date"),
                    "time_field": rows[0].observed_at.isoformat(),
                    "price_hash": hashlib.sha256(
                        json.dumps(prices, sort_keys=True).encode()
                    ).hexdigest()[:16],
                }
                if previous is not None:
                    changed = sum(1 for k, v in prices.items() if previous.get(k) != v)
                    record["changed_ods"] = changed
                    if changed:
                        change_times.append(fetched_at)
                previous = prices

            handle.write(json.dumps(record) + "\n")
            handle.flush()
            time.sleep(args.interval)

    print(f"\n{len(change_times)} content changes observed")
    if len(change_times) > 1:
        gaps = sorted(
            (b - a).total_seconds() for a, b in zip(change_times, change_times[1:])
        )
        print(
            f"seconds between changes: min {gaps[0]:.0f}, "
            f"median {statistics.median(gaps):.0f}, max {gaps[-1]:.0f}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure each price source's update cadence and VDOT's lag."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    archive = sub.add_parser("archive", help="analyse retained raw S3 objects")
    archive.add_argument(
        "--sync", action="store_true", help="aws s3 sync before analysing"
    )
    archive.add_argument("--since", help="inclusive YYYY-MM-DD lower bound")
    archive.add_argument("--until", help="inclusive YYYY-MM-DD upper bound")
    archive.set_defaults(func=cmd_archive)

    watch = sub.add_parser("watch", help="bounded 60s poll of Transurban's live feed")
    watch.add_argument(
        "--duration", type=int, default=360, help="minutes (default 360)"
    )
    watch.add_argument("--interval", type=int, default=60, help="seconds (default 60)")
    watch.add_argument("--out", default="transurban_watch.jsonl")
    watch.set_defaults(func=cmd_watch)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
