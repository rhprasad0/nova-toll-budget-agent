# pyright: basic
# ruff: noqa: E402
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2))

from eval import calibration


class CalibrationTests(unittest.TestCase):
    def test_current_environment_rejects_stale_candidate(self) -> None:
        identity = {
            "dataset_hash": "dataset",
            "source_digest": "stale",
            "artifact_digest": "current",
            "grader_digest": "grader",
            "rate_card_source": "source",
            "rate_card_version": "version",
            "rate_card_hash": "digest",
            "rate_card_values_hash": "values",
        }
        plan = {
            "identity": identity,
            "selection": {"trials": ["1", "2", "3"]},
            "container_execution": {"image": "image"},
            "rate_card": {
                "source": "source",
                "version": "version",
                "digest": "digest",
            },
        }
        corpus = cast(
            calibration.Corpus,
            SimpleNamespace(manifest={"dataset_sha256": "dataset"}, rows=[]),
        )
        with (
            patch.object(calibration.graph_checks, "valid_annual_identity"),
            patch.object(calibration.graph_checks, "_container_execution"),
            patch.object(
                calibration.graph_checks, "source_digest", return_value="current"
            ),
            patch.object(
                calibration.graph_checks, "grader_digest", return_value="grader"
            ),
            patch.object(
                calibration.graph_checks,
                "annual_rate_card_values_digest",
                return_value="values",
            ),
            self.assertRaisesRegex(ValueError, "environment is stale"),
        ):
            calibration._validate_current_environment(
                plan, corpus, Path("manifest.json"), plan["rate_card"]
            )

    def test_current_environment_rejects_different_trusted_rate_card(self) -> None:
        rate_card = {"source": "source", "version": "version", "digest": "digest"}
        identity = {
            "dataset_hash": "dataset",
            "source_digest": "current",
            "artifact_digest": "current",
            "grader_digest": "grader",
            "rate_card_source": "source",
            "rate_card_version": "version",
            "rate_card_hash": "digest",
            "rate_card_values_hash": "values",
        }
        plan = {
            "identity": identity,
            "selection": {"trials": ["1", "2", "3"]},
            "container_execution": {"image": "image"},
            "rate_card": rate_card,
        }
        corpus = cast(
            calibration.Corpus,
            SimpleNamespace(manifest={"dataset_sha256": "dataset"}, rows=[]),
        )
        with (
            patch.object(calibration.graph_checks, "valid_annual_identity"),
            patch.object(calibration.graph_checks, "_container_execution"),
            patch.object(
                calibration.graph_checks, "source_digest", return_value="current"
            ),
            patch.object(
                calibration.graph_checks, "grader_digest", return_value="grader"
            ),
            patch.object(
                calibration.graph_checks,
                "annual_rate_card_values_digest",
                return_value="values",
            ),
            self.assertRaisesRegex(ValueError, "environment is stale"),
        ):
            calibration._validate_current_environment(
                plan, corpus, Path("manifest.json"), {**rate_card, "digest": "other"}
            )

    def test_identity_separates_candidate_from_evaluator_and_runner(self) -> None:
        identity = {
            "model": "model",
            "prompt_hash": "a" * 64,
            "tool_contract_hash": "b" * 64,
            "model_settings_hash": "c" * 64,
            "prompt_context_hash": "d" * 64,
            "render_date": "2026-09-05",
            "grader_digest": "e" * 64,
            "commit": "f" * 40,
            "artifact_digest": "1" * 64,
            "source_digest": "2" * 64,
        }
        split = {
            "plan": {
                "identity": identity,
                "container_execution": {
                    "image": "image",
                    "image_id": "sha256:" + "3" * 64,
                    "source_digest": "4" * 64,
                },
            }
        }
        with patch.object(calibration, "_application_digest", return_value="5" * 64):
            projected = calibration._identity(split)
        self.assertEqual(projected["candidate"]["application_digest"], "5" * 64)
        self.assertNotIn("grader_digest", projected["candidate"])
        self.assertNotIn("sealed_source_digest", projected["candidate"])
        self.assertEqual(projected["evaluator"]["grader_digest"], "e" * 64)
        self.assertEqual(projected["runner"]["sealed_source_digest"], "2" * 64)

    def test_regular_input_rejects_symlinks_and_hardlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text("{}")
            symlink = root / "symlink.json"
            symlink.symlink_to(source)
            with self.assertRaisesRegex(ValueError, "regular"):
                calibration._regular(symlink)
            hardlink = root / "hardlink.json"
            hardlink.hardlink_to(source)
            with self.assertRaisesRegex(ValueError, "regular"):
                calibration._regular(source)
            source.unlink()
            source.write_text("{}")
            retained = root / "retained"
            retained.mkdir()
            retained_link = root / "retained-link"
            retained_link.symlink_to(retained, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "regular retained root"):
                calibration._validated_split(source, retained_link, {})

    def test_tool_projection_is_allowlisted(self) -> None:
        projected = calibration._tool_projection(
            {
                "name": "get_current_toll_price",
                "fixture_id": "private-fixture",
                "toolUseId": "private-call",
                "input": {
                    "origin_point_id": "private-origin",
                    "pricing_profile": {
                        "vehicle_class": "two_axle_passenger",
                        "api_key": "private-secret",
                    },
                },
                "tool_result": {
                    "total_usd": "4.25",
                    "point_ids": ["private-origin", "private-destination"],
                    "components": [
                        {
                            "facility": "i66",
                            "price_usd": "4.25",
                            "connection_ids": ["private-connection"],
                        }
                    ],
                },
            }
        )
        text = json.dumps(projected)
        self.assertIn("I-66 Express Lanes", text)
        self.assertIn("4.25", text)
        for canary in (
            "private-fixture",
            "private-call",
            "private-origin",
            "private-destination",
            "private-secret",
            "private-connection",
        ):
            self.assertNotIn(canary, text)

    def test_combined_report_keeps_private_aggregate_only(self) -> None:
        identity = {
            "candidate": {"model": "model"},
            "evaluator": {"grader_digest": "a" * 64},
            "runner": {"image": "image"},
        }

        def split(private: bool) -> dict[str, object]:
            case_id = "private-canary" if private else "public-case"
            item = {
                "case_id": case_id,
                "trial_id": "1",
                "state": "passed",
                "retained": True,
                "tokens": 1,
                "latency_ms": 1,
                "cost_usd": 0.0,
                "total_tool_calls": 0,
                "unbound_tool_calls": 0,
                "observed_tools": [],
                "scorecard_sha256": "9" * 64,
            }
            return {
                "plan": {"identity": {"dataset_hash": ("b" if private else "a") * 64}},
                "corpus": SimpleNamespace(
                    rows=[{"id": case_id, "primary_category": "sample"}],
                    manifest=(
                        {
                            "public_dataset_sha256": "public-dataset",
                            "public_membership_sha256": "public-membership",
                        }
                        if private
                        else {
                            "dataset_sha256": "public-dataset",
                            "membership_sha256": "public-membership",
                        }
                    ),
                ),
                "items": [item],
                "manifest_path": Path("public.json"),
                "report": {
                    "private": private,
                    "manifest_sha256": "c" * 64,
                    "summary": {"passed": 1},
                    "breakdowns": {"private-canary": "private-secret"},
                    **({} if private else {"results": [{"case_id": "public-case"}]}),
                },
                "manifest_sha256": "d" * 64,
                "report_sha256": "e" * 64,
                "evidence_sha256": "f" * 64,
            }

        with (
            patch.object(calibration, "_trusted_rate_card", return_value={}),
            patch.object(
                calibration, "_validated_split", side_effect=[split(False), split(True)]
            ) as validated,
            patch.object(calibration, "_identity", return_value=identity),
        ):
            report = calibration.combined_report(
                Path("public.json"),
                Path("public"),
                Path("private.json"),
                Path("private"),
                Path("rate-card.json"),
            )
        self.assertEqual(
            validated.call_args_list[1].kwargs["public_manifest_path"],
            Path("public.json"),
        )
        self.assertEqual(report["public"]["results"][0]["case_id"], "public-case")
        self.assertNotIn("results", report["private"])
        self.assertNotIn("case_id", json.dumps(report["private"]))
        self.assertNotIn("private-secret", json.dumps(report))

    def test_combined_report_rejects_unrelated_private_dataset(self) -> None:
        public = {
            "manifest_path": Path("public.json"),
            "corpus": SimpleNamespace(
                manifest={
                    "dataset_sha256": "public-dataset",
                    "membership_sha256": "public-membership",
                }
            ),
        }
        private = {
            "corpus": SimpleNamespace(
                manifest={
                    "public_dataset_sha256": "different-dataset",
                    "public_membership_sha256": "public-membership",
                }
            )
        }
        with (
            patch.object(calibration, "_trusted_rate_card", return_value={}),
            patch.object(
                calibration, "_validated_split", side_effect=[public, private]
            ),
            self.assertRaisesRegex(ValueError, "not bound to the public dataset"),
        ):
            calibration.combined_report(
                Path("public.json"),
                Path("public"),
                Path("private.json"),
                Path("private"),
                Path("rate-card.json"),
            )

    def test_review_is_blinded_escaped_and_self_contained(self) -> None:
        cards = [
            {
                "ref": "review-01-abcdef",
                "binding": "a" * 64,
                "display_sha256": "d" * 64,
                "conversation": ["<script>alert(1)</script>"],
                "answer": "Safe answer",
                "expected": "Do the safe thing",
                "tools": [],
            }
        ]
        packet = {
            "version": 1,
            "public_manifest_sha256": "b" * 64,
            "evidence_sha256": "c" * 64,
            "cards": [
                {
                    "ref": cards[0]["ref"],
                    "binding": cards[0]["binding"],
                    "display_sha256": cards[0]["display_sha256"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "review.html"
            with patch.object(
                calibration, "_review_cards", return_value=(cards, packet)
            ):
                calibration.render_review(
                    Path("manifest"), Path("root"), Path("rate-card"), output
                )
            text = output.read_text()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertIn("Pass", text)
        self.assertIn("Fail", text)
        self.assertIn("Unsure", text)
        self.assertIn("Download labels", text)
        self.assertIn("display_sha256", text)
        self.assertNotIn("<script>alert(1)</script>", text)
        for forbidden in (
            "failure_class",
            "case_pass3",
            "scorecard.json",
            "fixture_id",
        ):
            self.assertNotIn(forbidden, text)
        self.assertNotIn("https://", text)
        self.assertNotIn("http://", text)

    def test_labels_require_exact_bound_cards(self) -> None:
        packet = {
            "version": 1,
            "public_manifest_sha256": "b" * 64,
            "evidence_sha256": "c" * 64,
            "cards": [
                {
                    "ref": "review-01-abcdef",
                    "binding": "a" * 64,
                    "display_sha256": "d" * 64,
                }
            ],
        }
        value = {
            **packet,
            "labels": [
                {
                    "ref": "review-01-abcdef",
                    "binding": "a" * 64,
                    "label": "Pass",
                    "notes": "",
                }
            ],
        }
        with patch.object(calibration, "_review_cards", return_value=([], packet)):
            self.assertEqual(
                calibration.validate_labels(
                    value, Path("manifest"), Path("root"), Path("rate-card")
                ),
                value,
            )
            changed = json.loads(json.dumps(value))
            changed["labels"][0]["binding"] = "d" * 64
            with self.assertRaisesRegex(ValueError, "decisions"):
                calibration.validate_labels(
                    changed, Path("manifest"), Path("root"), Path("rate-card")
                )


if __name__ == "__main__":
    unittest.main()
