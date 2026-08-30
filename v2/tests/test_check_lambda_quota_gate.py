import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = "scripts/check_lambda_quota_gate.py"
type JsonObject = dict[str, Any]


def run(
    tmp_path: Path,
    account: JsonObject,
    resources: list[JsonObject],
    quota: str = "400",
) -> subprocess.CompletedProcess[str]:
    settings, plan = tmp_path / "settings.json", tmp_path / "plan.json"
    settings.write_text(json.dumps(account))
    plan.write_text(json.dumps({"resource_changes": resources}))
    return subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--account-settings",
            settings,
            "--plan",
            plan,
            "--quota",
            quota,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def function(before: JsonObject | None, after: JsonObject | None) -> JsonObject:
    return {"type": "aws_lambda_function", "change": {"before": before, "after": after}}


def provisioned(before: JsonObject | None, after: JsonObject | None) -> JsonObject:
    return {
        "type": "aws_lambda_provisioned_concurrency_config",
        "change": {"before": before, "after": after},
    }


def test_lambda_quota_gate_executes_overlap_and_decimal_quota(tmp_path: Path) -> None:
    account = {
        "AccountLimit": {
            "ConcurrentExecutions": 400,
            "UnreservedConcurrentExecutions": 378,
        }
    }
    resources = [
        function(
            {"function_name": "proxy", "reserved_concurrent_executions": 5},
            {"function_name": "proxy", "reserved_concurrent_executions": 7},
        ),
        provisioned(
            {"function_name": "proxy", "provisioned_concurrent_executions": 1},
            {"function_name": "proxy", "provisioned_concurrent_executions": 6},
        ),
    ]
    result = run(tmp_path, account, resources, "400.5")
    assert result.returncode == 0
    assert (
        result.stdout
        == "lambda_live=22 lambda_additions=2 lambda_quota=400.5 pass=true\n"
    )


def test_lambda_quota_gate_counts_each_function_increase_and_summed_provisioning(
    tmp_path: Path,
) -> None:
    account = {
        "AccountLimit": {
            "ConcurrentExecutions": 400,
            "UnreservedConcurrentExecutions": 378,
        }
    }
    resources = [
        function(
            {"function_name": "up", "reserved_concurrent_executions": 0},
            {"function_name": "up", "reserved_concurrent_executions": 10},
        ),
        function(
            {"function_name": "down", "reserved_concurrent_executions": 10},
            {"function_name": "down", "reserved_concurrent_executions": 0},
        ),
        function(
            {"function_name": "proxy", "reserved_concurrent_executions": 10},
            {"function_name": "proxy", "reserved_concurrent_executions": 10},
        ),
        provisioned(
            None, {"function_name": "proxy", "provisioned_concurrent_executions": 6}
        ),
        provisioned(
            None, {"function_name": "proxy", "provisioned_concurrent_executions": 6}
        ),
    ]
    result = run(tmp_path, account, resources)
    assert result.returncode == 0
    assert (
        result.stdout
        == "lambda_live=22 lambda_additions=12 lambda_quota=400 pass=true\n"
    )


def test_lambda_quota_gate_fails_closed(tmp_path: Path) -> None:
    valid = {
        "AccountLimit": {
            "ConcurrentExecutions": 400,
            "UnreservedConcurrentExecutions": 378,
        }
    }
    resource = [
        function(None, {"function_name": "proxy", "reserved_concurrent_executions": 5})
    ]
    for account, resources, quota in (
        ({"AccountLimit": {"ConcurrentExecutions": 400}}, resource, "400"),
        (valid, [function(None, {"function_name": "proxy"})], "400"),
        (valid, resource, "not-a-number"),
        (
            {
                "AccountLimit": {
                    "ConcurrentExecutions": 20,
                    "UnreservedConcurrentExecutions": 0,
                }
            },
            resource,
            "20",
        ),
    ):
        result = run(tmp_path, account, resources, quota)
        assert result.returncode != 0
        assert result.stdout == ""
