"""Explicit, test-only inputs for replay and runner regression checks."""

from pathlib import Path
from typing import Any

from eval import golden

ROOT = Path(__file__).with_name("fixtures") / "golden"


def case(number: int) -> golden.GoldenCase:
    return next(c for c in golden.load_cases(ROOT) if c.number == number)


def report_manifest(
    cases: list[golden.GoldenCase], *, harness_version: str = "2.0.13"
) -> dict[str, Any]:
    """Synthetic report identity, independent of application code and paid runs."""
    digest = "0" * 64
    hashes = {"synthetic-report-fixture": digest}
    return {
        "run_id": "offline-report",
        "mode": "run",
        "identity": {
            "commit": "0" * 40,
            "artifact_sha256": digest,
            "harness_version": harness_version,
            "harness_sha256": digest,
            "corpus": {
                "case_count": len(cases),
                "hashes": hashes,
                "corpus_sha256": golden.digest(hashes),
            },
            "prompt_version": "offline",
            "renderer_version": "offline",
            "prompt_hashes": {"offline": digest},
            "tool_schema_hashes": {"offline": digest},
            "actor_prompt_sha256": digest,
            "judge_prompt_sha256": digest,
            "diagnostic_prompt": "offline",
            "diagnostic_rubrics": {"grounding": "offline", "rules": "offline"},
            "model": "offline",
            "sampling": {"temperature": 0},
            "prices": {"input": 0, "output": 0},
            "cases": [case.model_dump(mode="json") for case in cases],
        },
    }
