"""Credential-free intake checks use synthetic lifecycle data, never real cases."""

from __future__ import annotations

import json
import socket
import stat
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch
from zipfile import ZipFile, ZipInfo

import pytest

from eval import golden, intake
from eval import golden_run as run
from eval.factory import factory as f
from eval.factory import smoke
from eval.repetition import report_trials


@pytest.fixture(scope="module")
def public_export(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("intake-template")
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("network forbidden")
    ):
        work, _ = smoke.prepared(directory)
        archive = directory / "public.zip"
        f.export_suite(work, "4.0.0", archive)
    return archive


@pytest.fixture
def packet(public_export: Path, tmp_path: Path) -> Path:
    directory = tmp_path / "packet"
    directory.mkdir()
    intake.unpack(public_export, directory)
    return directory


def real_label(directory: Path) -> dict[str, Any]:
    """Test only: exercise real-export gates with otherwise synthetic fixtures."""
    manifest = intake.read(directory / "manifest.json")
    measurement = manifest["measurement"]
    measurement["synthetic_smoke"] = False
    measurement["comparison_sha256"] = golden.digest(
        {k: v for k, v in measurement.items() if k != "comparison_sha256"}
    )
    evidence = intake.read(directory / "calibration.json")
    evidence["measurement"] = measurement
    path = directory / "calibration.json"
    path.write_text(json.dumps(evidence))
    manifest["calibration_file_sha256"] = intake.sha(path.read_bytes())
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_factory_export_validates_but_smoke_cannot_activate(
    packet: Path, tmp_path: Path
) -> None:
    manifest = intake.validate_export(packet, allow_smoke=True)
    assert [manifest["splits"][s]["count"] for s in intake.PUBLIC_SPLITS] == [50, 10]
    with pytest.raises(ValueError, match="synthetic smoke"):
        intake.install(packet, manifest, tmp_path / "active")
    assert not (tmp_path / "active").exists()


