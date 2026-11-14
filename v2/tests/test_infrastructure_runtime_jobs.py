import re

from tests.infrastructure_support import (
    APPLICATION_VARIABLES,
    DEVELOPMENT_PLAN_WORKFLOW,
    DEVELOPMENT_TFVARS,
    ENVIRONMENT_TF,
    FOUNDATION_AGENTCORE,
    FOUNDATION_TRIGGERS,
    MAIN_TF,
    PRODUCTION_PLAN_WORKFLOW,
    PUBLISHER_HANDLER,
    TIMED_CHECKS_TF,
    V2_ROOT,
    VERIFY_SCRIPT,
    assert_assignment,
    terraform_block,
)


def test_timed_lambda_scheduler_and_failure_contract() -> None:
    lambda_block = terraform_block(
        TIMED_CHECKS_TF, 'resource "aws_lambda_function" "timed_checks"'
    )

    assert TIMED_CHECKS_TF.count("alarm_actions       = local.alarm_actions") == 2

    lambda_trust = terraform_block(
        TIMED_CHECKS_TF,
        'data "aws_iam_policy_document" "timed_checks_lambda_assume"',
    )
    scheduler_trust = terraform_block(
        TIMED_CHECKS_TF,
        'data "aws_iam_policy_document" "timed_checks_scheduler_assume"',
    )
    assert 'identifiers = ["lambda.amazonaws.com"]' in lambda_trust
    assert 'identifiers = ["scheduler.amazonaws.com"]' in scheduler_trust
    assert 'variable = "aws:SourceAccount"' in scheduler_trust
    assert 'variable = "aws:SourceArn"' in scheduler_trust

    lambda_policy = terraform_block(
        TIMED_CHECKS_TF,
        'resource "aws_iam_role_policy" "timed_checks_lambda"',
    )
    assert 'Action   = ["rds:DescribeDBInstances"]' in lambda_policy
    assert "/${local.eval_db_user}" in lambda_policy
    legacy_policy = lambda_policy.split("], local.is_production ? [{", 1)[1]
    assert 'Sid    = "ConnectRdsIam"' in legacy_policy
    assert "/${local.database_roles.agent}" in legacy_policy
    assert "/${local.database_roles.pricing_caller}" in legacy_policy
    assert "}] : [])" in legacy_policy
    assert (
        "local.is_production ? {\n"
        "      DB_USER         = local.database_roles.agent\n"
        "      PRICING_DB_USER = local.database_roles.pricing_caller\n"
        "      } : {}" in lambda_block
    )
    for action in (
        "cloudfront:GetDistribution",
        "lambda:GetFunctionUrlConfig",
        "lambda:GetAlias",
        "lambda:GetFunctionConfiguration",
        "bedrock-agentcore:GetAgentRuntimeEndpoint",
        "bedrock-agentcore:InvokeAgentRuntime",
    ):
        assert action in lambda_policy
    assert (
        '"aws:SourceVpce" = var.foundation.agentcore_vpc_endpoint_id' in lambda_policy
    )
    assert "Resource = [aws_cloudfront_distribution.site.arn]" in lambda_policy
    assert "values(local.agentcore_policy_resources)" in lambda_policy
    assert (
        'resource "aws_vpc_security_group_ingress_rule" "agentcore_from_timed_checks"'
        in TIMED_CHECKS_TF
    )
    assert "EVAL_SITE_DISTRIBUTION_ID" in lambda_block
    assert "AGENTCORE_VPCE_URL" in lambda_block
    assert 'Action   = ["ssm:GetParameter"]' in lambda_policy
    assert 'Action   = ["sqs:SendMessage"]' in lambda_policy
    assert 'Action   = ["sns:Publish"]' in lambda_policy
    assert "Resource = [var.foundation.alerts_topic_arn]" in lambda_policy
    assert 'Action   = ["kms:Decrypt", "kms:GenerateDataKey*"]' in lambda_policy
    assert "Resource = [data.aws_kms_alias.alerts.target_key_arn]" in lambda_policy
    assert 'Resource = ["*"]' not in lambda_policy
    assert (
        'var.environment == "development" || !var.enable_development_timed_check_alerts'
        in APPLICATION_VARIABLES
    )
    assert "enable_development_timed_check_alerts = true" in DEVELOPMENT_TFVARS.replace(
        "      ", " "
    )


