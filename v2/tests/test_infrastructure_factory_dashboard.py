"""The factory dashboard's Lambdas, alarms and CloudFront, read from root infra/'s development plan."""

import json
from typing import Any

Plan = dict[str, dict[str, Any]]
FUNCTIONS = {
    "ingest": "dashboard.aws.ingest_handler",
    "web": "dashboard.aws.web_handler",
    "issues": "dashboard.alarm_issues.handler",
}


def test_each_function_runs_its_handler_from_the_one_package(
    foundation_development_plan: Plan,
) -> None:
    for key, handler in FUNCTIONS.items():
        function = foundation_development_plan[
            f'aws_lambda_function.factory_dashboard["{key}"]'
        ]
        assert function["handler"] == handler
        assert function["runtime"] == "python3.13"
        assert function["filename"] == "tests/fetcher.zip"
        assert function["reserved_concurrent_executions"] >= 1


def test_ingest_writes_and_web_reads_the_sandbox_database_privately(
    foundation_development_plan: Plan,
) -> None:
    plan = foundation_development_plan
    ingest = plan['aws_lambda_function.factory_dashboard["ingest"]']
    web = plan['aws_lambda_function.factory_dashboard["web"]']
    issues = plan['aws_lambda_function.factory_dashboard["issues"]']
    (ingest_env,) = ingest["environment"]
    (web_env,) = web["environment"]
    assert ingest_env["variables"] == {
        "DB_HOST": "db.example",
        "DB_NAME": "factory_sandbox",
        "DB_WRITER": "factory_sandbox",
        "ADMIN_KEY_PARAMETER": "/nova-toll/factory/anthropic-admin-key",
    }
    assert web_env["variables"] == {
        "DB_HOST": "db.example",
        "DB_NAME": "factory_sandbox",
        "DB_READER": "factory_sandbox_reader",
    }
    assert len(ingest["vpc_config"]) == len(web["vpc_config"]) == 1
    assert issues["vpc_config"] == []
    web_egress = [
        rule
        for address, rule in plan.items()
        if address.startswith("aws_vpc_security_group_egress_rule.factory_dashboard")
    ]
    assert sorted(rule["from_port"] for rule in web_egress) == [443, 5432, 5432]
    assert (
        plan["aws_cloudwatch_event_rule.factory_dashboard_ingest[0]"][
            "schedule_expression"
        ]
        == "cron(15 6 * * ? *)"
    )


def test_the_site_is_cloudfront_over_a_signed_function_url(
    foundation_development_plan: Plan,
) -> None:
    plan = foundation_development_plan
    assert (
        plan["aws_lambda_function_url.factory_dashboard[0]"]["authorization_type"]
        == "AWS_IAM"
    )
    assert (
        plan["aws_cloudfront_origin_access_control.factory_dashboard[0]"][
            "origin_access_control_origin_type"
        ]
        == "lambda"
    )
    assert (
        plan["aws_acm_certificate.factory_dashboard[0]"]["domain_name"]
        == "factory.tollchat.ai"
    )
    distribution = plan["aws_cloudfront_distribution.factory_dashboard[0]"]
    (behavior,) = distribution["default_cache_behavior"]
    assert behavior["allowed_methods"] == ["GET", "HEAD"]
    assert behavior["viewer_protocol_policy"] == "redirect-to-https"
    assert distribution["aliases"] == ["factory.tollchat.ai"]
    (certificate,) = distribution["viewer_certificate"]
    assert certificate["ssl_support_method"] == "sni-only"
    assert certificate["minimum_protocol_version"] == "TLSv1.2_2021"
    policy = plan["aws_cloudfront_cache_policy.factory_dashboard[0]"]
    (key,) = policy["parameters_in_cache_key_and_forwarded_to_origin"]
    assert key["headers_config"] == [{"header_behavior": "none", "headers": []}]
    assert key["query_strings_config"] == [
        {"query_string_behavior": "whitelist", "query_strings": [{"items": ["range"]}]}
    ]


def test_dashboard_alarms_file_issues_and_the_filer_alarms_by_email(
    foundation_development_plan: Plan,
) -> None:
    plan = foundation_development_plan
    alarms = {
        address: alarm
        for address, alarm in plan.items()
        if address.startswith("aws_cloudwatch_metric_alarm.factory_dashboard[")
    }
    assert {alarm["alarm_name"] for alarm in alarms.values()} == {
        "factory-dashboard-ingest-errors",
        "factory-dashboard-ingest-missed",
        "factory-dashboard-web-5xx",
        "factory-dashboard-web-errors",
    }
    assert all(alarm["alarm_description"] for alarm in alarms.values())
    assert (
        plan["aws_sns_topic.factory_dashboard_alarms[0]"]["name"]
        == "factory-dashboard-alarms"
    )
    assert (
        plan["aws_sns_topic_subscription.factory_dashboard_alarms[0]"]["protocol"]
        == "lambda"
    )
    assert (
        plan["aws_lambda_permission.factory_alarm_issues_sns[0]"]["principal"]
        == "sns.amazonaws.com"
    )
    missed = plan[
        'aws_cloudwatch_metric_alarm.factory_dashboard["factory-dashboard-ingest-missed"]'
    ]
    assert missed["treat_missing_data"] == "breaching" and missed["period"] == 86400
    issues = plan['aws_lambda_function.factory_dashboard["issues"]']
    (env,) = issues["environment"]
    assert env["variables"]["APP_SLUG"] == "tollchat-alarms"
    assert env["variables"]["GITHUB_REPOSITORY"] == "rhprasad0/nova-toll-budget-agent"
    assert json.dumps(
        plan["aws_cloudwatch_metric_alarm.factory_alarm_issues_errors[0]"]["dimensions"]
    ) == json.dumps({"FunctionName": "factory-alarm-issues"})
