from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "drill_kill_switch", ROOT / "scripts" / "drill_kill_switch.py"
)
assert SPEC and SPEC.loader
drill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(drill)


def _healthy_preflight() -> dict[str, object]:
    return {
        "account": "920534282028",
        "concurrency": 5,
        "lambda_state": "Active",
        "lambda_update": "Successful",
        "db_status": "available",
        "alarms": {name: "OK" for name in drill.ALARMS},
        "config_status": 200,
        "rds_ok": True,
        "artifacts_ok": True,
        "terraform_clean": True,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account", "407645373626"),
        ("concurrency", 0),
        ("concurrency", 4),
        ("lambda_state", "Failed"),
        ("lambda_update", "Failed"),
        ("db_status", "rebooting"),
        ("config_status", 503),
        ("rds_ok", False),
        ("artifacts_ok", False),
        ("terraform_clean", False),
    ],
)
def test_preflight_fails_closed(field: str, value: object):
    state = _healthy_preflight()
    state[field] = value

    with pytest.raises(drill.DrillError, match="preflight failed"):
        drill.validate_preflight(state)


def test_preflight_rejects_any_unhealthy_alarm():
    state = _healthy_preflight()
    state["alarms"][drill.ALARMS[0]] = "ALARM"

    with pytest.raises(drill.DrillError, match="preflight failed"):
        drill.validate_preflight(state)


def test_live_run_requires_explicit_owner_approval(monkeypatch):
    changed: list[int] = []
    monkeypatch.setattr(drill, "_preflight", lambda: _healthy_preflight())
    monkeypatch.setattr(drill, "_put_concurrency", changed.append)

    with pytest.raises(drill.DrillError, match="owner approval"):
        drill.run(execute=True, approved_by=None, pause_for_screenshot=False)

    assert changed == []


def test_subprocess_environment_pins_profile_and_drops_ambient_credentials(
    monkeypatch,
):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ambient")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "ambient")

    env = drill._environment()

    assert env["AWS_PROFILE"] == "nova-toll"
    assert env["AWS_DEFAULT_PROFILE"] == "nova-toll"
    assert env["AWS_REGION"] == "us-east-1"
    assert not drill._AMBIENT_AWS_CREDENTIALS & env.keys()


@pytest.mark.parametrize(
    "failure",
    [
        "routes",
        "agentcore",
        "pipeline",
        "terraform",
    ],
)
def test_every_engaged_failure_restores_baseline(monkeypatch, failure: str):
    concurrency = 5
    restored: list[int] = []
    monkeypatch.setattr(drill, "_preflight", lambda: _healthy_preflight())

    def put(value: int) -> None:
        nonlocal concurrency
        concurrency = value

    monkeypatch.setattr(drill, "_put_concurrency", put)
    monkeypatch.setattr(drill, "_get_concurrency", lambda: concurrency)
    monkeypatch.setattr(
        drill,
        "_restore_concurrency",
        lambda baseline: (restored.append(baseline), put(baseline)),
    )
    for name in ("routes", "agentcore", "pipeline", "terraform"):
        monkeypatch.setattr(
            drill,
            f"_prove_{name}",
            (lambda: (_ for _ in ()).throw(drill.DrillError("expected failure")))
            if name == failure
            else (lambda: None),
        )

    with pytest.raises(drill.DrillError, match="expected failure"):
        drill.run(execute=True, approved_by="Ryan", pause_for_screenshot=False)

    assert restored == [5]
    assert concurrency == 5


def test_ambiguous_concurrency_update_failure_still_restores(monkeypatch):
    restored: list[int] = []
    monkeypatch.setattr(drill, "_preflight", lambda: _healthy_preflight())
    monkeypatch.setattr(
        drill,
        "_put_concurrency",
        lambda _value: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("aws lambda", 120)
        ),
    )
    monkeypatch.setattr(drill, "_restore_concurrency", restored.append)

    with pytest.raises(subprocess.TimeoutExpired):
        drill.run(execute=True, approved_by="Ryan", pause_for_screenshot=False)

    assert restored == [5]


