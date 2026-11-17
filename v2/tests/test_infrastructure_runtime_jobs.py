import re

from tests.infrastructure_support import (
    FOUNDATION_AGENTCORE,
    FOUNDATION_TRIGGERS,
    MAIN_TF,
    assert_assignment,
    terraform_block,
)


def test_eventbridge_has_both_failure_paths_and_bounded_retries() -> None:
    loader_target = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_event_target" "loader"'
    )
    loader_permission = terraform_block(
        MAIN_TF, 'resource "aws_lambda_permission" "eventbridge_invoke"'
    )
    loader_invoke = terraform_block(
        MAIN_TF, 'resource "aws_lambda_function_event_invoke_config" "loader"'
    )
    loader_delivery_policy = terraform_block(
        MAIN_TF, 'data "aws_iam_policy_document" "delivery_failure"'
    )
    loader_error_alarm = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_metric_alarm" "loader_errors"'
    )
    loader_freshness_alarm = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_metric_alarm" "freshness"'
    )
    loader_failure_alarms = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_metric_alarm" "failure_queues"'
    )
    assert_assignment(
        loader_permission, "function_name", "aws_lambda_function.loader.function_name"
    )
    assert_assignment(loader_permission, "principal", '"events.amazonaws.com"')
    assert_assignment(
        loader_permission, "source_arn", "aws_cloudwatch_event_rule.raw_objects.arn"
    )
    assert_assignment(
        loader_target, "rule", "aws_cloudwatch_event_rule.raw_objects.name"
    )
    assert_assignment(loader_target, "arn", "aws_lambda_function.loader.arn")
    assert_assignment(loader_target, "arn", "aws_sqs_queue.delivery_failure.arn")
    assert_assignment(
        loader_invoke, "function_name", "aws_lambda_function.loader.function_name"
    )
    assert_assignment(loader_invoke, "destination", "aws_sqs_queue.invoke_failure.arn")
    assert_assignment(
        loader_delivery_policy, "resources", "[aws_sqs_queue.delivery_failure.arn]"
    )
    assert_assignment(loader_delivery_policy, "identifiers", '["events.amazonaws.com"]')
    assert_assignment(
        loader_delivery_policy, "values", "[aws_cloudwatch_event_rule.raw_objects.arn]"
    )
    assert_assignment(
        loader_freshness_alarm,
        "dimensions",
        "local.is_production ? { feed = each.key } : { feed = each.key, Environment = var.environment }",
    )
    for alarm in (loader_error_alarm, loader_freshness_alarm, loader_failure_alarms):
        assert_assignment(alarm, "alarm_actions", "local.alarm_actions")
    assert 'resource "aws_vpc_endpoint" "eventbridge"' in FOUNDATION_AGENTCORE
    assert (
        'resource "aws_vpc_security_group_egress_rule" "loader_to_eventbridge"'
        in MAIN_TF
    )
    collector = terraform_block(
        FOUNDATION_TRIGGERS,
        'resource "aws_cloudwatch_event_rule" "poll_tick"',
    )
    raw_notification = terraform_block(
        FOUNDATION_TRIGGERS,
        'resource "aws_s3_bucket_notification" "raw"',
    )
    assert_assignment(collector, "schedule_expression", '"cron(0/10 * * * ? *)"')
    assert_assignment(raw_notification, "eventbridge", "true")


def test_loader_network_and_data_access_are_scoped() -> None:
    assert "${data.aws_s3_bucket.raw.arn}/*" not in MAIN_TF
    assert '"${local.raw_bucket_arn}/raw/feed=i95/*"' in MAIN_TF
    assert '"${local.raw_bucket_arn}/raw/feed=i66/*"' in MAIN_TF


def test_timed_connectivity_role_uses_the_internal_pricing_caller() -> None:
    policy = MAIN_TF.split('data "aws_iam_policy_document" "timed_checks"', maxsplit=1)[
        1
    ].split('resource "aws_iam_role_policy" "timed_checks"', maxsplit=1)[0]

    assert re.search(
        r'name\s*=\s*"nova-toll-v2-timed-checks\$\{local\.suffix\}"', MAIN_TF
    )
    assert 'actions   = ["rds:DescribeDBInstances"]' in policy
    assert 'actions   = ["rds-db:connect"]' in policy
    assert "/${local.database_roles.pricing_caller}" in policy
    assert "/tollchat_agent" not in policy
    assert 'actions   = ["ssm:GetParameter"]' in policy
    assert (
        'resources = ["arn:aws:ssm:${data.aws_region.current.region}:'
        "${data.aws_caller_identity.current.account_id}:parameter/nova-toll/"
        'openai_api_key"]'
    ) in policy
    assert "ssm:GetParameters" not in policy
    assert "/pricing_reader" not in policy
