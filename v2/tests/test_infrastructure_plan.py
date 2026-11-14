"""The credential-free plan, and the check that keeps shared-resource changes out of releases."""

import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from scripts import infrastructure_plan

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = 'aws_bedrockagentcore_agent_runtime.tollchat["green"]'


def test_release_check_blocks_the_rate_limit_change_that_stranded_delivery(
    tmp_path: Path, development_plan: dict[str, dict[str, Any]]
) -> None:
    """PR #697 passed every check, then delivery rejected it as phase_boundary."""
    (tmp_path / "v2").mkdir()
    shutil.copytree(
        ROOT / "v2/infra",
        tmp_path / "v2/infra",
        ignore=shutil.ignore_patterns(".terraform", "build"),
    )
    for name in ("v2/agent", "v2/analytics", "infra"):
        (tmp_path / name).symlink_to(ROOT / name, target_is_directory=True)
    environment = tmp_path / "v2/infra/environment.tf"
    source = environment.read_text()
    assert "local.is_production ? 20 : 10" in source
    environment.write_text(
        source.replace("local.is_production ? 20 : 10", "local.is_production ? 20 : 20")
    )
    changed = infrastructure_plan.planned(tmp_path)

    waf = "aws_wafv2_web_acl.public_chat"
    assert infrastructure_plan.blocked(development_plan, changed, set()) == {
        waf: {"rule"}
    }
    assert not infrastructure_plan.blocked(development_plan, changed, {waf})


def test_release_check_allows_only_the_fields_a_release_may_change() -> None:
    base = {RUNTIME: {"environment_variables": {"A": "1"}, "role_arn": "role"}}
    release = {RUNTIME: {"environment_variables": {"A": "2"}, "role_arn": "role"}}
    rewired = {RUNTIME: {"environment_variables": {"A": "1"}, "role_arn": "other"}}

    assert not infrastructure_plan.blocked(base, release, set())
    assert infrastructure_plan.blocked(base, rewired, set()) == {RUNTIME: {"role_arn"}}
    assert infrastructure_plan.blocked(base, {}, set()) == {RUNTIME: set(base[RUNTIME])}


def test_administrator_entries_lapse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "applied"
    record.write_text(
        "# date approver address reason\n"
        "2026-11-01  Ryan  aws_wafv2_web_acl.public_chat  raise the limit\n"
        "2026-09-01  Ryan  aws_sns_topic.old  long merged\n"
        "2026-11-01  Ryan  aws_sns_topic.no_reason\n"
    )
    monkeypatch.setattr(infrastructure_plan, "ADMINISTRATOR_APPLIED", record)

    assert infrastructure_plan.administrator_applied(date(2026, 11, 14)) == {
        "aws_wafv2_web_acl.public_chat"
    }
