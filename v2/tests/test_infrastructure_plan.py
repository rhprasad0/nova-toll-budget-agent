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


def test_release_check_admits_only_what_the_gate_has_a_path_for() -> None:
    site = "aws_cloudfront_distribution.site"
    loader = "aws_lambda_function.loader"
    alarm = "aws_cloudwatch_metric_alarm.costs_errors"
    base: dict[str, dict[str, Any]] = {
        RUNTIME: {"environment_variables": {"A": "1"}},
        site: {"ordered_cache_behavior": [], "price_class": "PriceClass_100"},
        loader: {"timeout": 90},
    }

    def blocked(address: str, **fields: object) -> dict[str, set[str]]:
        head = {**base, address: {**base.get(address, {}), **fields}}
        return infrastructure_plan.blocked(base, head, set())

    # Both plans share their release inputs, so a slot difference is configuration.
    assert blocked(RUNTIME, environment_variables={"A": "2"})
    assert blocked(loader, timeout=900) == {loader: {"timeout"}}
    assert blocked(site, price_class="PriceClass_All") == {site: {"price_class"}}
    assert not blocked(site, ordered_cache_behavior=[{"path_pattern": "/costs.html"}])
    assert not blocked(alarm, threshold=1)
    assert infrastructure_plan.blocked(base, {}, set()).keys() == base.keys()


def test_administrator_entries_lapse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "applied"
    record.write_text(
        "# date approver address reason\n"
        "2026-11-01  Ryan  aws_wafv2_web_acl.public_chat  raise the limit\n"
        "2026-09-01  Ryan  aws_sns_topic.old  long merged\n"
        "2026-11-01  Ryan  aws_sns_topic.no_reason\n"
        "2099-01-01  Ryan  aws_sns_topic.future  never lapses\n"
        "Nov 1 2026  Ryan  aws_sns_topic.unparsed  not an ISO date\n"
    )
    monkeypatch.setattr(infrastructure_plan, "ADMINISTRATOR_APPLIED", record)

    assert infrastructure_plan.administrator_applied(date(2026, 11, 14)) == {
        "aws_wafv2_web_acl.public_chat"
    }
