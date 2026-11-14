"""What v2/infra resolves to for development, read from a credential-free plan.

These assert on planned values, so they fail when the deployed behavior would
change and pass through renames, reformatting and refactors. IAM policy text
is unknown at plan time and stays in the text-based tests.
"""

import json
from typing import Any

import pytest

from timed_checks import SCHEDULE_WINDOW_PAIRS

Plan = dict[str, dict[str, Any]]
ERRORS = ("AWS/Lambda", "Errors", "Sum", 300, 1, "GreaterThanOrEqualToThreshold")
QUEUED = (
    "AWS/SQS",
    "ApproximateNumberOfMessagesVisible",
    "Maximum",
    300,
    1,
    "GreaterThanOrEqualToThreshold",
)


def retries(target: dict[str, Any]) -> tuple[int, int]:
    (policy,) = target["retry_policy"]
    return policy["maximum_retry_attempts"], policy["maximum_event_age_in_seconds"]


def test_each_timed_window_runs_once_at_its_eastern_time(
    development_plan: Plan,
) -> None:
    weekdays = dict(
        zip("123456", ("MON", "TUE", "WED", "THU", "FRI", "SAT"), strict=True)
    )
    schedules = [
        value
        for address, value in development_plan.items()
        if address.startswith("aws_scheduler_schedule.timed_checks[")
    ]
    pairs: list[tuple[str, str]] = []
    for value in schedules:
        (target,) = value["target"]
        payload = json.loads(target["input"])
        minute, hour, _, _, weekday = payload["schedule"].split()
        assert (
            value["schedule_expression"]
            == f"cron({minute} {hour} ? * {weekdays[weekday]} *)"
        )
        assert value["schedule_expression_timezone"] == "America/New_York"
        assert value["state"] == "ENABLED"
        assert value["flexible_time_window"][0]["mode"] == "OFF"
        assert retries(target) == (0, 600)
        pairs.append((payload["schedule"], payload["window_id"]))
    assert sorted(pairs) == sorted(SCHEDULE_WINDOW_PAIRS)


def test_timed_check_function_is_single_private_and_alerting(
    development_plan: Plan,
) -> None:
    function = development_plan["aws_lambda_function.timed_checks"]
    assert function["reserved_concurrent_executions"] == 1
    assert function["filename"] is None
    assert function["s3_bucket"] == "artifacts-bucket"
    assert function["vpc_config"][0]["subnet_ids"] == ["subnet-a", "subnet-c"]
    variables = function["environment"][0]["variables"]
    # development.tfvars turns alerts on; the fixture mirrors it.
    assert variables["TIMED_CHECK_ALERTS_ENABLED"] == "true"
    assert variables["ENVIRONMENT"] == "development"
    assert variables["ALERTS_TOPIC_ARN"].endswith(":nova-toll-alerts")
    assert variables["EVAL_DB_USER"] == "eval_writer_development"
    # Only production keeps the legacy agent and pricing database users.
    assert not {"DB_USER", "PRICING_DB_USER"} & variables.keys()
    invoke = development_plan["aws_lambda_function_event_invoke_config.timed_checks"]
    assert invoke["maximum_retry_attempts"] == 0
    assert invoke["maximum_event_age_in_seconds"] == 600


def test_job_network_rules_are_exactly_the_reviewed_ones(
    development_plan: Plan,
) -> None:
    rules = {
        address.split(".", 1)[1]: (
            value["ip_protocol"],
            value["from_port"],
            value["to_port"],
            value["cidr_ipv4"]
            or value.get("referenced_security_group_id")
            or value.get("prefix_list_id")
            or value.get("security_group_id"),
        )
        for address, value in development_plan.items()
        if address.startswith("aws_vpc_security_group_")
        and any(job in address for job in ("timed_checks", "loader", "publisher"))
    }
    https, postgres = ("tcp", 443, 443), ("tcp", 5432, 5432)
    assert rules == {
        "timed_checks_https": (*https, "0.0.0.0/0"),
        "timed_checks_to_rds": (*postgres, "sg-rds"),
        "agentcore_from_timed_checks": (*https, "sg-agentcore"),
        "rds_from_timed_checks": (*postgres, "sg-rds"),
        "loader_to_eventbridge": (*https, "sg-eventbridge"),
        "loader_to_rds": (*postgres, "sg-rds"),
        "loader_to_s3": (*https, "pl-s3"),
        "rds_from_loader": (*postgres, "sg-rds"),
        "publisher_to_rds": (*postgres, "sg-rds"),
        "publisher_to_s3": (*https, "pl-s3"),
        "rds_from_publisher": (*postgres, "sg-rds"),
    }


def test_every_failure_queue_is_encrypted_and_kept_for_fourteen_days(
    development_plan: Plan,
) -> None:
    queues = {
        address: value
        for address, value in development_plan.items()
        if address.startswith("aws_sqs_queue.")
    }
    assert {address.split(".")[1] for address in queues} >= {
        "invoke_failure",
        "delivery_failure",
        "publisher_invoke_failure",
        "publisher_delivery_failure",
        "timed_checks_invoke_failure",
        "timed_checks_delivery_failure",
    }
    for address, queue in queues.items():
        assert queue["sqs_managed_sse_enabled"] is True, address
        assert queue["message_retention_seconds"] == 1209600, address


