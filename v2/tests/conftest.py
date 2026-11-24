"""Opt-in fixtures for the retained golden harness, never paid evaluation data."""

import json
import shutil
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY))

# GitHub's runners ship these; a bare image does not, and the tests that shell out
# to them fail far from the cause. Gitleaks, Docker and psql are optional: their
# tests skip. Terraform is not checked here, so one test file can run without it.
REQUIRED_TOOLS = ("jq", "xxd", "zip", "unzip")


def pytest_sessionstart(session: pytest.Session) -> None:
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        pytest.exit(
            f"Missing required tools: {', '.join(missing)}. See 'Verify the build' "
            "in v2/README.md.",
            returncode=2,
        )


@pytest.fixture(scope="session")
def development_plan() -> dict[str, dict[str, Any]]:
    """What v2/infra plans for development, by address, with mocked providers."""
    from scripts import infrastructure_plan

    if not shutil.which("terraform") or not infrastructure_plan.PROVIDERS.is_dir():
        pytest.skip("Run terraform -chdir=v2/infra init -backend=false")
    return infrastructure_plan.planned(infrastructure_plan.ROOT)


FOUNDATION_DEVELOPMENT_TEST = """
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\\"Version\\":\\"2012-10-17\\",\\"Statement\\":[]}" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "903859731897" }
  }
  mock_resource "aws_db_instance" {
    override_during = plan
    defaults = { address = "db.example", resource_id = "db-RESOURCE" }
  }
}
variables {
  environment               = "development"
  budget_notification_email = "budget@example.com"
  fetcher_package_path      = "tests/fetcher.zip"
  factory_dashboard_package_path = "tests/fetcher.zip"
  factory_alarm_app              = { client_id = "Iv23client", slug = "tollchat-alarms" }
}
run "development" {
  command = plan
}
"""


@pytest.fixture(scope="session")
def foundation_development_plan(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, dict[str, Any]]:
    """What root infra/ plans for development, by address, with mocked providers."""
    from scripts import infrastructure_plan

    if not shutil.which("terraform") or not infrastructure_plan.PROVIDERS.is_dir():
        pytest.skip("Run terraform -chdir=v2/infra init -backend=false")
    module = tmp_path_factory.mktemp("foundation") / "infra"
    shutil.copytree(
        infrastructure_plan.ROOT / "infra",
        module,
        ignore=shutil.ignore_patterns(".terraform", "build", "__pycache__"),
    )
    (module / "tests").mkdir()
    (module / "tests/fetcher.zip").write_bytes(b"placeholder")
    (module / "tests/development.tftest.hcl").write_text(FOUNDATION_DEVELOPMENT_TEST)
    shutil.copy(infrastructure_plan.ROOT / "v2/infra/.terraform.lock.hcl", module)
    (module / ".terraform").mkdir()
    (module / ".terraform/providers").symlink_to(
        infrastructure_plan.PROVIDERS, target_is_directory=True
    )
    result = subprocess.run(
        ["terraform", f"-chdir={module}", "test", "-json", "-verbose"],
        capture_output=True,
        text=True,
        check=False,
    )
    events = [
        json.loads(line) for line in result.stdout.splitlines() if line[:1] == "{"
    ]
    plans = [event["test_plan"] for event in events if event["type"] == "test_plan"]
    assert result.returncode == 0 and len(plans) == 1, [
        event["diagnostic"] for event in events if "diagnostic" in event
    ] or result.stderr
    return {
        item["address"]: item["change"]["after"]
        for item in plans[0]["resource_changes"]
    }


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item) -> Generator[None, Any]:
    """Show private-stage stderr logs when a test fails.

    run_private_stage.sh keeps a stage's stderr out of the workflow log by design,
    so a failing workflow-shell test otherwise reports only reason=unclassified.
    """
    report = (yield).get_result()
    tmp_path = getattr(item, "funcargs", {}).get("tmp_path")
    if report.when != "call" or not report.failed or tmp_path is None:
        return
    for log in sorted(tmp_path.rglob("*.err")):
        try:
            text = log.read_text(errors="replace").strip()
        except OSError:  # a directory or dangling link must not abort the session
            continue
        if text:
            report.sections.append((f"private stage stderr: {log.name}", text[-2000:]))
