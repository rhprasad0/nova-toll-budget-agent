# pyright: basic
# ruff: noqa: E402
"""Offline baseline accounting checks using the existing synthetic Strands model."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2))

from eval import baseline
from eval.container_runner import ContainerEvidence, ContainerTrial, source_digest
from eval.fixture_runner import (
    FixtureRunPacket,
    RateCard,
    run_fixture_trial,
    write_raw_artifact,
)
from eval.golden_corpus import Corpus, validate
from oracle.build_oracle_data import build_points
from tests.test_fixture_eval import _FakeModel


class BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = validate(_V2 / "eval/golden/manifest-v2.json")
        cases = list(baseline._PILOT_CASES)
        cls.selection = {
            "cases": cases,
            "trials": ["pilot-1"],
            "dataset_sha256": cls.corpus.manifest["dataset_sha256"],
            "render_date": cls.corpus.manifest["render_date"],
        }
        cls.points = [
            {
                "point_id": p.point_id,
                "network_id": p.network_id,
                "source_node_id": p.source_node_id,
                "point_type": p.point_type,
                "direction": p.direction,
                "label": p.label,
                "aliases": list(p.aliases),
                "location": {
                    "type": "Point",
                    "coordinates": [
                        float(cast(str, p.longitude)),
                        float(cast(str, p.latitude)),
                    ],
                },
            }
            for _, p in sorted(build_points().items())
        ]
        cls.card = RateCard("synthetic-offline", "1", "a" * 64, 0.2, 1.2, 0.02, 0.25)
        cls.evidence = ContainerEvidence(
            "synthetic:test", "sha256:" + "b" * 64, source_digest()
        )
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / "run"
        cls.calls = []

        def execute(
            packet: FixtureRunPacket,
            *,
            artifact_root: Path,
            trial_id: str,
            rate_card: RateCard,
            evidence: ContainerEvidence,
            **kwargs: object,
        ) -> ContainerTrial:
            cls.calls.append((packet.case_id, trial_id))
            if packet.case_id == cases[0]:
                raise RuntimeError("PRIVATE-EXCEPTION-CANARY")
            record = run_fixture_trial(
                packet,
                model=_FakeModel(packet),
                artifact_root=None,
                trial_id=trial_id,
                rate_card=rate_card,
            )
            record["output"]["container_execution"] = asdict(evidence)
            write_raw_artifact(artifact_root, record)
            return ContainerTrial(record, evidence)

        with patch.object(baseline, "run_container_trial", side_effect=execute):
            cls.report = baseline.run_baseline(
                cls.root,
                cls.selection,
                key="synthetic-offline-key",
                prompt_points=cls.points,
                rate_card=cls.card,
                evidence=cls.evidence,
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def copy_run(self, name: str) -> Path:
        root = Path(self.temp.name) / name
        shutil.copytree(self.root, root)
        (root / "report.json").unlink()
        return root

    def test_scheduling_failures_denominators_and_no_overwrite(self) -> None:
        self.assertEqual(self.calls, [(c, "pilot-1") for c in self.selection["cases"]])
        summary = self.report["summary"]
        self.assertEqual(summary["scheduled_attempts"], 30)
        self.assertEqual(summary["retained_attempts"], 30)
        self.assertEqual(summary["infrastructure_failures"], 1)
        self.assertEqual(summary["valid_scored_attempts"], 29)
        self.assertEqual(summary["pass_rate"]["denominator"], 29)
        self.assertIsNone(summary["cost_usd"])
        self.assertIsNone(summary["partial_failed_trial_cost_usd"])
        self.assertGreater(summary["complete_trial_cost_subtotal_usd"], 0)
        self.assertNotIn("PRIVATE-EXCEPTION-CANARY", json.dumps(self.report))
        for category in baseline._CATEGORIES:
            self.assertEqual(
                self.report["breakdowns"]["category"][category]["scheduled_attempts"], 5
            )
        original = (self.root / "report.json").read_bytes()
        with self.assertRaises(ValueError):
            baseline.aggregate_baseline(
                self.root,
                expected_identity=self.report["identity"],
                expected_container_execution=asdict(self.evidence),
            )
        self.assertEqual((self.root / "report.json").read_bytes(), original)
        with (
            patch.object(baseline, "run_container_trial") as execute,
            self.assertRaises(FileExistsError),
        ):
            baseline.run_baseline(
                self.root,
                self.selection,
                key="synthetic-offline-key",
                prompt_points=self.points,
                rate_card=self.card,
                evidence=self.evidence,
            )
        execute.assert_not_called()

    def test_selection_supports_full_baseline_and_rejects_mutations(self) -> None:
        full = {
            **self.selection,
            "cases": [r["id"] for r in self.corpus.rows],
            "trials": ["1", "2", "3"],
        }
        self.assertEqual(
            baseline.validate_selection(full, self.corpus)["phase"], "baseline"
        )
        for field, value in [
            ("cases", [self.selection["cases"][0]] * 30),
            ("cases", [*self.selection["cases"][:-1], "unknown-case"]),
            ("trials", ["1"]),
            ("trials", None),
            ("dataset_sha256", "0" * 64),
            ("render_date", "2026-09-06"),
        ]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                baseline.validate_selection(
                    {**self.selection, field: value}, self.corpus
                )
        alternate = deepcopy(self.selection)
        replacement = next(
            row["id"]
            for row in self.corpus.rows
            if row["primary_category"] == "topology"
            and row["id"] not in self.selection["cases"]
        )
        alternate["cases"][0] = replacement
        with self.assertRaises(ValueError):
            baseline.validate_selection(alternate, self.corpus)

    def test_missing_and_modified_artifacts_are_not_scored(self) -> None:
        root = self.copy_run("mutated")
        cases = self.selection["cases"]
        shutil.rmtree(root / cases[1])
        changed = root / cases[2] / "pilot-1"
        score = json.loads((changed / "scorecard.json").read_text())
        score["identity"]["model"] = "different-model"
        (changed / "scorecard.json").write_text(json.dumps(score))
        receipt = json.loads((changed / "receipt.json").read_text())
        receipt["scorecard_sha256"] = baseline._digest(changed / "scorecard.json")
        (changed / "receipt.json").write_text(json.dumps(receipt))
        raw = root / cases[3] / "pilot-1" / "output.json"
        output = json.loads(raw.read_text())
        output["container_execution"]["image_id"] = "sha256:" + "c" * 64
        raw.write_text(json.dumps(output))
        rebound = root / cases[4] / "pilot-1"
        run = json.loads((rebound / "run.json").read_text())
        run["case_digest"] = "0" * 64
        (rebound / "run.json").write_text(json.dumps(run))
        receipt = json.loads((rebound / "receipt.json").read_text())
        receipt["run_sha256"] = baseline._digest(rebound / "run.json")
        (rebound / "receipt.json").write_text(json.dumps(receipt))
        report = baseline.aggregate_baseline(
            root,
            expected_identity=self.report["identity"],
            expected_container_execution=asdict(self.evidence),
        )
        self.assertEqual(report["summary"]["missing_or_interrupted"], 1)
        self.assertEqual(report["summary"]["identity_mismatch_or_inconclusive"], 3)
        self.assertEqual(report["summary"]["valid_scored_attempts"], 25)

    def test_infra_scorecard_stays_out_of_valid_denominator(self) -> None:
        root = self.copy_run("infra-scorecard")
        changed = root / self.selection["cases"][5] / "pilot-1"
        score = json.loads((changed / "scorecard.json").read_text())
        score["pass"] = False
        score["failure_class"] = "infra_dependency"
        (changed / "scorecard.json").write_text(json.dumps(score))
        receipt = json.loads((changed / "receipt.json").read_text())
        receipt["scorecard_sha256"] = baseline._digest(changed / "scorecard.json")
        (changed / "receipt.json").write_text(json.dumps(receipt))
        report = baseline.aggregate_baseline(
            root,
            expected_identity=self.report["identity"],
            expected_container_execution=asdict(self.evidence),
        )
        self.assertEqual(report["summary"]["infrastructure_failures"], 2)
        self.assertEqual(report["summary"]["valid_scored_attempts"], 28)

    def test_external_identity_pin_is_required_and_mismatch_rejected(self) -> None:
        with self.assertRaises(ValueError):
            baseline.aggregate_baseline(self.root)
        with self.assertRaises(ValueError):
            baseline.aggregate_baseline(
                self.root,
                expected_identity={
                    **self.report["identity"],
                    "model": "wrong-model",
                },
                expected_container_execution=asdict(self.evidence),
            )

    def test_unbound_call_is_visible_when_expected_call_is_missing(self) -> None:
        row = next(
            item
            for item in self.report["results"]
            if item["case_id"] == "reagan-airport-to-westpark"
        )
        self.assertEqual(row["total_tool_calls"], 1)
        self.assertEqual(row["unbound_tool_calls"], 1)
        self.assertEqual(row["state"], "agent_quality_failure")

    def test_private_export_contains_only_opaque_ids_and_aggregates(self) -> None:
        root = Path(self.temp.name) / "private"
        root.mkdir()
        rows = []
        for index in range(50):
            row = deepcopy(self.corpus.rows[index])
            row.update(id=f"PRIVATE-CANARY-{index}", prompt="PRIVATE-PROMPT-CANARY")
            rows.append(row)
        private_hash = "d" * 64
        corpus = SimpleNamespace(
            rows=rows,
            manifest={
                **self.corpus.manifest,
                "dataset_sha256": private_hash,
                "public_dataset_sha256": self.corpus.manifest["dataset_sha256"],
            },
        )
        selection = {
            **self.selection,
            "cases": [r["id"] for r in rows],
            "trials": ["1", "2", "3"],
            "dataset_sha256": private_hash,
        }
        plan = json.loads((self.root / "manifest.json").read_text())
        plan.update(
            private=True,
            selection=baseline.validate_selection(selection, cast(Corpus, corpus)),
        )
        plan["identity"]["dataset_hash"] = private_hash
        plan["selection_file_sha256"] = None
        plan["selection_digest"] = baseline.graph_checks.annual_json_digest(
            plan["selection"]
        )
        (root / "manifest.json").write_text(json.dumps(plan))
        with (
            patch.object(baseline, "_validated_manifest", return_value=corpus),
            patch.object(
                baseline,
                "adapt_holdout_rows",
                return_value=[
                    {
                        "case_id": row["id"],
                        "row": row,
                        "row_digest": baseline._case_digest(
                            json.dumps(row, sort_keys=True).encode()
                        ),
                        "dataset_hash": private_hash,
                    }
                    for row in rows
                ],
            ),
        ):
            report = baseline.aggregate_baseline(
                root,
                expected_identity=plan["identity"],
                expected_container_execution=plan["container_execution"],
            )
        self.assertEqual(report["summary"]["scheduled_attempts"], 150)
        self.assertEqual(report["summary"]["missing_or_interrupted"], 150)
        self.assertNotIn("opaque_case_ids", report)
        self.assertNotIn("results", report)
        self.assertNotIn("PRIVATE-CANARY", json.dumps(report))
        self.assertNotIn("PRIVATE-PROMPT-CANARY", json.dumps(report))

    def test_physical_evidence_is_separate(self) -> None:
        physical = self.report["physical_evidence"]
        self.assertEqual(physical["records"], 100)
        self.assertEqual(
            physical["capture_status_counts"]["retained_validated_capture"], 98
        )
        self.assertEqual(len(physical["physical_findings"]), 4)
        self.assertNotIn("11732", json.dumps(physical))


if __name__ == "__main__":
    unittest.main()
