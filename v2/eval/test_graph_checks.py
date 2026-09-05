# pyright: basic
"""Synthetic, network-free checks. Run directly with Python's standard library."""

import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import graph_checks as metric


class MetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {
            "model": "synthetic-test-only",
            "prompt_hash": "1" * 64,
            "tool_contract_hash": "2" * 64,
            "dataset_hash": "3" * 64,
            "commit": "4" * 40,
            "artifact_digest": "5" * 64,
            "grader_digest": metric.grader_digest(),
        }

    def write(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def artifact(
        self, name: str = "artifact", expected: dict[str, Any] | None = None
    ) -> tuple[Path, Path]:
        root = self.root / name
        root.mkdir(parents=True, exist_ok=True)
        case = root / "case.json"
        self.write(
            case,
            {
                "case_id": "case-1",
                "prompt": "synthetic",
                "setup": {},
                "expected": expected or {"exit_code": 0},
                "rubric": ["contract-1"],
            },
        )
        self.write(
            root / "run.json",
            {
                "identity": {**self.identity, "trial_id": "1"},
                "case_digest": metric.digest(case),
                "tokens": None,
                "latency_ms": 0,
                "failure_class": "none",
            },
        )
        (root / "stdout.txt").write_text("hello 42\n")
        self.write(root / "exit_code.json", 0)
        return root, case

    def score(self, root: Path, case: Path) -> tuple[int, dict[str, Any]]:
        result = metric.grade(root, case)
        score = metric.read_json(root / "scorecard.json")
        metric.validate(
            score, metric.read_json(metric.ROOT / "schemas/scorecard.schema.json")
        )
        return result, score

    def run_set(
        self,
        name: str,
        outcomes: Sequence[bool],
        mode: str = "gate",
        identity: dict[str, str] | None = None,
        trial_count: int | None = None,
    ) -> Path:
        root = self.root / name
        ident = identity or self.identity
        paths = []
        for i, passed in enumerate(outcomes, 1):
            artifact, case = self.artifact(f"{name}/case-1/{i}")
            run = metric.read_json(artifact / "run.json")
            run["identity"] = {**ident, "trial_id": str(i)}
            self.write(artifact / "run.json", run)
            if not passed:
                self.write(artifact / "exit_code.json", 1)
            self.score(artifact, case)
            paths.append(f"case-1/{i}/scorecard.json")
        manifest = {
            "mode": mode,
            "identity": ident,
            "cases": ["case-1"],
            "trials": [str(i) for i in range(1, len(outcomes) + 1)],
            "scorecards": paths,
        }
        if trial_count is not None:
            manifest["trial_count"] = trial_count
        self.write(root / "manifest.json", manifest)
        return root

    def compare(
        self, before: Path, after: Path, held: Path | None = None
    ) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = metric.compare(before, after, held)
        return code, out.getvalue().strip(), err.getvalue()

    def sealed(
        self,
        before: Sequence[bool] = (True, True, True),
        after: Sequence[bool] = (True, True, True),
        mode: str = "gate",
        candidate: dict[str, str] | None = None,
    ) -> Path:
        self.run_set("sealed/before", before, mode, self.identity)
        self.run_set("sealed/after", after, mode, candidate or self.identity)
        return self.root / "sealed"

    def test_all_deterministic_checks(self) -> None:
        expected = {
            "exit_code": 0,
            "stdout_contains": ["hello"],
            "stdout_not_contains": ["secret"],
            "regex": [r"hello \d+"],
            "file_exists": ["nested/result.txt"],
            "json_path": [{"path": ["items", 0, "ok"], "equals": True}],
        }
        root, case = self.artifact(expected=expected)
        (root / "files/nested").mkdir(parents=True)
        (root / "files/nested/result.txt").write_text("ok")
        self.write(root / "output.json", {"items": [{"ok": True}]})
        self.assertEqual(self.score(root, case)[0], 0)
        result = subprocess.run(
            [str(metric.ROOT / "grade.sh"), str(root), str(case)], capture_output=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_check_fails_as_agent_quality(self) -> None:
        for expected in (
            {"exit_code": 3},
            {"stdout_contains": ["absent"]},
            {"stdout_not_contains": ["hello"]},
            {"regex": ["absent"]},
            {"file_exists": ["absent"]},
            {"json_path": [{"path": ["missing"], "equals": 2}]},
        ):
            with self.subTest(expected=expected):
                root, case = self.artifact(expected=expected)
                code, score = self.score(root, case)
                self.assertEqual(code, 1)
                self.assertEqual(score["failure_class"], "agent_quality")

    def test_json_equality_distinguishes_boolean_and_integer(self) -> None:
        root, case = self.artifact(
            expected={"json_path": [{"path": [], "equals": True}]}
        )
        self.write(root / "output.json", 1)
        self.assertEqual(self.score(root, case)[0], 1)

    def test_bad_checks_fail_closed(self) -> None:
        for expected in (
            {},
            {"unknown": 0},
            {"regex": ["["]},
            {"exit_code": True},
            {"stdout_contains": []},
            {"file_exists": ["../run.json"]},
            {"file_exists": ["/etc/passwd"]},
            {"json_path": [{"path": [-1], "equals": 0}]},
        ):
            with self.subTest(expected=expected):
                root, case = self.artifact()
                body = metric.read_json(case)
                body["expected"] = expected
                self.write(case, body)
                run = metric.read_json(root / "run.json")
                run["case_digest"] = metric.digest(case)
                self.write(root / "run.json", run)
                code, score = self.score(root, case)
                self.assertEqual(code, 1)
                self.assertEqual(score["failure_class"], "infra_dependency")

    def test_symlink_escape_and_scorecard_destination(self) -> None:
        root, case = self.artifact(expected={"file_exists": ["escape"]})
        (root / "files").mkdir()
        outside = self.root / "outside"
        outside.write_text("untouched")
        (root / "files/escape").symlink_to(outside)
        self.assertEqual(self.score(root, case)[1]["failure_class"], "infra_dependency")
        (root / "scorecard.json").unlink()
        (root / "scorecard.json").symlink_to(outside)
        with self.assertRaises(ValueError):
            metric.grade(root, case)
        self.assertEqual(outside.read_text(), "untouched")

    def test_missing_identity_evidence_and_dependency_failure(self) -> None:
        for problem in ("identity", "stdout", "dependency", "grader", "case"):
            root, case = self.artifact(problem)
            run = metric.read_json(root / "run.json")
            if problem == "identity":
                del run["identity"]["model"]
            elif problem == "stdout":
                (root / "stdout.txt").unlink()
            elif problem == "dependency":
                run["failure_class"] = "infra_dependency"
            elif problem == "grader":
                run["identity"]["grader_digest"] = "0" * 64
            else:
                run["case_digest"] = "0" * 64
            self.write(root / "run.json", run)
            code, score = self.score(root, case)
            self.assertEqual(code, 1)
            self.assertEqual(score["failure_class"], "infra_dependency")

    def test_duplicate_json_keys_rejected(self) -> None:
        root, case = self.artifact()
        case.write_text('{"case_id":"a", "case_id":"b"}')
        self.assertEqual(self.score(root, case)[1]["failure_class"], "infra_dependency")

    def test_comparison_and_gate_all_pass(self) -> None:
        before = self.run_set("before", [True] * 3)
        after = self.run_set("after", [True] * 3)
        held = self.sealed()
        self.assertEqual(self.compare(before, after, held)[:2], (0, "unchanged"))
        result = subprocess.run(
            [str(metric.ROOT / "compare.sh"), str(before), str(after), str(held)],
            capture_output=True,
            text=True,
        )
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "unchanged"))

    def test_two_of_three_is_capability_not_gate(self) -> None:
        before = self.run_set("before", [True, True, False])
        after = self.run_set("after", [True, True, False])
        code, word, reason = self.compare(before, after, self.sealed())
        self.assertEqual((code, word), (1, "unchanged"))
        self.assertIn("flaky", reason)
        self.assertIn("pass^k", reason)

    def test_improvement_and_regression_precedence(self) -> None:
        before = self.run_set("before", [False, True], "improve")
        after = self.run_set("after", [True, False], "improve")
        self.assertEqual(
            self.compare(before, after, self.sealed(mode="improve"))[:2],
            (1, "regressed"),
        )
        after = self.run_set("after", [True, True], "improve")
        self.assertEqual(
            self.compare(before, after, self.sealed(mode="improve"))[:2],
            (0, "improved"),
        )

    def test_held_out_regression_overrides_public_gain(self) -> None:
        before = self.run_set("before", [False] * 3, "improve")
        after = self.run_set("after", [True] * 3, "improve")
        held = self.sealed(after=(True, False, True), mode="improve")
        self.assertEqual(self.compare(before, after, held)[:2], (1, "regressed"))

    def test_missing_duplicate_and_extra_trials_fail_closed(self) -> None:
        root = self.run_set("run", [True] * 3)
        original = metric.read_json(root / "manifest.json")
        for change in ("missing", "duplicate", "extra", "count", "identity"):
            manifest = copy.deepcopy(original)
            if change == "missing":
                manifest["scorecards"].pop()
            elif change == "duplicate":
                manifest["scorecards"].append(manifest["scorecards"][0])
            elif change == "extra":
                manifest["trials"].append("4")
            elif change == "count":
                manifest["trial_count"] = 2
            else:
                manifest["identity"]["model"] = "wrong"
            self.write(root / "manifest.json", manifest)
            with self.subTest(change=change), self.assertRaises(ValueError):
                metric.load_run(root)

    def test_frozen_identity_and_sealed_evidence_required(self) -> None:
        before = self.run_set("before", [True] * 3)
        after = self.run_set("after", [True] * 3)
        with self.assertRaises(ValueError):
            self.compare(before, after)
        changed = {**self.identity, "dataset_hash": "a" * 64}
        after = self.run_set("after", [True] * 3, identity=changed)
        with self.assertRaises(ValueError):
            self.compare(before, after, self.sealed())
        candidate = {**self.identity, "model": "different-candidate"}
        after = self.run_set("after", [True] * 3, identity=candidate)
        with self.assertRaises(ValueError):
            self.compare(before, after, self.sealed())
        self.assertEqual(
            self.compare(before, after, self.sealed(candidate=candidate))[0], 0
        )

    def test_inconsistent_scorecard_and_infra_cannot_promote(self) -> None:
        root = self.run_set("run", [True] * 3)
        path = root / "case-1/1/scorecard.json"
        score = metric.read_json(path)
        score["pass"] = False
        self.write(path, score)
        with self.assertRaises(ValueError):
            metric.load_run(root)
        score["checks"][0]["pass"] = False
        score["checks"][0]["reason"] = "check failed"
        score["failure_class"] = "infra_dependency"
        self.write(path, score)
        with self.assertRaises(ValueError):
            metric.load_run(root)

    def test_held_out_cannot_reduce_gate_trial_count(self) -> None:
        before = self.run_set("before", [True] * 3)
        after = self.run_set("after", [True] * 3)
        self.run_set("sealed/before", [True], trial_count=1)
        self.run_set("sealed/after", [True], trial_count=1)
        with self.assertRaises(ValueError):
            self.compare(before, after, self.root / "sealed")

    def test_cli_malformed_input_is_sanitized_failure(self) -> None:
        before = self.root / "private-person@example.test"
        result = subprocess.run(
            [str(metric.ROOT / "compare.sh"), str(before), str(before)],
            capture_output=True,
            text=True,
        )
        self.assertEqual((result.returncode, result.stdout.strip()), (1, "regressed"))
        self.assertNotIn("private-person", result.stderr)


if __name__ == "__main__":
    unittest.main()