@pytest.mark.parametrize(
    "entry",
    [
        "../escape",
        "/absolute",
        "holdout/cases.jsonl",
        "training/../escape",
        "training\\escape",
        "training/link",
        "manifest.json",
    ],
)
def test_unpack_rejects_unsafe_and_duplicate_entries(
    tmp_path: Path, entry: str
) -> None:
    archive_path = tmp_path / "bad.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", "{}")
        if entry == "training/link":
            info = ZipInfo(entry)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../../escape")
        elif entry == "manifest.json":
            with pytest.warns(UserWarning, match="Duplicate"):
                archive.writestr(entry, "{}")
        else:
            archive.writestr(entry, "{}")
    with pytest.raises(ValueError):
        intake.unpack(archive_path, tmp_path / "unpacked")
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "change", ["input", "extra", "evidence", "allocation", "approval", "missing_actor"]
)
def test_changed_exports_are_rejected(packet: Path, change: str) -> None:
    manifest = intake.read(packet / "manifest.json")
    if change == "input":
        with (packet / "training/cases.jsonl").open("a") as stream:
            stream.write(
                (packet / "training/cases.jsonl").read_text().splitlines()[0] + "\n"
            )
    elif change == "extra":
        (packet / "training/extra.json").write_text("{}")
    elif change == "allocation":
        manifest["splits"]["training"]["count"] = 49
    else:
        evidence = intake.read(packet / "calibration.json")
        if change == "approval":
            evidence["review"]["status"] = "pending"
        elif change == "missing_actor":
            evidence["actor_check"].pop()
        else:
            evidence["calibration_rows"][0]["expected"]["outcome"] = False
        path = packet / "calibration.json"
        path.write_text(json.dumps(evidence))
        manifest["calibration_file_sha256"] = intake.sha(path.read_bytes())
    (packet / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        intake.validate_export(packet, allow_smoke=True)


def test_install_and_reuse_factory_evidence_with_explicit_repetitions(
    packet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(intake, "PRIVATE", tmp_path / "private")
    manifest = real_label(packet)
    output = tmp_path / "active"
    evidence = intake.install(packet, manifest, output)
    monkeypatch.setattr(golden, "ROOT", output / "training")
    golden.validate()
    corpus = golden.manifest()
    assert corpus["case_count"] == 50 and corpus["trials_per_case"] == 3
    assert not (output / "calibration.json").exists()
    assert evidence.stat().st_mode & 0o777 == 0o600
    for repetitions in (1, 3):
        identity = {
            "harness_version": run.VERSION,
            "corpus": corpus,
            "execution": {"trials_per_case": repetitions},
        }
        assert len(report_trials(identity)) == repetitions
        approved = intake.approved_calibration(evidence, identity)
        assert (
            approved["complete"]
            and approved["review"]["reviewer"] == "Synthetic smoke reviewer"
        )
        assert (
            approved["evidence_sha256"] == manifest["measurement"]["calibration_sha256"]
        )
        summary = run.summary([], golden.load_cases(), trials_per_case=repetitions)
        assert summary["expected_trials"] == 50 * repetitions
    with pytest.raises(FileExistsError):
        intake.install(packet, manifest, output)
    changed = intake.fingerprint()
    changed["runtime"] = {"changed": True}
    monkeypatch.setattr(intake, "fingerprint", lambda: changed)
    with pytest.raises(ValueError, match="recalibrate locally"):
        intake.approved_calibration(evidence, identity)


def test_mismatched_factory_calibration_blocks_before_credentials_and_output(
    packet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(intake, "PRIVATE", tmp_path / "private")
    manifest = real_label(packet)
    output = tmp_path / "active"
    evidence = intake.install(packet, manifest, output)
    monkeypatch.setattr(golden, "ROOT", output / "training")
    identity = {"harness_version": run.VERSION, "corpus": golden.manifest()}
    monkeypatch.setattr(run, "identity", Mock(return_value=identity))
    credentials = Mock(side_effect=AssertionError("must not load credentials"))
    monkeypatch.setattr(run.toll_agent, "load_openai_api_key", credentials)
    changed = intake.fingerprint()
    changed["runtime"] = {"changed": True}
    monkeypatch.setattr(intake, "fingerprint", lambda: changed)
    destination = tmp_path / "paid-run"
    monkeypatch.setattr(
        "sys.argv",
        ["run", "run", "--output", str(destination), "--calibration", str(evidence)],
    )
    with pytest.raises(ValueError, match="recalibrate locally"):
        run.main()
    credentials.assert_not_called()
    assert not destination.exists()


@pytest.mark.parametrize("repetitions", [1, 3])
def test_runner_uses_factory_calibration_and_recorded_execution_slots(
    packet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repetitions: int
) -> None:
    monkeypatch.setattr(intake, "PRIVATE", tmp_path / "private")
    output = tmp_path / "active"
    evidence = intake.install(packet, real_label(packet), output)
    monkeypatch.setattr(golden, "ROOT", output / "training")

    def git(*args: str) -> str:
        return "a" * 40 if args == ("rev-parse", "HEAD") else ""

    monkeypatch.setattr(run, "git", git)
    credentials = Mock(side_effect=AssertionError("mocked run cannot load credentials"))
    monkeypatch.setattr(run.toll_agent, "load_openai_api_key", credentials)

    def execute(
        case: golden.GoldenCase, trial: int, journal: run.Journal
    ) -> run.Attempt:
        row = run.Attempt(
            id=f"{case.id}-{trial}",
            case_id=case.id,
            trial=trial,
            status="scored",
            turns=[
                golden.Turn(
                    user=case.prompt, response="Synthetic offline answer.", calls=[]
                )
            ],
            actor_validity=run.ActorAssessment(
                status="valid", evidence="Synthetic control"
            ),
            verdicts={
                key: run.Verdict(passed=True, evidence="Synthetic control")
                for key in f.DIMENSIONS
            },
            measurements=[
                run.Measurement(
                    role="judge",
                    input_tokens=0,
                    output_tokens=0,
                    cached_tokens=0,
                    written_tokens=0,
                    seconds=0,
                    cost_usd=0,
                    complete=True,
                )
            ],
        )
        journal.append({"event": "attempt_finished", **row.model_dump()})
        return row

    monkeypatch.setattr(run, "execute", execute)
    destination = tmp_path / "mocked-run"
    args = ["run", "run", "--output", str(destination), "--calibration", str(evidence)]
    if repetitions == 3:
        args += ["--trials-per-case", "3"]
    monkeypatch.setattr("sys.argv", args)
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("network forbidden")
    ):
        run.main()
    report = intake.read(destination / "report.json")
    assert report["full_corpus_complete"]
    assert report["overall"]["expected_trials"] == 50 * repetitions
    assert report["manifest"]["identity"]["execution"]["trials_per_case"] == repetitions
    assert report["manifest"]["identity"]["corpus"]["trials_per_case"] == 3
    assert (
        report["manifest"]["calibration"]["review"]["reviewer"]
        == "Synthetic smoke reviewer"
    )
    credentials.assert_not_called()