def test_raw_objects_reach_the_loader_with_bounded_retries(
    development_plan: Plan,
) -> None:
    pattern = json.loads(
        development_plan["aws_cloudwatch_event_rule.raw_objects"]["event_pattern"]
    )
    assert pattern["source"] == ["aws.s3"]
    assert pattern["detail-type"] == ["Object Created"]
    assert pattern["detail"]["object"]["key"] == [
        {"prefix": "raw/feed=i95/"},
        {"prefix": "raw/feed=i66/"},
    ]
    target = development_plan["aws_cloudwatch_event_target.loader"]
    assert retries(target) == (185, 86400)
    invoke = development_plan["aws_lambda_function_event_invoke_config.loader"]
    assert invoke["maximum_retry_attempts"] == 2
    assert invoke["maximum_event_age_in_seconds"] == 21600


def test_report_publisher_runs_weekly_as_one_bounded_function(
    development_plan: Plan,
) -> None:
    schedule = development_plan["aws_scheduler_schedule.publisher"]
    (target,) = schedule["target"]
    assert schedule["schedule_expression"] == "cron(0 1 ? * MON *)"
    assert schedule["schedule_expression_timezone"] == "America/New_York"
    assert schedule["flexible_time_window"][0]["mode"] == "OFF"
    assert json.loads(target["input"]) == {"trigger": "watchdog"}
    assert retries(target) == (2, 3600)
    function = development_plan["aws_lambda_function.publisher"]
    assert function["function_name"] == "toll-v2-report-publisher-dev"
    assert (function["timeout"], function["memory_size"]) == (900, 2048)
    assert function["reserved_concurrent_executions"] == 1
    assert function["environment"][0]["variables"] == {
        "DB_HOST": "db.example",
        "DB_NAME": "nova_toll_development",
        "DB_PORT": "5432",
        "DB_USER": "report_publisher_development",
        "DB_READER_USER": "pricing_reader_development",
        "PUBLIC_BASE_URL": "https://dev.tollchat.ai",
        "REPORT_PUBLICATION_ENABLED": "true",
        "TOLLCHAT_ENVIRONMENT": "development",
    }
    invoke = development_plan["aws_lambda_function_event_invoke_config.publisher"]
    assert invoke["maximum_retry_attempts"] == 2
    assert invoke["maximum_event_age_in_seconds"] == 21600


@pytest.mark.parametrize(
    ("address", "signal", "missing", "dimensions"),
    [
        (
            "loader_errors",
            ERRORS,
            "notBreaching",
            {"FunctionName": "toll-v2-pricing-loader-dev"},
        ),
        (
            "publisher_errors",
            ERRORS,
            "notBreaching",
            {"FunctionName": "toll-v2-report-publisher-dev"},
        ),
        (
            "timed_checks_errors",
            ERRORS,
            "notBreaching",
            {"FunctionName": "nova-toll-v2-timed-checks-dev"},
        ),
        (
            'failure_queues["invoke"]',
            QUEUED,
            "notBreaching",
            {"QueueName": "toll-v2-pricing-loader-invoke-failure-dev"},
        ),
        (
            'failure_queues["delivery"]',
            QUEUED,
            "notBreaching",
            {"QueueName": "toll-v2-pricing-loader-delivery-failure-dev"},
        ),
        (
            'publisher_failure_queues["invoke"]',
            QUEUED,
            "notBreaching",
            {"QueueName": "toll-v2-report-publisher-invoke-failure-dev"},
        ),
        (
            'publisher_failure_queues["delivery"]',
            QUEUED,
            "notBreaching",
            {"QueueName": "toll-v2-report-publisher-delivery-failure-dev"},
        ),
        (
            'freshness["i95"]',
            ("NovaToll", "V2LoadSuccess", "Sum", 600, 3, "LessThanThreshold"),
            "breaching",
            {"Environment": "development", "feed": "i95"},
        ),
        (
            'freshness["i66"]',
            ("NovaToll", "V2LoadSuccess", "Sum", 600, 3, "LessThanThreshold"),
            "breaching",
            {"Environment": "development", "feed": "i66"},
        ),
        (
            "report_generation_freshness",
            (
                "NovaToll",
                "V2ReportGenerationSuccess",
                "Sum",
                86400,
                7,
                "LessThanThreshold",
            ),
            "breaching",
            {"Environment": "development", "facility_scope": "both"},
        ),
    ],
)
def test_job_alarm_watches_its_signal(
    development_plan: Plan,
    address: str,
    signal: tuple[str, str, str, int, int, str],
    missing: str,
    dimensions: dict[str, str],
) -> None:
    alarm = development_plan[f"aws_cloudwatch_metric_alarm.{address}"]
    assert (
        alarm["namespace"],
        alarm["metric_name"],
        alarm["statistic"],
        alarm["period"],
        alarm["evaluation_periods"],
        alarm["comparison_operator"],
    ) == signal
    assert alarm["threshold"] == 1
    assert alarm["treat_missing_data"] == missing
    assert alarm["dimensions"] == dimensions


def test_text_matching_infrastructure_assertions_only_shrink() -> None:
    """A text match passes when behavior breaks and fails on reformatting."""
    from pathlib import Path

    uses = sum(
        path.read_text().count(helper)
        for path in Path(__file__).parent.glob("test_*.py")
        if path != Path(__file__)
        for helper in ("assert_assignment(", "terraform_block(")
    )
    assert uses <= 117, (
        "Assert on the development_plan fixture's planned values instead of "
        "adding assert_assignment or terraform_block text matches."
    )
