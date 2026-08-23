import re
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = V2_ROOT.parent
MAIN_TF = (V2_ROOT / "infra" / "main.tf").read_text()
CI_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
TIMED_CHECKS_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-timed-checks.yml"
).read_text()
TIMED_SCHEDULE_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-timed-schedule.yml"
).read_text()
TIMED_ROUTE_TEST = (V2_ROOT / "tests" / "test_validate_toll_route_live.py").read_text()
TIMED_BALLPARK_TEST = (
    V2_ROOT / "tests" / "test_get_annual_toll_ballpark_live.py"
).read_text()
VERSIONS_TF = (V2_ROOT / "infra" / "versions.tf").read_text()
V1_TRIGGERS = (REPO_ROOT / "v1" / "infra" / "triggers.tf").read_text()
V1_LAMBDA = (REPO_ROOT / "v1" / "infra" / "lambda.tf").read_text()
V1_IAM = (REPO_ROOT / "v1" / "infra" / "iam.tf").read_text()
V1_AGENTCORE = (REPO_ROOT / "v1" / "infra" / "agentcore.tf").read_text()


def test_v1_loader_is_retired_but_eventbridge_remains():
    notification = V1_TRIGGERS.split(
        'resource "aws_s3_bucket_notification" "raw"', maxsplit=1
    )[1]
    assert "eventbridge = true" in notification
    assert "lambda_function" not in notification
    assert 'resource "aws_lambda_permission" "s3_invoke_loader"' not in V1_TRIGGERS
    assert 'resource "aws_lambda_function" "loader"' not in V1_LAMBDA


def test_v1_site_and_terraform_ci_are_removed():
    assert not (REPO_ROOT / "v1" / "infra" / "site.tf").exists()
    assert not (REPO_ROOT / ".github" / "workflows" / "terraform.yml").exists()
    assert 'resource "aws_iam_role" "terraform_apply"' not in V1_IAM
    assert 'resource "aws_iam_role" "github_ci"' not in V1_IAM


def test_shared_dynamodb_endpoint_admits_v2_session_table():
    endpoint = V1_AGENTCORE.split('resource "aws_vpc_endpoint" "dynamodb"', maxsplit=1)[
        1
    ].split('resource "aws_s3_bucket" "agentcore_artifacts"', maxsplit=1)[0]
    assert "tollchat-v2-anonymous-sessions" in endpoint
    assert "table/tollchat-anonymous-sessions" not in endpoint
    assert "dynamodb:*" not in endpoint


def test_v2_has_an_independent_state_and_identity():
    assert 'key          = "nova-toll/v2/terraform.tfstate"' in VERSIONS_TF
    assert 'function_name = "toll-v2-pricing-loader"' in MAIN_TF
    assert "/pricing_loader_writer" in MAIN_TF
    assert 'DB_USER    = "pricing_loader_writer"' in MAIN_TF


def test_v2_declares_a_private_agentcore_application_without_telemetry():
    agentcore_path = V2_ROOT / "infra" / "agentcore.tf"
    assert agentcore_path.exists()
    agentcore = agentcore_path.read_text()
    assert 'agent_runtime_name = "nova_toll_v2"' in agentcore
    assert 'network_mode = "VPC"' in agentcore
    assert "dbuser:${data.aws_db_instance.main.resource_id}/tollchat_agent" in agentcore
    assert "dbuser:${data.aws_db_instance.main.resource_id}/pricing_caller" in agentcore
    assert 'function_name                  = "tollchat-v2-chat-proxy"' in agentcore
    assert 'name         = "tollchat-v2-anonymous-sessions"' in agentcore
    assert 'types            = ["PRIVATE"]' in agentcore
    assert 'response_transfer_mode  = "STREAM"' in agentcore
    assert "DenyOutsidePrivateEndpoint" in agentcore
    assert (
        'resource "aws_vpc_security_group_ingress_rule" "agentcore_from_proxy"'
        in agentcore
    )
    assert "aws_cloudfront" not in agentcore
    assert "cloudflare" not in agentcore
    assert "aws_acm" not in agentcore
    assert "opentelemetry" not in agentcore.lower()
    assert "xray" not in agentcore.lower()
    assert "TOLLCHAT_TRACE_LOG_GROUP" not in agentcore
    assert "github_pat_[A-Za-z0-9_-]{20,}" in agentcore


