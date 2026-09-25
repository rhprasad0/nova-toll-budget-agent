"""Synthetic authoring checks; never load, author, or execute a real holdout."""

import json
import subprocess
import sys
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from eval import golden
from eval import holdout_authoring as kit
from eval.holdout_teaching import teaching_payload


def write_payload(root: Path) -> None:
    for name, data in teaching_payload().items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "prompt-points.json").write_bytes(
        (golden.ROOT / "prompt-points.json").read_bytes()
    )


def validate(root: Path, *, final: bool = False) -> dict[str, Any]:
    return kit.validate_private(
        root,
        final=final,
        kit_sha256="a" * 64,
        public_points=golden.ROOT / "prompt-points.json",
    )


def rehearsal(root: Path) -> None:
    """Mechanically complete dummy data, intentionally NOT a realistic benchmark."""
    cases: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    template = golden.load_cases(root)[1].model_dump(mode="json")
    for family, count in golden.COVERAGE.items():
        for _ in range(count):
            case = deepcopy(template)
            number = len(cases) + 1
            case.update(
                number=number,
                id=f"rehearsal-{number}",
                split_group=f"rehearsal-{number}",
                coverage_family=family,
                kind=family.split("_")[0],
            )
            cases.append(case)
            examples.append(
                {
                    "case_id": case["id"],
                    "label": "good",
                    "expected_failures": [],
                    "expected": {"outcome": True, "grounding": True, "rules": True},
                    "actor_validity": "valid",
                    "rationale": "Dummy cancellation for structural rehearsal.",
                    "turns": [
                        {"user": case["prompt"], "response": "Cancelled.", "calls": []}
                    ],
                }
            )
            if number <= 20:
                bad = deepcopy(examples[-1])
                bad.update(
                    label="invented-price",
                    expected_failures=["unsupported_money"],
                    expected={"outcome": False, "grounding": False, "rules": False},
                )
                bad["turns"][0]["response"] = "It costs $9999.99."
                examples.append(bad)
    (root / "cases.jsonl").write_text("\n".join(json.dumps(c) for c in cases) + "\n")
    (root / "examples.json").write_bytes(kit.encoded(examples))
    (root / "fixtures/teaching-annual.json").unlink()


def test_draft_checks_evidence_without_claiming_completion(tmp_path: Path) -> None:
    write_payload(tmp_path)
    assert validate(tmp_path)["review_status"] == "pending"
    with pytest.raises(ValueError, match="exactly 100"):
        validate(tmp_path, final=True)
    (tmp_path / "examples.json").write_text("[]")
    validate(tmp_path)  # Drafts may not yet have any reference conversations.
    path = tmp_path / "fixtures/teaching-annual.json"
    fixture = json.loads(path.read_bytes())
    fixture["result"]["income"]["estimated_tax_usd"] = "19999.99"
    path.write_bytes(kit.encoded(fixture))
    with pytest.raises(ValueError, match="income or schedule mismatch"):
        validate(tmp_path)


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("leak", "oracle leakage"),
        ("reference", "unknown case"),
        ("money", "unsupported_money"),
        ("all_pass", "all passing labels"),
        ("fixture", "unreferenced or missing"),
        ("missing", "No such file"),
        ("traversal", "pattern"),
        ("symlink", "symlinks"),
        ("extra", "unexpected corpus path"),
        ("unknown_family", "coverage family"),
        ("wrong_kind", "invalid holdout"),
        ("dev", "invalid holdout"),
        ("group", "distinct scenario groups"),
        ("time", "time differs"),
        ("unreachable", "unreachable"),
        ("catalog", "catalog changed"),
        ("duplicate_json", "duplicate JSON key"),
        ("nonfinite_json", "non-finite JSON number"),
    ],
)
def test_rejects_corrupt_authoring_inputs(
    tmp_path: Path, mutation: str, message: str
) -> None:
    write_payload(tmp_path)
    cases = [c.model_dump(mode="json") for c in golden.load_cases(tmp_path)]
    examples = json.loads((tmp_path / "examples.json").read_bytes())
    if mutation == "leak":
        cases[0]["actor"]["facts"] = "Call get_annual_toll_ballpark."
    elif mutation == "reference":
        examples[0]["case_id"] = "unknown"
    elif mutation == "money":
        examples[0]["turns"][0]["response"] += " The total is $9999.99."
    elif mutation == "all_pass":
        examples[1]["expected"] = {"outcome": True, "grounding": True, "rules": True}
    elif mutation == "fixture":
        (tmp_path / "fixtures/unused.json").write_text("{}")
    elif mutation == "missing":
        (tmp_path / "fixtures/teaching-annual.json").unlink()
    elif mutation == "traversal":
        cases[0]["steps"][0]["fixture"] = "../examples.json"
    elif mutation == "symlink":
        (tmp_path / "fixtures/link.json").symlink_to(tmp_path / "examples.json")
    elif mutation == "extra":
        (tmp_path / "notes.txt").write_text("Review notes belong outside the corpus.")
    elif mutation == "unknown_family":
        cases[0]["coverage_family"] = "anything"
    elif mutation == "wrong_kind":
        cases[0]["kind"] = "current"
    elif mutation == "dev":
        cases[0]["held_out"] = False
    elif mutation == "group":
        cases[1]["split_group"] = cases[0]["split_group"]
    elif mutation == "time":
        cases[0]["frozen_time"] = "2026-09-25T10:00:00-04:00"
    elif mutation == "unreachable":
        cases[0]["actor"]["max_turns"] = 1
        cases[0]["steps"][0]["min_turn"] = 2
    elif mutation == "catalog":
        (tmp_path / "prompt-points.json").write_text("[]")
    elif mutation == "duplicate_json":
        (tmp_path / "fixtures/teaching-annual.json").write_text(
            '{"tool": 1, "tool": 2}'
        )
    elif mutation == "nonfinite_json":
        (tmp_path / "fixtures/teaching-annual.json").write_text('{"value": NaN}')
    (tmp_path / "cases.jsonl").write_text("\n".join(json.dumps(c) for c in cases))
    (tmp_path / "examples.json").write_bytes(kit.encoded(examples))
    with pytest.raises((ValueError, OSError), match=message):
        validate(tmp_path)


