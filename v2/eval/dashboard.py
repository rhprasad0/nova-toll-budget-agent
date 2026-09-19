"""Persist scheduled evaluations and publish a bounded public evidence snapshot."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import boto3
from agent_tools.validate_toll_route import (
    _connect_to_database,  # pyright: ignore[reportPrivateUsage]
)
from eval.run_evaluation import load_cases
from timed_checks import NEW_YORK, SCHEDULE_WINDOW_PAIRS

if TYPE_CHECKING:
    from psycopg import Connection

TITLES = {
    "springfield-franconia-to-westpark": (
        "A price with its sources",
        "Springfield-Franconia → Westpark Drive",
        "Can the assistant explain a multi-part toll and its sources?",
        "I-95 · NORTHBOUND",
    ),
    "dulles-to-reagan-current-price": (
        "Two airports, one request",
        "Dulles Airport → Reagan Airport",
        "Can it price the requested trip without substituting another route?",
        "I-95 · SATURDAY",
    ),
    "reagan-airport-pentagon-eads-westpark-parity": (
        "“I meant a different origin”",
        "Reagan / Pentagon-Eads → Westpark",
        "Can it follow a correction and look up the new trip?",
        "I-95 · SOUTHBOUND",
    ),
    "old-keene-mill-to-reagan-i95-unavailable": (
        "Knowing when not to quote",
        "Old Keene Mill Road → Reagan Airport",
        "Can it explain unavailable roads without inventing a price?",
        "I-95 · LANE REVERSAL",
    ),
    "i66-west-to-route-7-current-price": (
        "The morning toll",
        "I-66 West → Route 7",
        "Can it distinguish an observed toll from a free trip?",
        "I-66 · EASTBOUND",
    ),
    "route-7-to-i495-south-current-price": (
        "The evening toll",
        "Route 7 → I-495 South",
        "Can it report the right route, price, time, and source?",
        "I-66 · WESTBOUND",
    ),
}
CHECKS = ("ToolCallCount", "Completeness", "Correctness")
# Only pricing facts cross the public boundary; storage keys and diagnostics do not.
PUBLIC_FIELDS = frozenset(
    {
        "origin_point_id",
        "destination_point_id",
        "pricing_profile",
        "vehicle_class",
        "payment_method",
        "transponder_mode",
        "status",
        "reason",
        "error",
        "total_usd",
        "components",
        "unavailable_components",
        "price_usd",
        "facility",
        "source_kind",
        "pricing_method",
        "observed_at",
        "calculated_at",
        "current_at",
        "source_status",
        "required_i95_directions",
        "availability",
        "evidence",
        "direction",
        "interval_end_at",
        "recent_movement",
        "comparison",
        "amount_usd",
    }
)
_PRIVATE = re.compile(
    r"(?:\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bsk-[\w-]{12,}|"
    r"arn:aws[^\s\"<>]*|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|"
    r"(?:https?://)?[\w.-]+\.(?:rds|amazonaws)\.com[^\s\"<>]*|"
    r"(?:password|authorization|api[_ -]?key)\s*[:=]\s*\S+)",
    re.I,
)


def public_text(value: object) -> str:
    text = _PRIVATE.sub("[redacted]", str(value))
    return text if len(text) <= 8000 else text[:8000] + " [truncated]"


def public_facts(value: object, depth: int = 0) -> object:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            key: public_facts(item, depth + 1)
            for key, item in cast(dict[str, object], value).items()
            if key in PUBLIC_FIELDS
        }
    if isinstance(value, list):
        return [
            public_facts(item, depth + 1) for item in cast(list[object], value)[:30]
        ]
    if isinstance(value, str):
        return public_text(value)
    return value if value is None or isinstance(value, (bool, int, float)) else None


def project_report(report: object) -> dict[str, Any]:
    """Publish verdicts and actual turns once, not one transcript per judge."""
    report_data = cast(Any, report)
    checks: list[dict[str, Any]] = []
    for case, passed, details in zip(
        report_data.cases,
        report_data.test_passes,
        report_data.detailed_results,
        strict=True,
    ):
        name = case.get("evaluator")
        if name not in CHECKS or not details:
            raise ValueError("Evaluation report is incomplete")
        detail = details[0]
        reason = (
            cast(dict[str, Any], detail).get("reason", "")
            if isinstance(detail, dict)
            else detail.reason
        )
        checks.append(
            {"name": name, "passed": bool(passed), "reason": public_text(reason)}
        )
    if sorted(item["name"] for item in checks) != sorted(CHECKS):
        raise ValueError("Evaluation report is incomplete")
    trajectory = report_data.cases[0].get("actual_trajectory")
    if hasattr(trajectory, "model_dump"):
        trajectory = trajectory.model_dump(mode="json")
    if not isinstance(trajectory, dict) or not cast(dict[str, Any], trajectory).get(
        "traces"
    ):
        raise ValueError("Evaluation report has no conversation")
    trajectory = cast(dict[str, Any], trajectory)
    turns: list[dict[str, Any]] = []
    for trace in trajectory["traces"][:3]:
        turn: dict[str, Any] = {"tools": []}
        for span in trace["spans"]:
            if "user_prompt" in span:
                turn.update(
                    user=public_text(span["user_prompt"]),
                    assistant=public_text(span["agent_response"]),
                )
            elif "tool_call" in span:
                result = span.get("tool_result", {})
                content = result.get("content")
                if isinstance(content, str):
                    content = json.loads(content)
                turn["tools"].append(
                    {
                        "name": "get_current_toll_price"
                        if span["tool_call"]["name"] == "get_current_toll_price"
                        else "unexpected_tool",
                        "arguments": public_facts(
                            span["tool_call"].get("arguments", {})
                        ),
                        "result": public_facts(content),
                    }
                )
        turns.append(turn)
    return {"checks": checks, "turns": turns, "model": "gpt-5.6-luna"}


def scenario_id(window: str, scheduled: datetime) -> str:
    cases = load_cases(
        suite="scheduled",
        window=window,
        weekday=scheduled.astimezone(NEW_YORK).isoweekday(),
    )
    if len(cases) != 1 or cases[0].name not in TITLES:
        raise ValueError("Invalid dashboard scenario")
    return str(cases[0].name)


class Store:
    def __init__(self) -> None:
        self.environment = os.environ["ENVIRONMENT"]
        if self.environment not in {"development", "production"}:
            raise ValueError("Invalid dashboard environment")
        self.bucket = os.environ["EVAL_DASHBOARD_BUCKET"]
        self.user = os.environ["EVAL_DB_USER"]

    def connect(self) -> Connection[dict[str, Any]]:
        return cast("Connection[dict[str, Any]]", _connect_to_database(self.user))

    def start(
        self, window: str, scheduled: datetime, started: datetime, stale: bool
    ) -> bool:
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO pricing.evaluation_runs
                (environment, window_id, scheduled_at, scenario_id, started_at, status)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING window_id""",
                (
                    self.environment,
                    window,
                    scheduled,
                    scenario_id(window, scheduled),
                    started,
                    "stale" if stale else "running",
                ),
            )
            return cursor.fetchone() is not None

    def finish(
        self, window: str, scheduled: datetime, status: str, evidence: dict[str, Any]
    ) -> None:
        from psycopg.types.json import Jsonb

        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE pricing.evaluation_runs SET status=%s, finished_at=%s, evidence=%s
                WHERE environment=%s AND window_id=%s AND scheduled_at=%s AND status='running'""",
                (
                    status,
                    datetime.now(UTC),
                    Jsonb(evidence),
                    self.environment,
                    window,
                    scheduled,
                ),
            )

    def publish(self) -> None:
        now = datetime.now(UTC)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT environment, window_id, scheduled_at, scenario_id, started_at,
                   finished_at, status, evidence FROM pricing.evaluation_runs
                   WHERE environment=%s AND (scheduled_at >= %s OR (window_id, scheduled_at) IN
                     (SELECT DISTINCT ON (scenario_id) window_id, scheduled_at
                      FROM pricing.evaluation_runs WHERE environment=%s
                      ORDER BY scenario_id, scheduled_at DESC)) ORDER BY scheduled_at DESC""",
                (self.environment, now - timedelta(days=7), self.environment),
            )
            rows = list(cursor.fetchall())
            cursor.execute(
                "SELECT min(started_at) AS first_run FROM pricing.evaluation_runs WHERE environment=%s",
                (self.environment,),
            )
            first_row = cursor.fetchone()
            assert first_row is not None
            first = first_row["first_run"]
        schedules: list[dict[str, str]] = []
        # Publish actual UTC occurrences, calculated with New York DST rules.
        for offset in range(-8, 9):
            day = now.astimezone(NEW_YORK) + timedelta(days=offset)
            for cron, window in SCHEDULE_WINDOW_PAIRS:
                minute, hour, _, _, weekday = cron.split()
                if day.isoweekday() != int(weekday):
                    continue
                due = day.replace(
                    hour=int(hour), minute=int(minute), second=0, microsecond=0
                )
                if first is not None and due >= first:
                    schedules.append(
                        {
                            "window_id": window,
                            "scenario_id": scenario_id(window, due),
                            "scheduled_at": due.isoformat(),
                        }
                    )
        data = {
            "schema_version": 1,
            "environment": self.environment,
            "generated_at": now.isoformat(),
            "collection_started_at": first,
            "scenarios": [
                {
                    "id": key,
                    "title": value[0],
                    "route": value[1],
                    "description": value[2],
                    "tag": value[3],
                }
                for key, value in TITLES.items()
            ],
            "runs": rows,
            "schedule": schedules,
        }
        cast(Any, boto3).client("s3").put_object(
            Bucket=self.bucket,
            Key="evals.json",
            Body=json.dumps(
                data, default=lambda value: value.isoformat(), allow_nan=False
            ).encode(),
            ContentType="application/json",
            CacheControl="no-cache, max-age=0",
        )