def test_v2_agent_packages_are_required_for_real_deployments():
    variables = (V2_ROOT / "infra" / "variables.tf").read_text()
    agentcore = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    build = V2_ROOT / "scripts" / "build_agentcore_zips.sh"
    assert 'variable "agentcore_package_path"' in variables
    assert 'variable "chat_proxy_package_path"' in variables
    assert "AgentCore deployment requires the reviewed v2 runtime package" in agentcore
    assert "Chat proxy deployment requires the reviewed v2 proxy package" in agentcore
    assert build.exists()


def test_eventbridge_has_both_failure_paths_and_bounded_retries():
    assert 'detail-type = ["Object Created"]' in MAIN_TF
    assert '{ prefix = "raw/feed=i95/" }' in MAIN_TF
    assert '{ prefix = "raw/feed=i66/" }' in MAIN_TF
    assert "maximum_event_age_in_seconds = 86400" in MAIN_TF
    assert "maximum_retry_attempts       = 185" in MAIN_TF
    assert 'resource "aws_sqs_queue" "invoke_failure"' in MAIN_TF
    assert 'resource "aws_sqs_queue" "delivery_failure"' in MAIN_TF


def test_loader_network_and_data_access_are_scoped():
    assert "${data.aws_s3_bucket.raw.arn}/*" not in MAIN_TF
    assert '"${data.aws_s3_bucket.raw.arn}/raw/feed=i95/*"' in MAIN_TF
    assert '"${data.aws_s3_bucket.raw.arn}/raw/feed=i66/*"' in MAIN_TF
    assert 'resource "aws_vpc_security_group_egress_rule" "loader_to_rds"' in MAIN_TF
    assert 'resource "aws_vpc_security_group_egress_rule" "loader_to_s3"' in MAIN_TF


def test_timed_ci_uses_the_internal_pricing_caller():
    policy = MAIN_TF.split('data "aws_iam_policy_document" "timed_checks"', maxsplit=1)[
        1
    ].split('resource "aws_iam_role_policy" "timed_checks"', maxsplit=1)[0]

    assert 'name               = "nova-toll-v2-timed-checks"' in MAIN_TF
    assert 'actions   = ["rds:DescribeDBInstances"]' in policy
    assert 'actions   = ["rds-db:connect"]' in policy
    assert "/pricing_caller" in policy
    assert "/tollchat_agent" not in policy
    assert 'actions   = ["ssm:GetParameter"]' in policy
    assert (
        'resources = ["arn:aws:ssm:${data.aws_region.current.region}:'
        "${data.aws_caller_identity.current.account_id}:parameter/nova-toll/"
        'openai_api_key"]'
    ) in policy
    assert "ssm:GetParameters" not in policy
    assert "/pricing_reader" not in policy
    assert "role/nova-toll-v2-timed-checks" in TIMED_CHECKS_WORKFLOW
    assert "role/nova-toll-github-ci" not in TIMED_CHECKS_WORKFLOW


def test_timed_ci_skips_stale_scheduled_runs():
    schedules = re.findall(r'cron: "([^"]+)"', TIMED_SCHEDULE_WORKFLOW)
    assert all(schedule.split()[-1].isdigit() for schedule in schedules)
    assert "schedule: ${{ github.event.schedule || '' }}" in TIMED_SCHEDULE_WORKFLOW
    assert "TIMED_SCHEDULE: ${{ inputs.schedule }}" in TIMED_CHECKS_WORKFLOW
    assert 'python3 scripts/check_timed_window.py "$TIMED_SCHEDULE"' in (
        TIMED_CHECKS_WORKFLOW
    )