def test_timed_package_is_threaded_through_all_plan_paths() -> None:
    assert (
        "-var timed_checks_package_path=build/timed-checks.zip"
        in DEVELOPMENT_PLAN_WORKFLOW
    )
    assert (
        '("timed_checks", "timed-checks")'
        in (V2_ROOT / "scripts/release_blue_green.py").read_text()
    )
    assert '--bundle-root "$overlay"' in PRODUCTION_PLAN_WORKFLOW
    assert (
        'blue_green.py prepare --environment production --plan "$plan_json" --saved-plan "$plan"'
        in PRODUCTION_PLAN_WORKFLOW
    )
    assert (
        '--package-evidence "$RUNNER_TEMP/blue-green/package-evidence.json"'
        in PRODUCTION_PLAN_WORKFLOW
    )
    assert "-target" not in PRODUCTION_PLAN_WORKFLOW


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


def test_report_publisher_is_weekly_bounded_and_least_privilege() -> None:
    variables = (V2_ROOT / "infra" / "variables.tf").read_text()
    assert 'variable "publisher_package_path"' in variables
    policy = terraform_block(MAIN_TF, 'data "aws_iam_policy_document" "publisher"')
    rds_resources = re.search(
        r'(?s)sid\s*=\s*"ConnectRdsIam"\s+actions\s*=\s*\["rds-db:connect"\]\s+'
        r"resources\s*=\s*\[(.*?)\]",
        policy,
    )
    assert rds_resources
    assert re.findall(r'"([^"]+)"', rds_resources.group(1)) == [
        "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.publisher}",
        "arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.foundation.db_instance.resource_id}/${local.database_roles.reader}",
    ]
    assert "*" not in rds_resources.group(1)
    assert "s3:GetObject" not in policy
    assert 'actions   = ["s3:ListBucket"]' in policy
    assert 'variable = "s3:prefix"' in policy
    assert 'values   = ["tolls/i95-i495/", "tolls/i66/"]' in policy
    assert re.search(r'actions\s+= \["s3:PutObject"\]', policy)
    assert "tolls/i95-i495/*" in policy
    assert "tolls/i66/*" in policy
    assert "sitemap.xml" in policy
    assert 'actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]' in policy
    assert re.search(r'actions\s+= \["s3:DeleteObject"\]', policy)
    assert '"${aws_s3_bucket.site.arn}/tolls/i95-i495/*"' in policy
    assert '"${aws_s3_bucket.site.arn}/tolls/i66/*"' in policy
    assert "s3:DeleteObjectVersion" not in policy
    publisher_lambda = MAIN_TF.split(
        'resource "aws_lambda_function" "publisher"', maxsplit=1
    )[1].split(
        'resource "aws_lambda_function_event_invoke_config" "publisher"', maxsplit=1
    )[0]
    assert "aws_cloudfront_distribution.site" in publisher_lambda
    assert "aws_iam_role_policy.publisher" in publisher_lambda
    assert "aws_s3_object.robots" in publisher_lambda
    assert (
        'resource "aws_cloudwatch_log_metric_filter" "report_generation_success"'
        not in MAIN_TF
    )
    assert "cloudwatch:PutMetricData" not in MAIN_TF
    assert "put_metric_data" not in PUBLISHER_HANDLER
    assert "print(" in PUBLISHER_HANDLER
    assert '"Timestamp": int(marker.timestamp() * 1000)' in PUBLISHER_HANDLER
    assert "_week_window(invoked_at)" in PUBLISHER_HANDLER
    assert 'local.is_production ? "[..., event=\\"V2_LOAD_OK\\", feed]"' in MAIN_TF
    assert "TOLLCHAT_ENVIRONMENT = var.environment" in MAIN_TF
    assert "}, local.is_production ? {} : {" in publisher_lambda
    freshness_alarm = MAIN_TF.split(
        'resource "aws_cloudwatch_metric_alarm" "report_generation_freshness"',
        maxsplit=1,
    )[1].split('resource "aws_cloudwatch_metric_alarm" "publisher_errors"', 1)[0]
    assert "alarm_actions       = local.alarm_actions" in freshness_alarm
    assert (V2_ROOT / "scripts" / "build_publisher_zip.sh").exists()
    assert "./scripts/build_publisher_zip.sh" in VERIFY_SCRIPT
    assert (V2_ROOT / "scripts" / "build_timed_checks_zip.sh").exists()
    assert "./scripts/build_timed_checks_zip.sh" in VERIFY_SCRIPT

    publisher_invoke = terraform_block(
        MAIN_TF, 'resource "aws_lambda_function_event_invoke_config" "publisher"'
    )
    publisher_errors = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_metric_alarm" "publisher_errors"'
    )
    publisher_queue_alarms = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_metric_alarm" "publisher_failure_queues"'
    )
    assert_assignment(
        publisher_invoke, "function_name", "aws_lambda_function.publisher.function_name"
    )
    assert_assignment(
        publisher_invoke, "destination", "aws_sqs_queue.publisher_invoke_failure.arn"
    )
    assert_assignment(publisher_errors, "alarm_actions", "local.alarm_actions")
    assert_assignment(
        publisher_queue_alarms, "invoke", "aws_sqs_queue.publisher_invoke_failure"
    )
    assert_assignment(
        publisher_queue_alarms, "delivery", "aws_sqs_queue.publisher_delivery_failure"
    )
    assert_assignment(publisher_queue_alarms, "alarm_actions", "local.alarm_actions")


