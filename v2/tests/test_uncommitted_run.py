"""A local waiver changes checkout admission, never calibration or CI defaults."""

import hashlib
import sys
import tarfile
from pathlib import Path

import pytest

from eval import golden, uncommitted_run
from eval import golden_run as runner


@pytest.mark.parametrize(
    "arguments",
    [
        ["run"],
        ["calibrate", "--allow-uncommitted-application"],
        ["render", "--allow-uncommitted-application"],
        ["run", "--allow-uncommitted-application", "--cases", "one"],
        ["run", "--allow-uncommitted-application", "--cases=one"],
    ],
)
def test_waiver_requires_explicit_full_application_run(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["launcher", *arguments])
    with pytest.raises(SystemExit, match="full application run"):
        uncommitted_run.main()


def test_waiver_keeps_calibration_and_records_actual_snapshot(
    golden_test_identity: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "v2/eval/uncommitted_run.py"

    def git(*args: str) -> str:
        if args[0] == "status":
            return "?? " + source
        if args[0] == "ls-files":
            return source + "\0"
        return "a" * 40

    monkeypatch.setattr(runner, "git", git)
    native_identity = runner.identity
    cases = golden.load_cases()
    baseline = native_identity(cases, allow_uncommitted_preparation=True)
    argv = [
        "launcher",
        "run",
        "--allow-uncommitted-application",
        "--output",
        str(tmp_path),
        "--budget-usd",
        "50",
        "--calibration",
        "approved.json",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    def main() -> None:
        assert "--allow-uncommitted-application" not in sys.argv
        assert sys.argv[1:] == [a for a in argv[1:] if not a.startswith("--allow-")]
        pinned = runner.identity(cases)
        assert runner.calibration_contract(pinned) == runner.calibration_contract(
            baseline
        )
        runner.validate_identity(pinned)
        assert pinned["preparation"]["status"] == "dirty"
        expected = hashlib.sha256((golden.V2.parent / source).read_bytes()).hexdigest()
        assert pinned["local_checkout_waiver"]["launcher_sha256"] == expected
        runner.snapshot_preparation(pinned, tmp_path)
        with tarfile.open(tmp_path / "source-snapshot.tar.gz") as archive:
            stream = archive.extractfile(source)
            assert stream is not None
            assert hashlib.sha256(stream.read()).hexdigest() == expected
        raise RuntimeError("stop before paid work")

    monkeypatch.setattr(runner, "main", main)
    with pytest.raises(RuntimeError, match="stop before paid work"):
        uncommitted_run.main()
    assert runner.identity is native_identity and sys.argv is argv
    with pytest.raises(ValueError, match="clean committed"):
        runner.identity(cases)
