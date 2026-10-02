"""Retired fixtures cannot activate development evaluations or transfer approval."""

import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from eval import golden, golden_actor_check
from eval import golden_run as run
from tests.golden_support import ROOT as TEST_DATA


def test_retired_test_data_is_not_an_active_corpus(tmp_path: Path) -> None:
    for name in ("manifest.json", "review.json", "calibration-reference.json"):
        assert not (TEST_DATA / name).exists()
    with pytest.raises(ValueError, match="No active golden corpus"):
        golden.validate(tmp_path)
    with pytest.raises(ValueError, match="exactly 100"):
        golden.validate(TEST_DATA)


def test_development_contract_binds_review_without_transferring_approval() -> None:
    review = json.loads((golden.ROOT / "review.json").read_text())
    manifest = json.loads((golden.ROOT / "manifest.json").read_text())
    assert review["status"] in {"approved", "pending"}
    assert review["authorization"].startswith("Ryan explicitly authorized")
    assert review["human_trajectory_adjudication"] is False
    assert review["evidence"]
    if review["status"] == "approved":
        assert (
            review["reviewer"] and review["contract_commit"] and review["reviewed_at"]
        )
    else:
        assert not review["reviewer"]
        assert review["contract_commit"] is None and review["reviewed_at"] is None
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