def test_report_publisher_scheduler_and_environment_contract() -> None:
    assert 'reader         = "pricing_reader"' in ENVIRONMENT_TF
    assert 'reader         = "pricing_reader_development"' in ENVIRONMENT_TF
    schedule = terraform_block(MAIN_TF, 'resource "aws_scheduler_schedule" "publisher"')
    assert MAIN_TF.count('resource "aws_scheduler_schedule" "publisher"') == 1
    for attribute, value in (
        ("arn", "aws_lambda_function.publisher.arn"),
        ("role_arn", "aws_iam_role.publisher_scheduler.arn"),
    ):
        assert_assignment(schedule, attribute, value)
    assert_assignment(schedule, "arn", "aws_sqs_queue.publisher_delivery_failure.arn")

    assume = MAIN_TF.split(
        'data "aws_iam_policy_document" "publisher_scheduler_assume"', maxsplit=1
    )[1].split('resource "aws_iam_role" "publisher_scheduler"', 1)[0]
    scheduler_role = terraform_block(
        MAIN_TF, 'resource "aws_iam_role" "publisher_scheduler"'
    )
    scheduler_role_policy = terraform_block(
        MAIN_TF, 'resource "aws_iam_role_policy" "publisher_scheduler"'
    )
    assert_assignment(assume, "actions", '["sts:AssumeRole"]')
    assert assume.count("principals {") == 1
    assert re.findall(r"identifiers\s*=\s*\[([^\]]+)\]", assume) == [
        '"scheduler.amazonaws.com"'
    ]
    assert_assignment(
        scheduler_role,
        "assume_role_policy",
        "data.aws_iam_policy_document.publisher_scheduler_assume.json",
    )
    assert_assignment(
        scheduler_role_policy, "role", "aws_iam_role.publisher_scheduler.id"
    )
    assert "policy = jsonencode({" in scheduler_role_policy
    assert 'data "aws_iam_policy_document" "publisher_scheduler"' not in MAIN_TF
    statements = re.findall(
        r"(?s)\{\n\s+Effect\s*=\s*\"Allow\"(.*?)\n\s+\},", scheduler_role_policy
    )
    assert len(statements) == 2
    assert [
        (
            re.findall(r'Action\s+=\s+"([^"]+)"', statement),
            re.findall(r"Resource\s+=\s+([^\n]+)", statement),
        )
        for statement in statements
    ] == [
        (["lambda:InvokeFunction"], ["aws_lambda_function.publisher.arn"]),
        (["sqs:SendMessage"], ["aws_sqs_queue.publisher_delivery_failure.arn"]),
    ]


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
