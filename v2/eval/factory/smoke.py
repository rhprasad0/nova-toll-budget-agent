"""Credential-free synthetic workflow; creates no real evaluation cases or approvals."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from eval.factory import factory as f
from eval.factory.kit import APPLICATION, HERE, snapshot, write


def inputs(root: Path) -> Path:
    """Clearly synthetic no-tool cases exercise all allocations and lifecycle gates."""
    drafts = root / "drafts"
    for split, allocation in f.CONTRACT["splits"].items():
        directory = drafts / split
        (directory / "fixtures").mkdir(parents=True)
        shutil.copyfile(
            HERE / "examples/prompt-points.json", directory / "prompt-points.json"
        )
        cases: list[dict[str, Any]] = []
        examples: list[dict[str, Any]] = []
        for family, count in allocation["coverage"].items():
            kind = family.split("_")[0]
            for _ in range(count):
                number = len(cases) + 1
                case_id = f"smoke-{split}-{number:03d}"
                prompt = f"Synthetic {split} scenario {number}: please price an unsupported trip to Testtown."
                case: dict[str, Any] = {
                    "number": number,
                    "id": case_id,
                    "title": "Synthetic factory smoke",
                    "kind": kind,
                    "contract_version": 2,
                    "coverage_family": family,
                    "split_group": case_id,
                    "terminal_objective": "refusal",
                    "minimum_user_turns": 1,
                    "prompt": prompt,
                    "actor": {
                        "facts": "You drive a passenger car with E-ZPass in toll mode. Testtown is your only destination.",
                        "goal": "Learn that this synthetic destination is unsupported.",
                        "follow_up_rules": [],
                        "max_turns": 5,
                    },
                    "frozen_time": "2026-10-01T08:00:00-04:00",
                    "provenance": {
                        "kind": "synthetic",
                        "source": "factory smoke",
                        "note": "Lifecycle check only; never an evaluation corpus.",
                    },
                    "coverage_tags": [family],
                    "critical": False,
                    "held_out": split == "holdout",
                    "max_tool_calls": 0,
                    "steps": [],
                    "expected_assertion": "Explain that Testtown is unsupported without inventing a price.",
                }
                cases.append(case)
                example: dict[str, Any] = {
                    "case_id": case_id,
                    "label": "good",
                    "expected_failures": [],
                    "expected": dict.fromkeys(f.DIMENSIONS, True),
                    "actor_validity": "valid",
                    "rationale": "Synthetic unsupported destination refusal.",
                    "turns": [
                        {
                            "user": prompt,
                            "response": "That destination is outside the supported catalog; I cannot price this trip.",
                            "calls": [],
                        }
                    ],
                }
                examples.append(example)
                if split == "training" and number <= 20:
                    bad = json.loads(json.dumps(example))
                    bad.update(
                        label="invented-price",
                        expected_failures=["unsupported_money"],
                        expected=dict.fromkeys(f.DIMENSIONS, False),
                    )
                    bad["turns"][0]["response"] = "Your unsupported trip costs $123.45."
                    examples.append(bad)
        (directory / "cases.jsonl").write_text(
            "".join(json.dumps(c) + "\n" for c in cases)
        )
        write(directory / "examples.json", examples)
    return drafts


def handoff(root: Path) -> str:
    source_dir = root / "synthetic-source"
    for name in APPLICATION:
        path = source_dir / "v2" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE.parents[1] / name, path)
    subprocess.run(["git", "init", "--quiet", str(source_dir)], check=True)
    for name, value in (
        ("user.name", "Smoke"),
        ("user.email", "smoke@localhost"),
        ("commit.gpgsign", "false"),
        ("core.hooksPath", "/dev/null"),
    ):
        subprocess.run(
            ["git", "-C", str(source_dir), "config", name, value], check=True
        )
    subprocess.run(["git", "-C", str(source_dir), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source_dir),
            "commit",
            "--quiet",
            "-m",
            "Synthetic source handoff",
        ],
        check=True,
    )
    zip_path = root / "source.zip"
    snapshot(source_dir, zip_path)
    return f.import_source(root / "work", zip_path)


def prepared(root: Path) -> tuple[Path, str]:
    work = root / "work"
    work.mkdir(parents=True, exist_ok=True)
    f.init(work)
    f.freeze(work, inputs(work), "4.0.0", dict.fromkeys(f.SPLITS, "4.0.0"), smoke=True)
    calibration = f.calibrate(work, "4.0.0", mock=True)
    f.review_calibration(
        work,
        "4.0.0",
        {
            "evidence_sha256": calibration["evidence_sha256"],
            "reviewer": "Synthetic smoke reviewer",
            "evidence": "Mocked lifecycle check, no human approval or real calibration.",
            "dispositions": [],
        },
    )
    return work, handoff(root)


def audited(work: Path, run_id: str) -> None:
    blind = f.audit(work, run_id)
    review = {
        "audit_sha256": blind["audit_sha256"],
        "reviewer": "Synthetic smoke reviewer",
        "evidence": "Synthetic blinded assessment recorded before reveal.",
        "items": [
            {
                "token": item["token"],
                **dict.fromkeys(f.DIMENSIONS, True),
                "actor_validity": "valid",
                "evidence": "Synthetic independent assessment",
            }
            for item in blind["items"]
        ],
    }
    reveal = f.assessments(work, run_id, review)
    f.finish_audit(
        work,
        run_id,
        {
            "reveal_sha256": reveal["reveal_sha256"],
            "reviewer": "Synthetic smoke reviewer",
            "evidence": "Mock disagreement disposition, no real grading conclusion.",
            "dispositions": [
                {
                    "id": i["id"],
                    "dimension": key,
                    "material": False,
                    "disposition": "accepted_limitation",
                    "evidence": "Known synthetic divergence.",
                }
                for i in reveal["items"]
                for key in i["disagreements"]
            ],
        },
    )


def workflow(root: Path) -> dict[str, Any]:
    with patch.object(
        socket.socket,
        "connect",
        side_effect=AssertionError("smoke must be credential-free and offline"),
    ):
        work, source_id = prepared(root)
        incumbent = f.evaluate(work, "4.0.0", source_id, "incumbent", mock=True)
        audited(work, incumbent)
        f.disclose(
            work,
            incumbent,
            "1" * 64,
            "synthetic reviewer",
            "Manual smoke feedback",
            manual=True,
        )
        f.approve_reuse(
            work,
            "4.0.0",
            source_id,
            "Synthetic smoke reviewer",
            "Next exact snapshot; synthetic lifecycle only",
        )
        candidate = f.evaluate(work, "4.0.0", source_id, "candidate", mock=True)
        audited(work, candidate)
        exported = f.export_report(
            work,
            candidate,
            root / "aggregate.json",
            "synthetic reviewer",
            "Aggregate smoke feedback",
            incumbent,
        )
        f.export_suite(work, "4.0.0", root / "public-suite.zip")
        f.backup(work, root / "backup.tar.gz")
        assert exported["overall"]["expected_trials"] == 150
        assert not exported["release_ready_evidence"]
        assert f.ledger(work)[-1]["event"] == "feedback_disclosed"
        return {
            "candidate": candidate,
            "incumbent": incumbent,
            "ledger_sha256": f.ledger(work)[-1]["sha256"],
            "successful_trials": exported["overall"]["successful_trials"],
            "expected_trials": 150,
            "synthetic_smoke": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    if args.restore:
        work = args.directory / "work"
        with f.locked(work):
            f.restore(work, args.restore)
        reports = [p.parent.name for p in (work / "runs").glob("*/report.json")]
        assert len(reports) == 2 and all(
            f.audit_status(work, rid) == "approved" for rid in reports
        )
        print(
            json.dumps(
                {
                    "restored": True,
                    "runs": len(reports),
                    "ledger_sha256": f.ledger(work)[-1]["sha256"],
                }
            )
        )
    else:
        args.directory.mkdir(parents=True, exist_ok=True)
        print(json.dumps(workflow(args.directory)))


if __name__ == "__main__":
    main()
