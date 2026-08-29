"""Publish completed, privacy-safe daily snapshots from filtered WAF logs."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import boto3


class _Athena(Protocol):
    def start_query_execution(self, **kwargs: object) -> dict[str, object]: ...

    def get_query_execution(self, **kwargs: object) -> dict[str, object]: ...

    def get_query_results(self, **kwargs: object) -> dict[str, object]: ...


class _CloudWatch(Protocol):
    def get_metric_statistics(self, **kwargs: object) -> dict[str, object]: ...

    def put_metric_data(self, **kwargs: object) -> object: ...


def _query_template(name: str) -> str:
    return Path(__file__).with_name(name).read_text()


def _replay_dates(now: datetime) -> list[date]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("rollup time must include a timezone")
    today = now.astimezone(UTC).date()
    return [today - timedelta(days=offset) for offset in (2, 1, 0)]


def _coverage_percent(logged: int, waf: int) -> float:
    if logged < 0 or waf < 0:
        raise ValueError("coverage counts cannot be negative")
    if waf == 0:
        return 100.0 if logged == 0 else 0.0
    return round(min(100.0, logged * 100 / waf), 2)


def _run_query(
    athena: _Athena,
    *,
    query: str,
    database: str,
    workgroup: str,
    sleep: Callable[[float], None],
) -> str:
    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": database},
        WorkGroup=workgroup,
    )
    query_id = response.get("QueryExecutionId")
    if not isinstance(query_id, str):
        raise RuntimeError("Athena did not return a query ID")
    for _ in range(180):
        execution = athena.get_query_execution(QueryExecutionId=query_id)
        query_execution = execution.get("QueryExecution")
        status = (
            cast(dict[str, object], query_execution).get("Status")
            if isinstance(query_execution, dict)
            else None
        )
        state = (
            cast(dict[str, object], status).get("State")
            if isinstance(status, dict)
            else None
        )
        if state == "SUCCEEDED":
            return query_id
        if state in {"FAILED", "CANCELLED"}:
            reason = cast(dict[str, object], status).get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {state}: {reason}".rstrip())
        if state not in {"QUEUED", "RUNNING"}:
            raise RuntimeError(f"Athena returned unknown state: {state}")
        sleep(1)
    raise TimeoutError("Athena query did not finish within three minutes")


def _scalar(athena: _Athena, query_id: str) -> int:
    response = athena.get_query_results(QueryExecutionId=query_id, MaxResults=2)
    result_set = response.get("ResultSet")
    rows = (
        cast(dict[str, object], result_set).get("Rows")
        if isinstance(result_set, dict)
        else None
    )
    if not isinstance(rows, list):
        raise RuntimeError("Athena count query returned no value")
    typed_rows = cast(list[object], rows)
    if len(typed_rows) != 2:
        raise RuntimeError("Athena count query returned no value")
    row = typed_rows[1]
    data = cast(dict[str, object], row).get("Data") if isinstance(row, dict) else None
    value = (
        cast(dict[str, object], data[0]).get("VarCharValue")
        if isinstance(data, list) and data and isinstance(data[0], dict)
        else None
    )
    if not isinstance(value, str) or not value.isdigit():
        raise RuntimeError("Athena count query returned a malformed value")
    return int(value)


def run_rollup(
    *,
    athena: _Athena,
    cloudwatch: _CloudWatch,
    database: str,
    workgroup: str,
    web_acl_metric: str,
    route_rule_metric: str,
    now: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    completed: list[str] = []
    for report_date in _replay_dates(now):
        day = report_date.isoformat()
        run_id = f"{day}-{uuid4().hex}"
        values = {"report_date": day, "run_id": run_id}
        _run_query(
            athena,
            query=_query_template("rollup.sql").format(**values),
            database=database,
            workgroup=workgroup,
            sleep=sleep,
        )
        _run_query(
            athena,
            query=_query_template("complete.sql").format(**values),
            database=database,
            workgroup=workgroup,
            sleep=sleep,
        )
        completed.append(day)

    _run_query(
        athena,
        query=_query_template("latest_view.sql"),
        database=database,
        workgroup=workgroup,
        sleep=sleep,
    )
    coverage_date = now.astimezone(UTC).date() - timedelta(days=1)
    coverage_query_id = _run_query(
        athena,
        query=_query_template("coverage.sql").format(
            report_date=coverage_date.isoformat()
        ),
        database=database,
        workgroup=workgroup,
        sleep=sleep,
    )
    logged = _scalar(athena, coverage_query_id)
    start = datetime.combine(coverage_date, datetime.min.time(), tzinfo=UTC)
    metric = cloudwatch.get_metric_statistics(
        Namespace="AWS/WAFV2",
        MetricName="CountedRequests",
        Dimensions=[
            {"Name": "WebACL", "Value": web_acl_metric},
            {"Name": "Rule", "Value": route_rule_metric},
            {"Name": "Region", "Value": "CloudFront"},
        ],
        StartTime=start,
        EndTime=start + timedelta(days=1),
        Period=86400,
        Statistics=["Sum"],
    )
    datapoints = metric.get("Datapoints", [])
    waf_total = 0.0
    for point in cast(list[object], datapoints):
        if not isinstance(point, dict):
            continue
        value = cast(dict[str, object], point).get("Sum", 0)
        if not isinstance(value, int | float):
            raise RuntimeError("CloudWatch returned a malformed WAF count")
        waf_total += value
    waf = int(waf_total)
    coverage = _coverage_percent(logged, waf)
    environment = os.environ.get("TOLLCHAT_ENVIRONMENT", "production")
    metric_data: list[dict[str, object]] = [
        {"MetricName": "LogCoveragePercent", "Value": coverage, "Unit": "Percent"},
        {"MetricName": "RollupCompleted", "Value": 1, "Unit": "Count"},
    ]
    if environment != "production":
        for metric in metric_data:
            metric["Dimensions"] = [{"Name": "Environment", "Value": environment}]
    cloudwatch.put_metric_data(
        Namespace="TollChat/AgentReports",
        MetricData=metric_data,
    )
    return {
        "completed_dates": completed,
        "coverage_date": coverage_date.isoformat(),
        "coverage_percent": coverage,
        "logged_requests": logged,
        "waf_requests": waf,
    }


def handler(event: object, context: object) -> dict[str, object]:
    del event, context
    return run_rollup(
        athena=cast(
            _Athena,
            boto3.client("athena"),  # pyright: ignore[reportUnknownMemberType]
        ),
        cloudwatch=cast(
            _CloudWatch,
            boto3.client("cloudwatch"),  # pyright: ignore[reportUnknownMemberType]
        ),
        database=os.environ["ATHENA_DATABASE"],
        workgroup=os.environ["ATHENA_WORKGROUP"],
        web_acl_metric=os.environ["WAF_WEB_ACL_METRIC"],
        route_rule_metric=os.environ["WAF_ROUTE_RULE_METRIC"],
        now=datetime.now(UTC),
    )