@pytest.mark.parametrize("statuses", [(200, 500), (403, 500), (500, 429)])
def test_blocked_routes_require_integration_failures(statuses: tuple[int, int]):
    with pytest.raises(drill.DrillError, match="integration"):
        drill.validate_blocked_statuses(statuses)


def test_blocked_routes_accept_server_side_failures():
    drill.validate_blocked_statuses((500, 502))


def test_success_restores_then_runs_canonical_smoke(monkeypatch):
    concurrency = 5
    order: list[str] = []
    monkeypatch.setattr(drill, "_preflight", lambda: _healthy_preflight())

    def put(value: int) -> None:
        nonlocal concurrency
        concurrency = value
        order.append(f"concurrency:{value}")

    monkeypatch.setattr(drill, "_put_concurrency", put)
    monkeypatch.setattr(drill, "_get_concurrency", lambda: concurrency)
    monkeypatch.setattr(
        drill,
        "_restore_concurrency",
        lambda baseline: put(baseline),
    )
    for name in ("routes", "agentcore", "pipeline", "terraform"):
        monkeypatch.setattr(
            drill, f"_prove_{name}", lambda name=name: order.append(name)
        )
    monkeypatch.setattr(
        drill,
        "_canonical_smoke",
        lambda: (order.append("canonical"), {"status": "passed"})[1],
    )
    monkeypatch.setattr(drill, "_now", lambda: 100.0)

    report = drill.run(execute=True, approved_by="Ryan", pause_for_screenshot=False)

    assert order == [
        "concurrency:0",
        "routes",
        "pipeline",
        "terraform",
        "agentcore",
        "concurrency:5",
        "canonical",
    ]
    assert report["status"] == "passed"
    assert report["checks"]["canonical_recovery"] is True


def test_agentcore_query_uses_the_parsed_stage_field():
    assert drill.AGENTCORE_COUNT_QUERY == (
        'filter stage = "invoke" | stats count() as count'
    )


def test_controlled_fetcher_rejects_handler_failure(monkeypatch, tmp_path):
    output = tmp_path / "fetcher.json"
    output.write_text('{"errorMessage":"failed"}')
    monkeypatch.setattr(drill.secrets, "token_hex", lambda _size: "a" * 16)
    monkeypatch.setattr(
        drill,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, '{"StatusCode":200,"FunctionError":"Unhandled"}', ""
        ),
    )

    with pytest.raises(drill.DrillError, match="invocation failed"):
        drill._invoke_fetcher(output)


def test_controlled_fetcher_returns_only_its_unique_objects(monkeypatch, tmp_path):
    output = tmp_path / "fetcher.json"
    keys = [
        "raw/feed=i95/date=2026-08-09/1940Z-aaaaaaaaaaaaaaaa.csv",
        "raw/feed=i66/date=2026-08-09/1940Z-aaaaaaaaaaaaaaaa.xml",
    ]
    output.write_text(json.dumps({"keys": keys}))
    monkeypatch.setattr(drill.secrets, "token_hex", lambda _size: "a" * 16)
    monkeypatch.setattr(
        drill,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, '{"StatusCode":200}', ""
        ),
    )

    assert drill._invoke_fetcher(output) == set(keys)


def test_loader_proof_ignores_unrelated_scheduled_loads(monkeypatch):
    expected = {
        "raw/feed=i95/date=2026-08-09/1940Z-aaaaaaaaaaaaaaaa.csv",
        "raw/feed=i66/date=2026-08-09/1940Z-aaaaaaaaaaaaaaaa.xml",
    }
    monkeypatch.setattr(
        drill,
        "_aws_json",
        lambda *_args: {
            "events": [
                {"message": "LOAD_OK i95"},
                {
                    "message": (
                        "LOAD_OBJECT_OK i95 raw/feed=i95/date=2026-08-09/1940Z.csv"
                    )
                },
                {"message": f"LOAD_OBJECT_OK i66 {sorted(expected)[0]}"},
                {"message": f"LOAD_OBJECT_OK i95 {sorted(expected)[1]}"},
            ]
        },
    )

    assert drill._load_successes(0, expected) == expected


