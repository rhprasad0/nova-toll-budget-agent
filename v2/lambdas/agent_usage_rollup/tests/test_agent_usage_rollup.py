from datetime import UTC, date, datetime

import agent_usage_rollup_handler as rollup
import pytest


class _Athena:
    def __init__(self, states=None, result="95"):
        self.states = list(states or [])
        self.result = result
        self.queries = []

    def start_query_execution(self, **kwargs):
        self.queries.append(kwargs)
        return {"QueryExecutionId": f"query-{len(self.queries)}"}

    def get_query_execution(self, **_kwargs):
        state = self.states.pop(0) if self.states else "SUCCEEDED"
        return {"QueryExecution": {"Status": {"State": state}}}

    def get_query_results(self, **_kwargs):
        return {
            "ResultSet": {
                "Rows": [
                    {"Data": [{"VarCharValue": "_col0"}]},
                    {"Data": [{"VarCharValue": self.result}]},
                ]
            }
        }


class _CloudWatch:
    def __init__(self, waf_count=100):
        self.waf_count = waf_count
        self.metrics = []

    def get_metric_statistics(self, **_kwargs):
        return {"Datapoints": [{"Sum": self.waf_count}]}

    def put_metric_data(self, **kwargs):
        self.metrics.append(kwargs)


def test_replay_dates_are_current_and_previous_two_utc_days():
    assert rollup._replay_dates(datetime(2026, 8, 25, 3, 15, tzinfo=UTC)) == [
        date(2026, 8, 23),
        date(2026, 8, 24),
        date(2026, 8, 25),
    ]


@pytest.mark.parametrize(
    ("logged", "waf", "expected"),
    [(0, 0, 100.0), (10, 0, 0.0), (0, 10, 0.0), (95, 100, 95.0), (110, 100, 100.0)],
)
def test_coverage_is_bounded_and_zero_safe(logged, waf, expected):
    assert rollup._coverage_percent(logged, waf) == expected


def test_rollup_publishes_only_completed_runs_and_metrics(monkeypatch):
    athena = _Athena()
    cloudwatch = _CloudWatch()
    monkeypatch.setattr(rollup, "_query_template", lambda name: name)

    result = rollup.run_rollup(
        athena=athena,
        cloudwatch=cloudwatch,
        database="agent_reports",
        workgroup="agent-reports",
        web_acl_metric="tollchat-v2-public-chat",
        route_rule_metric="tollchat-v2-agent-route-report",
        now=datetime(2026, 8, 25, 3, 15, tzinfo=UTC),
        sleep=lambda _seconds: None,
    )

    rollup_queries = [
        q for q in athena.queries if q["QueryString"].startswith("rollup.sql")
    ]
    completion_queries = [
        q for q in athena.queries if q["QueryString"].startswith("complete.sql")
    ]
    assert len(rollup_queries) == len(completion_queries) == 3
    assert result["coverage_percent"] == 95.0
    assert result["completed_dates"] == ["2026-08-23", "2026-08-24", "2026-08-25"]
    assert {datum["MetricName"] for datum in cloudwatch.metrics[0]["MetricData"]} == {
        "LogCoveragePercent",
        "RollupCompleted",
    }


def test_failed_athena_write_never_publishes_completion(monkeypatch):
    athena = _Athena(states=["FAILED"])
    monkeypatch.setattr(rollup, "_query_template", lambda name: name)

    with pytest.raises(RuntimeError, match="FAILED"):
        rollup.run_rollup(
            athena=athena,
            cloudwatch=_CloudWatch(),
            database="agent_reports",
            workgroup="agent-reports",
            web_acl_metric="acl",
            route_rule_metric="route",
            now=datetime(2026, 8, 25, 3, 15, tzinfo=UTC),
            sleep=lambda _seconds: None,
        )

    assert len(athena.queries) == 1
    assert athena.queries[0]["QueryString"].startswith("rollup.sql")
