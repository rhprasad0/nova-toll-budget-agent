# pyright: basic
# ruff: noqa: E402
from __future__ import annotations

import json
import subprocess
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

_LEGACY_PUBLIC_MANIFEST = Path(
    "/home/ryan/Documents/nova-toll-budget-agent/.worktrees/issue-360-live-report/v2/eval/golden/manifest-v2.json"
)
_LEGACY_PUBLIC_ROOT = Path(
    "/home/ryan/Documents/nova-toll-budget-agent/.worktrees/issue-360-live-report/.graph/public-parallel-e852f7a"
)
_LEGACY_RATE_CARD = Path(
    "/home/ryan/Documents/nova-toll-budget-agent/.worktrees/eval-300-slice-6/.graph/rate-card.json"
)
_BALANCED_LABELS = Path("/home/ryan/Downloads/tollchat-v2-calibration-labels.json")
_FOLLOW_UP_LABELS = Path(
    "/home/ryan/Downloads/tollchat-v2-calibration-labels-follow-up.json"
)
_LEGACY_EVIDENCE_SHA256 = (
    "917db5b5187ed721b3cb9291185949bc7c1e417e9ac51f223419c5e336a12e09"
)


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

    def test_v2_selection_order_count_and_rejects_altered_manifest(self) -> None:
        categories = {
            case_id: category
            for category, case_ids in (
                ("topology", calibration._V2_BALANCED_CASES[:5]),
                ("current", calibration._V2_BALANCED_CASES[5:10]),
                ("annual", calibration._V2_BALANCED_CASES[10:15]),
                ("multiturn", calibration._V2_BALANCED_CASES[15:20]),
                ("fault", calibration._V2_BALANCED_CASES[20:25]),
                ("abuse", calibration._V2_BALANCED_CASES[25:]),
            )
            for case_id in case_ids
        }
        categories.update(
            {case_id: "multiturn" for case_id in calibration._V2_FOLLOW_UP_CASES}
        )
        corpus = cast(
            calibration.Corpus,
            SimpleNamespace(
                manifest={
                    "dataset_version": "2.2.0",
                    "render_date": "2026-09-05",
                    "dataset_sha256": calibration._V2_PUBLIC_DATASET_SHA256,
                },
                rows=[
                    {
                        "id": case_id,
                        "primary_category": category,
                        "expected_assertion": "expected",
                    }
                    for case_id, category in categories.items()
                ],
            ),
        )
        balanced = calibration._v2_selection("balanced", corpus)
        follow_up = calibration._v2_selection("follow-up", corpus)
        self.assertEqual(
            balanced["cases"],
            [
                "topology-proof-dca-to-i95-north-current",
                "topology-proof-dca-to-i95-north-annual",
                "topology-proof-dca-to-i95-south-current",
                "topology-proof-dca-to-i95-south-annual",
                "topology-proof-dtr-to-greenway-annual",
                "pentagon-eads-to-westpark",
                "springfield-franconia-to-westpark",
                "old-keene-mill-to-reagan-i95-unavailable",
                "dulles-to-reagan-current-price",
                "i66-west-to-route-7-current-price",
                "springfield-franconia-tysons-annual-affordability",
                "leesburg-route-28-schedule-inputs",
                "leesburg-route-28-income-clarification",
                "dulles-to-reagan-annual-unavailable",
                "leesburg-route-28-annual-day-confirmation",
                "multiturn-days-01",
                "multiturn-current-annual-02",
                "multiturn-annual-current-02",
                "multiturn-income-02",
                "multiturn-days-02",
                "fault-current-02",
                "fault-annual-02",
                "fault-current-03",
                "fault-annual-03",
                "fault-current-04",
                "abuse-fake-role",
                "abuse-unrelated-code",
                "abuse-unsupported-override",
                "abuse-fabricate-no-route",
                "abuse-payment-override",
            ],
        )
        self.assertEqual(follow_up["cases"], list(calibration._V2_FOLLOW_UP_CASES))
        self.assertEqual(calibration.validate_v2_selection(balanced, corpus), balanced)
        changed = {**balanced, "cases": list(reversed(balanced["cases"]))}
        with self.assertRaisesRegex(ValueError, "disagrees"):
            calibration.validate_v2_selection(changed, corpus)

        altered_manifest = cast(
            calibration.Corpus,
            SimpleNamespace(
                manifest={
                    **corpus.manifest,
                    "dataset_sha256": "b" * 64,
                },
                rows=corpus.rows,
            ),
        )
        with self.assertRaisesRegex(ValueError, "approved public"):
            calibration._v2_selection("balanced", altered_manifest)
        changed = {**balanced, "render_date": "2026-09-06"}
        with self.assertRaisesRegex(ValueError, "disagrees"):
            calibration.validate_v2_selection(changed, corpus)

    def test_v2_projection_keeps_turns_local_and_blinded(self) -> None:
        rows = [
            {
                "id": case_id,
                "primary_category": "multiturn",
                "expected_assertion": "Expected <safe>",
            }
            for case_id in calibration._V2_FOLLOW_UP_CASES
        ]
        corpus = cast(
            calibration.Corpus,
            SimpleNamespace(
                manifest={
                    "dataset_version": "2.2.0",
                    "render_date": "2026-09-05",
                    "dataset_sha256": calibration._V2_PUBLIC_DATASET_SHA256,
                },
                rows=rows,
            ),
        )
        split = {
            "report": {"private": False},
            "corpus": corpus,
            "root": Path("/retained-public"),
            "manifest_sha256": "b" * 64,
            "evidence_sha256": "c" * 64,
        }
        reads: list[Path] = []

        def read(path: Path) -> dict[str, object]:
            reads.append(path)
            case_id = path.parts[-3]
            if path.name == "receipt.json":
                return {"receipt": case_id}
            return {
                "output": f"final-{case_id}",
                "trajectory": [
                    {
                        "prompt": f"prompt-1-{case_id} <x>",
                        "response": f"response-1-{case_id} </x>",
                        "calls": [
                            {
                                "name": "get_current_toll_price",
                                "fixture_id": "private-fixture",
                                "toolUseId": "private-tool-id",
                                "input": {
                                    "pricing_profile": {
                                        "vehicle_class": "two_axle_passenger",
                                        "private": "private-canary",
                                    }
                                },
                                "tool_result": {
                                    "total_usd": "4.25",
                                    "private": "private-canary",
                                },
                            }
                        ],
                    },
                    {
                        "prompt": f"prompt-2-{case_id}",
                        "response": f"response-2-{case_id}",
                        "calls": [],
                    },
                ],
            }

        with (
            patch.object(calibration, "_validated_split", return_value=split),
            patch.object(calibration, "_trusted_rate_card", return_value={}),
            patch.object(calibration.baseline, "_read", side_effect=read),
        ):
            cards, packet = calibration._v2_review_cards(
                Path("manifest"), Path("root"), Path("rate-card"), "follow-up"
            )
            reads.clear()
            cards_again, packet_again = calibration._v2_review_cards(
                Path("manifest"), Path("root"), Path("rate-card"), "follow-up"
            )
        self.assertEqual(len(cards), 3)
        self.assertEqual(len(reads), 6)
        self.assertEqual(cards_again, cards)
        self.assertEqual(packet_again, packet)
        self.assertTrue(all(path.parts[-2] == "1" for path in reads))
        self.assertEqual(
            [turn["prompt"] for turn in cards[0]["trajectory"]],
            [
                "prompt-1-multiturn-current-annual-01 <x>",
                "prompt-2-multiturn-current-annual-01",
            ],
        )
        self.assertEqual(
            cards[0]["trajectory"][0]["tools"][0]["result"], {"total_usd": "4.25"}
        )
        self.assertEqual(cards[0]["trajectory"][1]["tools"], [])
        text = json.dumps(packet) + json.dumps(cards)
        for forbidden in (
            "private-fixture",
            "private-tool-id",
            "private-canary",
            "failure_class",
            "case_id",
            "toolUseId",
        ):
            self.assertNotIn(forbidden, text)

    def test_v2_html_escaping_and_label_round_trip(self) -> None:
        cards = [
            {
                "ref": "v2-follow-up-01-abcdef",
                "binding": "a" * 64,
                "display_sha256": "b" * 64,
                "trajectory": [
                    {
                        "prompt": "<script>alert(1)</script>",
                        "response": "safe & sound",
                        "tools": [],
                    }
                ],
                "answer": "safe & sound",
                "expected": "Expected behavior",
            }
        ]
        packet = {
            "version": 2,
            "selection": {
                "kind": "follow-up",
                "dataset_version": "2.2.0",
                "dataset_sha256": "c" * 64,
                "render_date": "2026-09-05",
            },
            "selection_sha256": "d" * 64,
            "public_manifest_sha256": "e" * 64,
            "evidence_sha256": "f" * 64,
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
                calibration, "_v2_review_cards", return_value=(cards, packet)
            ):
                calibration.render_v2_review(
                    Path("manifest"),
                    Path("root"),
                    Path("rate-card"),
                    output,
                    "follow-up",
                )
            text = output.read_text()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertNotIn("<script>alert(1)</script>", text)
        self.assertNotIn("https://", text)
        labels = {
            **packet,
            "labels": [
                {
                    "ref": cards[0]["ref"],
                    "binding": cards[0]["binding"],
                    "label": "Unsure",
                    "notes": "needs review",
                }
            ],
        }
        with patch.object(
            calibration, "_v2_review_cards", return_value=(cards, packet)
        ):
            self.assertEqual(
                calibration.validate_v2_labels(
                    labels,
                    Path("manifest"),
                    Path("root"),
                    Path("rate-card"),
                    "follow-up",
                ),
                labels,
            )
            changed = json.loads(json.dumps(labels))
            changed["selection_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "binding"):
                calibration.validate_v2_labels(
                    changed,
                    Path("manifest"),
                    Path("root"),
                    Path("rate-card"),
                    "follow-up",
                )

    def test_immutable_2_2_label_commands_accept_recorded_packets(self) -> None:
        required = (
            _LEGACY_PUBLIC_MANIFEST,
            _LEGACY_PUBLIC_ROOT,
            _LEGACY_RATE_CARD,
            _BALANCED_LABELS,
            _FOLLOW_UP_LABELS,
        )
        if not all(path.exists() for path in required):
            self.skipTest("recorded 2.2 packet inputs are unavailable")
        for kind, labels_path, expected_cards, expected_passes in (
            ("balanced", _BALANCED_LABELS, 30, 21),
            ("follow-up", _FOLLOW_UP_LABELS, 3, 3),
        ):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "eval.calibration",
                    "validate-v2-labels",
                    "--public-manifest",
                    str(_LEGACY_PUBLIC_MANIFEST),
                    "--public-root",
                    str(_LEGACY_PUBLIC_ROOT),
                    "--rate-card",
                    str(_LEGACY_RATE_CARD),
                    "--labels",
                    str(labels_path),
                    "--kind",
                    kind,
                ],
                cwd=_V2,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            packet = json.loads(labels_path.read_text())
            self.assertEqual(packet["selection"]["kind"], kind)
            self.assertEqual(packet["selection"]["dataset_version"], "2.2.0")
            self.assertEqual(
                packet["selection"]["dataset_sha256"],
                calibration._V2_PUBLIC_DATASET_SHA256,
            )
            self.assertEqual(
                packet["public_manifest_sha256"],
                calibration._V2_2_PUBLIC_MANIFEST_SHA256,
            )
            self.assertEqual(packet["evidence_sha256"], _LEGACY_EVIDENCE_SHA256)
            self.assertEqual(len(packet["cards"]), expected_cards)
            self.assertEqual(len(packet["labels"]), expected_cards)
            self.assertEqual(
                sum(item["label"] == "Pass" for item in packet["labels"]),
                expected_passes,
            )

    def test_immutable_2_2_compatibility_rejects_unknown_grader(self) -> None:
        required = (_LEGACY_PUBLIC_MANIFEST, _LEGACY_PUBLIC_ROOT, _LEGACY_RATE_CARD)
        if not all(path.exists() for path in required):
            self.skipTest("recorded 2.2 retained inputs are unavailable")
        corpus = calibration._validated_manifest(_LEGACY_PUBLIC_MANIFEST)
        plan = calibration.baseline._read(_LEGACY_PUBLIC_ROOT / "manifest.json")
        plan["identity"]["grader_digest"] = "b" * 64
        rate_card = calibration._trusted_rate_card(_LEGACY_RATE_CARD)
        with self.assertRaisesRegex(ValueError, "environment is stale"):
            calibration._validate_current_environment(
                plan, corpus, _LEGACY_PUBLIC_MANIFEST, rate_card
            )


if __name__ == "__main__":
    unittest.main()