def test_timed_ci_checks_agent_pricing_tool_in_every_i95_state():
    for window_id in ("i95_northbound", "i95_reversal", "i95_southbound"):
        assert f"- {window_id}" in TIMED_SCHEDULE_WORKFLOW
        assert f'window_id="{window_id}"' in TIMED_SCHEDULE_WORKFLOW
        assert f'"{window_id}":' in TIMED_ROUTE_TEST

    assert "tests/test_validate_toll_route_live.py" in TIMED_CHECKS_WORKFLOW
    assert "tests/test_get_annual_toll_ballpark_live.py" in TIMED_CHECKS_WORKFLOW
    assert "get_current_toll_price" in TIMED_ROUTE_TEST
    assert "get_annual_toll_ballpark" in TIMED_BALLPARK_TEST
    assert "route_validation.validate_toll_route" not in TIMED_ROUTE_TEST
    assert "eval/run_evaluation.py --check" in CI_WORKFLOW
    assert 'if [[ "$TIMED_WINDOW_ID" == i95_* ]]' in TIMED_CHECKS_WORKFLOW
    assert 'eval/run_evaluation.py --window "$TIMED_WINDOW_ID"' in TIMED_CHECKS_WORKFLOW
    assert "TollChat junction evaluation" in TIMED_CHECKS_WORKFLOW
    assert "test_live_i95_northbound_restart_is_state_independent" in TIMED_ROUTE_TEST
    assert "OPENAI_API_KEY" not in TIMED_CHECKS_WORKFLOW


def test_timed_ci_covers_three_real_i95_states_monday_through_saturday():
    expected = {
        1: {
            "i95_northbound": "17 6",
            "i95_reversal": "17 11",
            "i95_southbound": "17 14",
        },
        2: {
            "i95_northbound": "17 6",
            "i95_reversal": "47 1",
            "i95_southbound": "17 14",
        },
        3: {
            "i95_northbound": "17 6",
            "i95_reversal": "47 1",
            "i95_southbound": "17 14",
        },
        4: {
            "i95_northbound": "17 6",
            "i95_reversal": "47 1",
            "i95_southbound": "17 14",
        },
        5: {
            "i95_northbound": "17 6",
            "i95_reversal": "47 1",
            "i95_southbound": "17 14",
        },
        6: {
            "i95_northbound": "17 18",
            "i95_reversal": "17 15",
            "i95_southbound": "17 10",
        },
    }

    for weekday, windows in expected.items():
        schedules = [f"{clock} * * {weekday}" for clock in windows.values()]
        assert len(schedules) == len(set(schedules)) == 3
        for schedule in schedules:
            assert TIMED_SCHEDULE_WORKFLOW.count(f'cron: "{schedule}"') == 1
        for window_id, clock in windows.items():
            schedule = f"{clock} * * {weekday}"
            assert re.search(
                rf'^.*"{re.escape(schedule)}".*window_id="{window_id}"',
                TIMED_SCHEDULE_WORKFLOW,
                re.MULTILINE,
            )

    assert not re.search(r'cron: "[^\"]+ \* \* 0"', TIMED_SCHEDULE_WORKFLOW)


def test_timed_ci_checks_both_greenway_peak_windows():
    for window_id in ("greenway_eb_peak", "greenway_wb_peak"):
        assert f"- {window_id}" in TIMED_SCHEDULE_WORKFLOW
        assert f'window_id="{window_id}"' in TIMED_SCHEDULE_WORKFLOW
        assert f'"{window_id}":' in TIMED_ROUTE_TEST

    for weekday in range(1, 6):
        assert f'cron: "23 7 * * {weekday}"' in TIMED_SCHEDULE_WORKFLOW
        assert f'cron: "23 17 * * {weekday}"' in TIMED_SCHEDULE_WORKFLOW

    assert "test_live_greenway_peak_price" in TIMED_ROUTE_TEST
    assert "if: startsWith(inputs.window_id, 'i95_')" not in TIMED_CHECKS_WORKFLOW
