"""What v2/infra resolves to for development, read from a credential-free plan.

These assert on planned values, so they fail when the deployed behavior would
change and pass through renames, reformatting and refactors. IAM policy text
is unknown at plan time and stays in the text-based tests.
"""

import json
from typing import Any

import pytest

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
        if address.startswith("aws_vpc_security_group_") and "loader" in address
    }
    assert not [
        address
        for address, value in development_plan.items()
        if address.startswith("aws_vpc_security_group_")
        and value["ip_protocol"] == "-1"
    ]
    https, postgres = ("tcp", 443, 443), ("tcp", 5432, 5432)
    assert rules == {
        "loader_to_eventbridge": (*https, "sg-eventbridge"),
        "loader_to_rds": (*postgres, "sg-rds"),
        "loader_to_s3": (*https, "pl-s3"),
        "rds_from_loader": (*postgres, "sg-rds"),
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
    assert uses <= 118, (
        "Assert on the development_plan fixture's planned values instead of "
        "adding assert_assignment or terraform_block text matches."
    )
