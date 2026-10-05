"""Receive trusted public factory exports without activating smoke or holdout data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

from eval import golden

PUBLIC_SPLITS = ("training", "shadow")
ACTIVE = golden.V2 / "eval/active"
PRIVATE = golden.V2 / "eval/private/intake"


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint() -> dict[str, Any]:
    """Application prose is masked; evaluator code and measured settings are fixed."""
    from eval import golden_run as run
    from eval.factory.factory import runtime
    from eval.factory.kit import CONTRACT

    settings = CONTRACT["settings"]
    if (
        settings["actor_params"] != run.EVAL_MODEL_PARAMS
        or settings["judge_params"] != run.JUDGE_MODEL_PARAMS
        or settings["prices"] != run.PRICES
    ):
        raise ValueError("factory and runner settings differ; rebuild and recalibrate")
    return {
        "harness_version": run.VERSION,
        "sources": golden.source_hashes(),
        "settings": settings,
        "runtime": runtime(),
    }


def unpack(archive_path: Path, destination: Path) -> None:
    """No extractall: validate every path and bound decompression before writing."""
    with ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (
            len(names) > 5000
            or len(names) != len(set(names))
            or sum(e.file_size for e in entries) > 100_000_000
        ):
            raise ValueError("duplicate entries or oversized factory export")
        for entry in entries:
            name = entry.filename
            path = PurePosixPath(name)
            mode = entry.external_attr >> 16
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in name
                or path.as_posix() != name
                or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or entry.is_dir()
                or entry.file_size > 10_000_000
                or not (
                    name in {"manifest.json", "calibration.json"}
                    or (len(path.parts) >= 2 and path.parts[0] in PUBLIC_SPLITS)
                )
            ):
                raise ValueError(
                    "unsafe path, file type, size, or non-public export entry"
                )
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))


def validate_public(
    directory: Path, manifest: dict[str, Any], *, allow_smoke: bool = False
) -> None:
    from eval.factory.factory import validate_splits, version
    from eval.factory.kit import CONTRACT

    if manifest.get("export_format_version") != 1 or set(manifest["splits"]) != set(
        PUBLIC_SPLITS
    ):
        raise ValueError(
            "unsupported public export; regenerate with the current factory kit"
        )
    version(manifest["version"])
    measurement = manifest["measurement"]
    if measurement["synthetic_smoke"] is not False and not allow_smoke:
        raise ValueError("synthetic smoke exports cannot activate training")
    if measurement["settings"] != CONTRACT["settings"]:
        raise ValueError("unsupported factory settings")
    if measurement["comparison_sha256"] != golden.digest(
        {k: v for k, v in measurement.items() if k != "comparison_sha256"}
    ):
        raise ValueError("changed factory measurement identity")
    if (
        manifest["fingerprint"]["settings"] != measurement["settings"]
        or manifest["fingerprint"]["runtime"] != measurement["runtime"]
    ):
        raise ValueError("fingerprint and factory measurement differ")
    hashes = validate_splits(directory, splits=PUBLIC_SPLITS)
    for split in PUBLIC_SPLITS:
        recorded = manifest["splits"][split]
        version(recorded["version"])
        if (
            recorded["files"] != hashes[split]
            or recorded["sha256"] != golden.digest(hashes[split])
            or any(recorded[k] != v for k, v in CONTRACT["splits"][split].items())
        ):
            raise ValueError(f"{split}: input digest or allocation mismatch")


def validate_evidence(
    directory: Path, manifest: dict[str, Any], evidence_path: Path
) -> dict[str, Any]:
    from eval import golden_run as run

    if sha(evidence_path.read_bytes()) != manifest["calibration_file_sha256"]:
        raise ValueError("changed exported calibration evidence")
    evidence = read(evidence_path)
    review = evidence["review"]
    if (
        evidence["measurement"] != manifest["measurement"]
        or evidence["review_status"] != "approved"
        or review["status"] != "approved"
        or not review["reviewer"]
        or not review["reviewed_at"]
    ):
        raise ValueError(
            "factory calibration is unapproved or bound to different inputs"
        )
    examples = [
        golden.Example.model_validate(e)
        for split in PUBLIC_SPLITS
        for e in json.loads((directory / split / "examples.json").read_text())
    ]
    expected = {f"{e.case_id}-{e.label}": e for e in examples}
    rows = evidence["calibration_rows"]
    if len(rows) != len(expected) or {r["id"] for r in rows} != set(expected):
        raise ValueError("missing, duplicate, or non-public calibration references")
    for row in rows:
        example = expected[row["id"]]
        attempt = run.Attempt.model_validate(
            {k: v for k, v in row.items() if k in run.Attempt.model_fields}
        )
        if (
            attempt.case_id != example.case_id
            or row["example"] != example.label
            or row["expected"]
            != (example.expected.model_dump() if example.expected else None)
            or row["expected_actor_validity"] != example.actor_validity
            or not row["measurement_complete"]
            or not attempt.measurements
            or any(not m.complete for m in attempt.measurements)
        ):
            raise ValueError("incomplete or changed calibration reference")
    actors = evidence["actor_check"]
    case_ids = {
        c.id for split in PUBLIC_SPLITS for c in golden.load_cases(directory / split)
    }
    if len(actors) != len(case_ids) or {r["case_id"] for r in actors} != case_ids:
        raise ValueError("missing, duplicate, or non-public actor checks")
    for row in actors:
        attempt = run.Attempt.model_validate(row)
        if (
            attempt.trial != 1
            or attempt.id != f"{attempt.case_id}-1"
            or attempt.status not in {"scored", "inconclusive"}
            or not attempt.measurements
            or any(not m.complete for m in attempt.measurements)
        ):
            raise ValueError("incomplete actor check evidence")
    return evidence


def validate_export(directory: Path, *, allow_smoke: bool = False) -> dict[str, Any]:
    if {p.name for p in directory.iterdir()} != {
        "manifest.json",
        "calibration.json",
        *PUBLIC_SPLITS,
    }:
        raise ValueError("unexpected public export entry")
    manifest = read(directory / "manifest.json")
    validate_public(directory, manifest, allow_smoke=allow_smoke)
    validate_evidence(directory, manifest, directory / "calibration.json")
    return manifest


def training_contract(factory: dict[str, Any]) -> dict[str, Any]:
    split = factory["splits"]["training"]
    hashes = {**split["files"], **golden.source_hashes()}
    settings = factory["measurement"]["settings"]
    return {
        "version": split["version"],
        "evaluation_scope": "training",
        "case_count": split["count"],
        # Preserve factory repetitions; execution overrides live in run.identity.
        "trials_per_case": settings["trials_per_case"],
        "actor_model": settings["actor_model"],
        "judge_model": settings["judge_model"],
        "tool_description_policy": golden.TOOL_DESCRIPTION_POLICY,
        "hashes": hashes,
        "corpus_sha256": golden.digest(hashes),
        "factory": factory,
    }


def validate_installed(directory: Path) -> None:
    manifest = read(directory / "manifest.json")
    if manifest.get("status") != "approved":
        raise ValueError("training input approval is pending")
    factory = manifest["factory"]
    if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob("*")):
        raise ValueError("installed training inputs must be regular files")
    if {p.name for p in directory.iterdir()} != {"manifest.json", *PUBLIC_SPLITS}:
        raise ValueError("unexpected installed input")
    validate_public(directory, factory)
    if manifest["training"] != training_contract(factory):
        raise ValueError(
            "training inputs or protected evaluator changed; new contract required"
        )


def install(directory: Path, manifest: dict[str, Any], output: Path) -> Path:
    """All validation precedes writes; one rename publishes both splits together."""
    if validate_export(directory) != manifest:
        raise ValueError("installation manifest differs from validated export")
    if output.exists() or output.is_symlink():
        raise FileExistsError(
            "active inputs already exist; never overwrite an installed set"
        )
    evidence = directory / "calibration.json"
    private = PRIVATE / manifest["calibration_file_sha256"] / "calibration.json"
    private.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if private.exists():
        if private.read_bytes() != evidence.read_bytes():
            raise ValueError("private calibration evidence changed")
    else:
        with private.open("xb") as stream:
            stream.write(evidence.read_bytes())
        private.chmod(0o600)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staged = Path(temporary) / "active"
        staged.mkdir()
        for split in PUBLIC_SPLITS:
            shutil.copytree(directory / split, staged / split)
        (staged / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "approved",
                    "factory": manifest,
                    "training": training_contract(manifest),
                },
                indent=2,
            )
            + "\n"
        )
        validate_installed(staged)
        os.rename(staged, output)
    return private


def approved_calibration(path: Path, identity: dict[str, Any]) -> dict[str, Any]:
    """Adapt verified factory evidence to the runner's existing calibration binding."""
    corpus = identity["corpus"]
    if corpus != golden.manifest():
        raise ValueError("factory calibration does not match active training identity")
    factory = corpus["factory"]
    if factory["fingerprint"] != fingerprint():
        raise ValueError(
            "factory evaluator, runtime, or settings differ; recalibrate locally"
        )
    validate_installed(golden.ROOT.parent)
    evidence = validate_evidence(golden.ROOT.parent, factory, path)
    review = {
        **evidence["review"],
        "evidence_sha256": factory["measurement"]["calibration_sha256"],
        "evidence": "Factory review "
        + factory["measurement"]["calibration_review_sha256"],
    }
    return {
        "complete": True,
        "review": review,
        "manifest": {
            "identity": identity,
            "run_id": "factory-" + factory["measurement"]["calibration_sha256"],
        },
        "evidence_sha256": factory["measurement"]["calibration_sha256"],
        "exported_evidence_sha256": factory["calibration_file_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("validate", "install"))
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Validate synthetic exports; never install them.",
    )
    args = parser.parse_args()
    if args.smoke and args.mode != "validate":
        parser.error("--smoke is validation-only")
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        unpack(args.archive, directory)
        manifest = validate_export(directory, allow_smoke=args.smoke)
        if args.mode == "install":
            evidence = install(directory, manifest, ACTIVE)
            print(
                f"Installed training/shadow {manifest['version']}; calibration: {evidence}"
            )
        else:
            print(
                f"Validated training/shadow {manifest['version']}; synthetic_smoke={manifest['measurement']['synthetic_smoke']}"
            )


if __name__ == "__main__":
    main()