def _policy_change(address: str, expanded_resource: str) -> dict[str, object]:
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "execute-api:Invoke",
                "Resource": expanded_resource,
                "Condition": {"StringEquals": {"aws:SourceVpce": "vpce-123"}},
            }
        ],
    }
    shorthand = json.loads(json.dumps(policy))
    shorthand["Statement"][0]["Resource"] = "execute-api:/*"
    return {
        "address": address,
        "change": {
            "actions": ["update"],
            "before": {"id": "stable", "policy": json.dumps(policy)},
            "after": {"id": "stable", "policy": json.dumps(shorthand)},
        },
    }


def _normalization_plan() -> dict[str, object]:
    return {
        "resource_changes": [
            _policy_change(
                "aws_api_gateway_rest_api.tollchat",
                "arn:aws:execute-api:us-east-1:920534282028:api123/*",
            ),
            _policy_change(
                "aws_api_gateway_domain_name.tollchat",
                "arn:aws:execute-api:us-east-1:920534282028:/domainnames/preview.tollchat.ai+domain123",
            ),
        ]
    }


def test_terraform_plan_accepts_only_api_policy_normalization():
    drill.validate_terraform_plan(_normalization_plan())


@pytest.mark.parametrize("mutation", ["extra", "behavior", "attribute"])
def test_terraform_plan_rejects_real_changes(mutation: str):
    plan = _normalization_plan()
    changes = plan["resource_changes"]
    if mutation == "extra":
        changes.append(
            {
                "address": "aws_lambda_function.tollchat_proxy",
                "change": {"actions": ["update"], "before": {}, "after": {}},
            }
        )
    elif mutation == "behavior":
        policy = json.loads(changes[0]["change"]["after"]["policy"])
        policy["Statement"][0]["Effect"] = "Deny"
        changes[0]["change"]["after"]["policy"] = json.dumps(policy)
    else:
        changes[0]["change"]["after"]["id"] = "changed"

    with pytest.raises(drill.DrillError, match="Terraform plan"):
        drill.validate_terraform_plan(plan)


def test_screenshot_pause_is_sanitized(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda: "")

    drill._screenshot_pause()

    output = capsys.readouterr().err
    assert "TOLLCHAT KILL-SWITCH — ENGAGED" in output
    assert "AgentCore invocations    0" in output
    assert "Automatic restore        ARMED" in output
    for unsafe in ("920534282028", "arn:aws", "preview.tollchat.ai", "Ryan"):
        assert unsafe not in output


def test_report_is_metadata_only():
    report = drill.build_report(
        baseline=5,
        disabled_seconds=2.4,
        recovery_seconds=8.6,
        started_at=datetime(2026, 8, 9, 12, tzinfo=UTC),
        restored_at=datetime(2026, 8, 9, 12, 5, tzinfo=UTC),
        completed_at=datetime(2026, 8, 9, 12, 6, tzinfo=UTC),
    )

    assert report["issues"] == [93]
    assert report["checks"] == {
        "owner_approval_recorded": True,
        "control_plane_zero": True,
        "private_config_blocked": True,
        "private_chat_blocked": True,
        "agentcore_invocations_zero": True,
        "ingestion_healthy": True,
        "rds_healthy": True,
        "terraform_preserved_switch": True,
        "baseline_restored": True,
        "canonical_recovery": True,
    }
    serialized = json.dumps(report)
    for unsafe in (
        "920534282028",
        "arn:aws",
        "preview.tollchat.ai",
        "kill-switch drill request",
        "Ryan",
    ):
        assert unsafe not in serialized


def test_runbook_requires_approval_restore_and_metadata_only_evidence():
    runbook = (ROOT / "docs/runbooks/kill-switch.md").read_text()

    for required in (
        "explicit owner approval",
        "--approved-by Ryan",
        "--pause-for-screenshot",
        "put-function-concurrency",
        "eval/results/",
        "gitleaks",
        "enable_public_chat=false",
    ):
        assert required in runbook


def test_main_reports_static_drill_error_without_external_details(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["drill_kill_switch.py"])
    monkeypatch.setattr(
        drill,
        "run",
        lambda **_arguments: (_ for _ in ()).throw(
            drill.DrillError("Terraform plan contained drift or failed")
        ),
    )

    assert drill.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "KILL-SWITCH DRILL FAILED: Terraform plan contained drift or failed\n"
    )
