"""Retired inputs and a development-only approval cannot qualify a release."""

import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from eval import golden, golden_actor_check
from eval import golden_run as run
from scripts import golden_gate as gate
from scripts import golden_release as release
from tests.golden_support import ROOT as TEST_DATA


def test_retired_test_data_is_not_an_active_corpus(tmp_path: Path) -> None:
    for name in ("manifest.json", "review.json", "calibration-reference.json"):
        assert not (TEST_DATA / name).exists()
    with pytest.raises(ValueError, match="No active golden corpus"):
        golden.validate(tmp_path)
    with pytest.raises(ValueError, match="exactly 100"):
        golden.validate(TEST_DATA)


def test_development_contract_has_fresh_bound_review() -> None:
    review = json.loads((golden.ROOT / "review.json").read_text())
    manifest = json.loads((golden.ROOT / "manifest.json").read_text())
    assert review["status"] == "approved"
    assert review["reviewer"].startswith("Codex")
    assert review["authorization"].startswith("Ryan explicitly authorized")
    assert review["human_trajectory_adjudication"] is False
    assert review["contract_commit"] and review["reviewed_at"] and review["evidence"]
    assert manifest["tool_description_policy"] == golden.TOOL_DESCRIPTION_POLICY
    assert review["corpus_sha256"] == manifest["corpus_sha256"]
    assert manifest["evaluation_scope"] == "development"
    assert not (golden.ROOT / "calibration-reference.json").exists()


@pytest.mark.parametrize("mode", ["calibrate", "run", "actor-check"])
def test_paid_entrypoints_stop_before_credentials_or_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(golden, "ROOT", tmp_path / "absent-corpus")
    credentials = Mock(side_effect=AssertionError("must not load credentials"))
    monkeypatch.setattr(run.toll_agent, "load_openai_api_key", credentials)
    output = tmp_path / "paid-run"
    args = ["test", "--output", str(output)]
    if mode == "actor-check":
        args += ["--budget-usd", "15"]
    else:
        args.insert(1, mode)
    monkeypatch.setattr("sys.argv", args)
    with pytest.raises(ValueError, match="No active golden corpus"):
        (golden_actor_check.main if mode == "actor-check" else run.main)()
    credentials.assert_not_called()
    assert not output.exists()


def test_release_blocks_even_with_historical_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = Mock(side_effect=AssertionError("must fail before AWS access"))
    monkeypatch.setattr(gate, "development_account", account)
    monkeypatch.setattr(gate, "POLICY", gate.POLICY.with_name("policy-1.0.2.json"))
    with pytest.raises(ValueError, match="unsupported private"):
        gate.policy()
    with pytest.raises(ValueError, match="unsupported private"):
        gate.admit({"candidate": "a" * 40})
    receipt = Mock(side_effect=AssertionError("must fail before receipt lookup"))
    monkeypatch.setattr(gate, "receipt", receipt)
    with pytest.raises(ValueError, match="unsupported private"):
        gate.revalidate({"candidate": "a" * 40, "golden": {"run_id": "old-run"}})
    receipt.assert_not_called()
    with pytest.raises(ValueError, match="unsupported private"):
        release.import_summary({}, "0" * 64, "v1", tmp_path / "prepared")
    account.assert_not_called()
    assert not (tmp_path / "prepared").exists()


def test_application_run_requires_new_corpus_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "pending-corpus"
    shutil.copytree(golden.ROOT, root)
    (root / "review.json").write_text(json.dumps({"status": "pending"}))
    monkeypatch.setattr(golden, "ROOT", root)
    identity = Mock(side_effect=AssertionError("must stop before run identity"))
    credentials = Mock(side_effect=AssertionError("must not load credentials"))
    monkeypatch.setattr(run, "identity", identity)
    monkeypatch.setattr(run.toll_agent, "load_openai_api_key", credentials)
    output = tmp_path / "application"
    monkeypatch.setattr("sys.argv", ["test", "run", "--output", str(output)])
    with pytest.raises(SystemExit, match="2"):
        run.main()
    assert "corpus review is pending" in capsys.readouterr().err
    identity.assert_not_called()
    credentials.assert_not_called()
    assert not output.exists()
