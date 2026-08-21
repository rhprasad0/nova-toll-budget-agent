import re
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = V2_ROOT.parent
MAIN_TF = (V2_ROOT / "infra" / "main.tf").read_text()
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


def test_v1_direct_notification_and_eventbridge_coexist():
    notification = V1_TRIGGERS.split(
        'resource "aws_s3_bucket_notification" "raw"', maxsplit=1
    )[1]
    assert "eventbridge = true" in notification
    assert "lambda_function_arn = aws_lambda_function.loader.arn" in notification


def test_v2_has_an_independent_state_and_identity():
    assert 'key          = "nova-toll/v2/terraform.tfstate"' in VERSIONS_TF
    assert 'function_name = "toll-v2-pricing-loader"' in MAIN_TF
    assert "/pricing_loader_writer" in MAIN_TF
    assert 'DB_USER    = "pricing_loader_writer"' in MAIN_TF


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
    assert "ssm:" not in policy
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
