"""The retired corpus cannot trigger spending or qualify a production release."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from eval import golden, golden_actor_check
from eval import golden_run as run
from scripts import golden_gate as gate
from scripts import golden_release as release
from tests.golden_support import ROOT as TEST_DATA


def test_no_active_corpus_or_approval() -> None:
    assert not list(golden.ROOT.glob("**/*.json*"))
    for root in (golden.ROOT, TEST_DATA):
        assert not (root / "manifest.json").exists()
        assert not (root / "review.json").exists()
        assert not (root / "calibration-reference.json").exists()
    with pytest.raises(ValueError, match="No active golden corpus"):
        golden.validate()
    with pytest.raises(ValueError, match="exactly 200"):
        golden.validate(TEST_DATA)


@pytest.mark.parametrize("mode", ["calibrate", "run", "actor-check"])
def test_paid_entrypoints_stop_before_credentials_or_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    credentials = Mock(side_effect=AssertionError("must not load credentials"))
    monkeypatch.setattr(run.toll_agent, "load_openai_api_key", credentials)
    output = tmp_path / "paid-run"
    args = ["test", "--output", str(output)]
    if mode == "actor-check":
        args += ["--prior-spend-usd", "0"]
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
    assert gate.policy()  # A real historical approved policy is insufficient.
    with pytest.raises(ValueError, match="No active golden corpus"):
        gate.code_digest()
    with pytest.raises(ValueError, match="No active golden corpus"):
        gate.admit({"candidate": "a" * 40})
    with pytest.raises(ValueError, match="No active golden corpus"):
        release.prepare({}, tmp_path, tmp_path / "prepared")
    account.assert_not_called()
    assert not (tmp_path / "prepared").exists()
