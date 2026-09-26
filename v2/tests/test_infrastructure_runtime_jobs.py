import ast
import re

from tests.infrastructure_support import (
    APPLICATION_VARIABLES,
    CI_WORKFLOW,
    DEVELOPMENT_PLAN_WORKFLOW,
    DEVELOPMENT_TFVARS,
    ENVIRONMENT_TF,
    FOUNDATION_AGENTCORE,
    FOUNDATION_TRIGGERS,
    MAIN_TF,
    PRODUCTION_PLAN_WORKFLOW,
    PUBLISHER_HANDLER,
    TIMED_CHECKS_MODULE,
    TIMED_CHECKS_TF,
    V2_ROOT,
    assert_assignment,
    terraform_block,
)


def test_timed_lambda_scheduler_and_failure_contract() -> None:
    pairs = set(
        next(
            ast.literal_eval(node.value)
            for node in ast.parse(TIMED_CHECKS_MODULE).body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SCHEDULE_WINDOW_PAIRS"
            and node.value is not None
        )
    )
    entries = re.findall(
        r'"([^"]+)"\s*=\s*\{ schedule = "([^"]+)", expression = "([^"]+)", window_id = "([^"]+)" \}',
        TIMED_CHECKS_TF,
    )
    assert len(entries) == 28
    assert len({name for name, *_ in entries}) == 28
    assert {(schedule, window) for _, schedule, _, window in entries} == pairs
    weekdays = {"1": "MON", "2": "TUE", "3": "WED", "4": "THU", "5": "FRI", "6": "SAT"}
    for _, schedule, expression, _ in entries:
        minute, hour, _, _, weekday = schedule.split()
        assert expression == f"cron({minute} {hour} ? * {weekdays[weekday]} *)"

    lambda_block = terraform_block(
        TIMED_CHECKS_TF, 'resource "aws_lambda_function" "timed_checks"'
    )
    for name, value in (
        ("s3_bucket", "var.foundation.agentcore_artifacts_bucket_name"),
        ("s3_key", "aws_s3_object.timed_checks.key"),
        ("s3_object_version", "aws_s3_object.timed_checks.version_id"),
        ("source_code_hash", "local.timed_checks_zip_hash"),
        ("reserved_concurrent_executions", "1"),
    ):
        assert_assignment(lambda_block, name, value)
    assert "filename" not in lambda_block
    assert "subnet_ids         = local.private_subnets" in lambda_block
    assert (
        "TIMED_CHECK_ALERTS_ENABLED = tostring(local.timed_check_alerts_enabled)"
        in lambda_block
    )
    assert "ENVIRONMENT                = var.environment" in lambda_block
    assert "ALERTS_TOPIC_ARN = var.foundation.alerts_topic_arn" in lambda_block
    assert 'data "aws_kms_alias" "alerts"' in TIMED_CHECKS_TF
    assert 'name = "alias/nova-toll-alerts"' in TIMED_CHECKS_TF

    schedule = terraform_block(
        TIMED_CHECKS_TF, 'resource "aws_scheduler_schedule" "timed_checks"'
    )
    assert_assignment(schedule, "for_each", "local.timed_check_schedules")
    assert_assignment(schedule, "state", '"ENABLED"')
    assert_assignment(schedule, "schedule_expression_timezone", '"America/New_York"')
    assert_assignment(schedule, "mode", '"OFF"')
    assert "window_id = each.value.window_id" in schedule
    assert "schedule  = each.value.schedule" in schedule
    assert schedule.count("maximum_retry_attempts       = 0") == 1
    assert schedule.count("maximum_event_age_in_seconds = 600") == 1

    invoke = terraform_block(
        TIMED_CHECKS_TF,
        'resource "aws_lambda_function_event_invoke_config" "timed_checks"',
    )
    assert_assignment(invoke, "maximum_retry_attempts", "0")
    assert_assignment(invoke, "maximum_event_age_in_seconds", "600")
    for queue_name in ("timed_checks_invoke_failure", "timed_checks_delivery_failure"):
        queue = terraform_block(
            TIMED_CHECKS_TF, f'resource "aws_sqs_queue" "{queue_name}"'
        )
        assert_assignment(queue, "sqs_managed_sse_enabled", "true")
        assert_assignment(queue, "message_retention_seconds", "1209600")
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
        'data "aws_iam_policy_document" "timed_checks_lambda"',
    )
    assert 'actions   = ["rds:DescribeDBInstances"]' in lambda_policy
    assert 'actions = ["rds-db:connect"]' in lambda_policy
    assert "/${local.database_roles.agent}" in lambda_policy
    assert "/${local.database_roles.pricing_caller}" in lambda_policy
    assert 'actions   = ["ssm:GetParameter"]' in lambda_policy
    assert 'actions   = ["sqs:SendMessage"]' in lambda_policy
    assert 'actions   = ["sns:Publish"]' in lambda_policy
    assert "resources = [var.foundation.alerts_topic_arn]" in lambda_policy
    assert 'actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]' in lambda_policy
    assert "resources = [data.aws_kms_alias.alerts.target_key_arn]" in lambda_policy
    assert 'resources = ["*"]' not in lambda_policy
    assert (
        "local.is_production || var.enable_development_timed_check_alerts"
        in TIMED_CHECKS_TF
    )
    assert 'variable "enable_development_timed_check_alerts"' in APPLICATION_VARIABLES
    assert "default     = false" in APPLICATION_VARIABLES
    assert (
        'var.environment == "development" || !var.enable_development_timed_check_alerts'
        in APPLICATION_VARIABLES
    )
    assert "enable_development_timed_check_alerts = true" in DEVELOPMENT_TFVARS.replace(
        "      ", " "
    )
    errors_alarm = terraform_block(
        TIMED_CHECKS_TF, 'resource "aws_cloudwatch_metric_alarm" "timed_checks_errors"'
    )
    assert (
        "Unexpected timed-check failures and evaluation alert delivery failures"
        in errors_alarm
    )

    assert 'cidr_ipv4         = "0.0.0.0/0"' in TIMED_CHECKS_TF
    assert "from_port         = 443" in TIMED_CHECKS_TF
    assert "to_port           = 443" in TIMED_CHECKS_TF
    assert "from_port                    = 5432" in TIMED_CHECKS_TF
    assert "to_port                      = 5432" in TIMED_CHECKS_TF
    assert 'ip_protocol = "-1"' not in TIMED_CHECKS_TF


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
    raw_rule = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_event_rule" "raw_objects"'
    )
    loader_target = terraform_block(
        MAIN_TF, 'resource "aws_cloudwatch_event_target" "loader"'
    )
    loader_permission = terraform_block(
        MAIN_TF, 'resource "aws_lambda_permission" "eventbridge_invoke"'
    )
    loader_invoke = terraform_block(
        MAIN_TF, 'resource "aws_lambda_function_event_invoke_config" "loader"'
    )
    loader_invoke_queue = terraform_block(
        MAIN_TF, 'resource "aws_sqs_queue" "invoke_failure"'
    )
    loader_delivery_queue = terraform_block(
        MAIN_TF, 'resource "aws_sqs_queue" "delivery_failure"'
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
    assert_assignment(raw_rule, "source", '["aws.s3"]')
    assert_assignment(raw_rule, "detail-type", '["Object Created"]')
    assert '{ prefix = "raw/feed=i95/" }' in raw_rule
    assert '{ prefix = "raw/feed=i66/" }' in raw_rule
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
    assert_assignment(loader_target, "maximum_event_age_in_seconds", "86400")
    assert_assignment(loader_target, "maximum_retry_attempts", "185")
    assert_assignment(loader_target, "arn", "aws_sqs_queue.delivery_failure.arn")
    assert_assignment(
        loader_invoke, "function_name", "aws_lambda_function.loader.function_name"
    )
    assert_assignment(loader_invoke, "maximum_retry_attempts", "2")
    assert_assignment(loader_invoke, "maximum_event_age_in_seconds", "21600")
    assert_assignment(loader_invoke, "destination", "aws_sqs_queue.invoke_failure.arn")
    for queue in (loader_invoke_queue, loader_delivery_queue):
        assert_assignment(queue, "sqs_managed_sse_enabled", "true")
        assert_assignment(queue, "message_retention_seconds", "1209600")
    assert_assignment(
        loader_delivery_policy, "resources", "[aws_sqs_queue.delivery_failure.arn]"
    )
    assert_assignment(loader_delivery_policy, "identifiers", '["events.amazonaws.com"]')
    assert_assignment(
        loader_delivery_policy, "values", "[aws_cloudwatch_event_rule.raw_objects.arn]"
    )
    for alarm in (loader_error_alarm, loader_freshness_alarm, loader_failure_alarms):
        assert_assignment(alarm, "alarm_actions", "local.alarm_actions")
    assert_assignment(loader_error_alarm, "namespace", '"AWS/Lambda"')
    assert_assignment(loader_error_alarm, "metric_name", '"Errors"')
    assert_assignment(
        loader_error_alarm,
        "dimensions",
        "{ FunctionName = aws_lambda_function.loader.function_name }",
    )
    assert_assignment(loader_error_alarm, "statistic", '"Sum"')
    assert_assignment(loader_error_alarm, "period", "300")
    assert_assignment(loader_error_alarm, "evaluation_periods", "1")
    assert_assignment(loader_error_alarm, "threshold", "1")
    assert_assignment(
        loader_error_alarm, "comparison_operator", '"GreaterThanOrEqualToThreshold"'
    )
    assert_assignment(loader_error_alarm, "treat_missing_data", '"notBreaching"')
    assert_assignment(loader_freshness_alarm, "namespace", '"NovaToll"')
    assert_assignment(loader_freshness_alarm, "metric_name", '"V2LoadSuccess"')
    assert_assignment(
        loader_freshness_alarm,
        "dimensions",
        "local.is_production ? { feed = each.key } : { feed = each.key, Environment = var.environment }",
    )
    assert_assignment(loader_freshness_alarm, "statistic", '"Sum"')
    assert_assignment(loader_freshness_alarm, "period", "600")
    assert_assignment(loader_freshness_alarm, "evaluation_periods", "3")
    assert_assignment(loader_freshness_alarm, "threshold", "1")
    assert_assignment(
        loader_freshness_alarm, "comparison_operator", '"LessThanThreshold"'
    )
    assert_assignment(loader_freshness_alarm, "treat_missing_data", '"breaching"')
    assert_assignment(loader_failure_alarms, "invoke", "aws_sqs_queue.invoke_failure")
    assert_assignment(
        loader_failure_alarms, "delivery", "aws_sqs_queue.delivery_failure"
    )
    assert_assignment(loader_failure_alarms, "namespace", '"AWS/SQS"')
    assert_assignment(
        loader_failure_alarms, "metric_name", '"ApproximateNumberOfMessagesVisible"'
    )
    assert_assignment(
        loader_failure_alarms, "dimensions", "{ QueueName = each.value.name }"
    )
    assert_assignment(loader_failure_alarms, "statistic", '"Maximum"')
    assert_assignment(loader_failure_alarms, "period", "300")
    assert_assignment(loader_failure_alarms, "evaluation_periods", "1")
    assert_assignment(loader_failure_alarms, "threshold", "1")
    assert_assignment(
        loader_failure_alarms,
        "comparison_operator",
        '"GreaterThanOrEqualToThreshold"',
    )
    assert_assignment(loader_failure_alarms, "treat_missing_data", '"notBreaching"')
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
    assert 'resource "aws_vpc_security_group_egress_rule" "loader_to_rds"' in MAIN_TF
    assert 'resource "aws_vpc_security_group_egress_rule" "loader_to_s3"' in MAIN_TF


def test_report_publisher_is_weekly_bounded_and_least_privilege() -> None:
    variables = (V2_ROOT / "infra" / "variables.tf").read_text()
    assert 'variable "publisher_package_path"' in variables
    assert 'function_name = "toll-v2-report-publisher${local.suffix}"' in MAIN_TF
    assert 'resource "aws_vpc_security_group_egress_rule" "publisher_to_rds"' in MAIN_TF
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
    assert 'resource "aws_vpc_security_group_egress_rule" "publisher_to_s3"' in MAIN_TF
    publisher_lambda = MAIN_TF.split(
        'resource "aws_lambda_function" "publisher"', maxsplit=1
    )[1].split(
        'resource "aws_lambda_function_event_invoke_config" "publisher"', maxsplit=1
    )[0]
    assert "timeout       = 900" in publisher_lambda
    assert "memory_size   = 2048" in publisher_lambda
    assert re.search(r"DB_USER\s+= local.database_roles.publisher", publisher_lambda)
    assert re.search(
        r"DB_READER_USER\s+= local.database_roles.reader", publisher_lambda
    )
    assert 'REPORT_PUBLICATION_ENABLED = "true"' in publisher_lambda
    assert "SITE_BUCKET_NAME           = aws_s3_bucket.site.id" in publisher_lambda
    assert "reserved_concurrent_executions = 1" in publisher_lambda
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
    assert "PUBLIC_BASE_URL      = local.public_site_url" in publisher_lambda
    freshness_alarm = MAIN_TF.split(
        'resource "aws_cloudwatch_metric_alarm" "report_generation_freshness"',
        maxsplit=1,
    )[1].split('resource "aws_cloudwatch_metric_alarm" "publisher_errors"', 1)[0]
    assert "trailing seven-day sliding window" in freshness_alarm
    assert (
        'alarm_name          = "toll-v2-report-generation-freshness${local.suffix}"'
        in freshness_alarm
    )
    assert 'namespace           = "NovaToll"' in freshness_alarm
    assert 'metric_name         = "V2ReportGenerationSuccess"' in freshness_alarm
    assert "period              = 86400" in freshness_alarm
    assert "evaluation_periods  = 7" in freshness_alarm
    assert "datapoints_to_alarm = 7" in freshness_alarm
    assert 'statistic           = "Sum"' in freshness_alarm
    assert "threshold           = 1" in freshness_alarm
    assert 'comparison_operator = "LessThanThreshold"' in freshness_alarm
    assert 'treat_missing_data  = "breaching"' in freshness_alarm
    assert 'facility_scope = "both"' in freshness_alarm
    assert "Environment = var.environment" in freshness_alarm
    assert "alarm_actions       = local.alarm_actions" in freshness_alarm
    assert (V2_ROOT / "scripts" / "build_publisher_zip.sh").exists()
    assert "./scripts/build_publisher_zip.sh" in CI_WORKFLOW
    assert (V2_ROOT / "scripts" / "build_timed_checks_zip.sh").exists()
    assert "./scripts/build_timed_checks_zip.sh" in CI_WORKFLOW

    publisher_invoke = terraform_block(
        MAIN_TF, 'resource "aws_lambda_function_event_invoke_config" "publisher"'
    )
    publisher_invoke_queue = terraform_block(
        MAIN_TF, 'resource "aws_sqs_queue" "publisher_invoke_failure"'
    )
    publisher_delivery_queue = terraform_block(
        MAIN_TF, 'resource "aws_sqs_queue" "publisher_delivery_failure"'
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
    assert_assignment(publisher_invoke, "maximum_retry_attempts", "2")
    assert_assignment(publisher_invoke, "maximum_event_age_in_seconds", "21600")
    assert_assignment(
        publisher_invoke, "destination", "aws_sqs_queue.publisher_invoke_failure.arn"
    )
    for queue in (publisher_invoke_queue, publisher_delivery_queue):
        assert_assignment(queue, "sqs_managed_sse_enabled", "true")
        assert_assignment(queue, "message_retention_seconds", "1209600")
    assert_assignment(publisher_errors, "namespace", '"AWS/Lambda"')
    assert_assignment(publisher_errors, "metric_name", '"Errors"')
    assert_assignment(
        publisher_errors,
        "dimensions",
        "{ FunctionName = aws_lambda_function.publisher.function_name }",
    )
    assert_assignment(publisher_errors, "statistic", '"Sum"')
    assert_assignment(publisher_errors, "period", "300")
    assert_assignment(publisher_errors, "evaluation_periods", "1")
    assert_assignment(publisher_errors, "threshold", "1")
    assert_assignment(
        publisher_errors, "comparison_operator", '"GreaterThanOrEqualToThreshold"'
    )
    assert_assignment(publisher_errors, "treat_missing_data", '"notBreaching"')
    assert_assignment(publisher_errors, "alarm_actions", "local.alarm_actions")
    assert_assignment(
        publisher_queue_alarms, "invoke", "aws_sqs_queue.publisher_invoke_failure"
    )
    assert_assignment(
        publisher_queue_alarms, "delivery", "aws_sqs_queue.publisher_delivery_failure"
    )
    assert_assignment(publisher_queue_alarms, "namespace", '"AWS/SQS"')
    assert_assignment(
        publisher_queue_alarms, "metric_name", '"ApproximateNumberOfMessagesVisible"'
    )
    assert_assignment(
        publisher_queue_alarms, "dimensions", "{ QueueName = each.value.name }"
    )
    assert_assignment(publisher_queue_alarms, "statistic", '"Maximum"')
    assert_assignment(publisher_queue_alarms, "period", "300")
    assert_assignment(publisher_queue_alarms, "evaluation_periods", "1")
    assert_assignment(publisher_queue_alarms, "threshold", "1")
    assert_assignment(
        publisher_queue_alarms, "comparison_operator", '"GreaterThanOrEqualToThreshold"'
    )
    assert_assignment(publisher_queue_alarms, "treat_missing_data", '"notBreaching"')
    assert_assignment(publisher_queue_alarms, "alarm_actions", "local.alarm_actions")


def test_report_publisher_scheduler_and_environment_contract() -> None:
    assert 'reader         = "pricing_reader"' in ENVIRONMENT_TF
    assert 'reader         = "pricing_reader_development"' in ENVIRONMENT_TF
    schedule = terraform_block(MAIN_TF, 'resource "aws_scheduler_schedule" "publisher"')
    assert MAIN_TF.count('resource "aws_scheduler_schedule" "publisher"') == 1
    for attribute, value in (
        ("schedule_expression", '"cron(0 1 ? * MON *)"'),
        ("schedule_expression_timezone", '"America/New_York"'),
        ("arn", "aws_lambda_function.publisher.arn"),
        ("role_arn", "aws_iam_role.publisher_scheduler.arn"),
        ("input", 'jsonencode({ trigger = "watchdog" })'),
        ("maximum_retry_attempts", "2"),
        ("maximum_event_age_in_seconds", "3600"),
    ):
        assert_assignment(schedule, attribute, value)
    assert_assignment(schedule, "mode", '"OFF"')
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
    for obsolete in (
        'resource "aws_cloudwatch_event_rule" "committed_i95_loads"',
        'resource "aws_cloudwatch_event_rule" "report_watchdog"',
        'resource "aws_cloudwatch_event_target" "publisher_load_event"',
        'resource "aws_cloudwatch_event_target" "publisher_watchdog"',
        'resource "aws_lambda_permission" "publisher_load_event"',
        'resource "aws_lambda_permission" "publisher_watchdog"',
        'resource "aws_sqs_queue_policy" "publisher_delivery_failure"',
        'resource "aws_cloudwatch_metric_alarm" "publisher_failed_invocations"',
    ):
        assert obsolete not in MAIN_TF


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