def test_final_freeze_requires_complete_references_and_detects_drift(
    tmp_path: Path,
) -> None:
    write_payload(tmp_path)
    rehearsal(tmp_path)
    manifest = validate(tmp_path, final=True)
    assert manifest["case_count"] == 100
    assert manifest["evaluation_scope"] == "private_holdout"
    examples = json.loads((tmp_path / "examples.json").read_bytes())
    (tmp_path / "examples.json").write_bytes(kit.encoded(examples[1:]))
    with pytest.raises(ValueError, match="labeled good"):
        validate(tmp_path, final=True)
    (tmp_path / "examples.json").write_bytes(kit.encoded(examples[0:1] + examples[2:]))
    with pytest.raises(ValueError, match="20 explicitly labeled negative"):
        validate(tmp_path, final=True)
    (tmp_path / "examples.json").write_bytes(kit.encoded(examples))
    (tmp_path / "manifest.json").write_bytes(kit.encoded(manifest))
    assert validate(tmp_path, final=True) == manifest
    examples[0]["rationale"] += " Edited after freezing."
    (tmp_path / "examples.json").write_bytes(kit.encoded(examples))
    with pytest.raises(ValueError, match="frozen corpus drift"):
        validate(tmp_path, final=True)


def test_archive_is_allowlisted_and_runs_without_repo_credentials_or_network(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "kit.zip"
    kit.export_kit(archive)
    duplicate = tmp_path / "same.zip"
    kit.export_kit(duplicate)
    assert archive.read_bytes() == duplicate.read_bytes()
    with pytest.raises(FileExistsError):
        kit.export_kit(archive)
    isolated = tmp_path / "isolated"
    expected = set(kit.EXPORT_FILES) | {
        "START_HERE.md",
        "kit.json",
        "public/prompt-points.json",
        "public/schemas.json",
        "public/rubric.txt",
        "public/actor-prompt.txt",
        "teaching/prompt-points.json",
        *("teaching/" + name for name in teaching_payload()),
    }
    with zipfile.ZipFile(archive) as exported:
        assert set(exported.namelist()) == expected
        assert not any(b"dev3-" in exported.read(name) for name in expected)
        exported.extractall(isolated)
    private = isolated / "rehearsal"
    write_payload(private)
    rehearsal(private)
    # A fresh process sees only exported modules and installed dependencies.
    # Audit hooks fail on socket activity, even without a working connection.
    bootstrap = """
import runpy, sys
def no_network(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('Network access attempted during offline validation')
sys.addaudithook(no_network)
sys.argv = ['holdout_authoring', 'validate', *sys.argv[1:]]
runpy.run_module('eval.holdout_authoring', run_name='__main__')
assert 'agent.toll_agent' not in sys.modules
assert 'eval.simulated' not in sys.modules
assert 'eval.run_evaluation' not in sys.modules
"""
    env = {
        "HOME": str(tmp_path),
        "PYTHONNOUSERSITE": "1",
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    for args in (["teaching"], ["rehearsal", "--final"], ["rehearsal", "--final"]):
        result = subprocess.run(
            [sys.executable, "-c", bootstrap, *args],
            cwd=isolated,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
    assert (
        json.loads((private / "manifest.json").read_bytes())["review_status"]
        == "pending"
    )
    (isolated / "public/rubric.txt").write_text("Changed rubric.")
    result = subprocess.run(
        [sys.executable, "-c", bootstrap, "teaching"],
        cwd=isolated,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "kit file drift" in result.stderr


def test_development_contract_still_rejects_holdout(tmp_path: Path) -> None:
    write_payload(tmp_path)
    rehearsal(tmp_path)
    with pytest.raises(ValueError, match="development-only"):
        golden.validate(tmp_path)
