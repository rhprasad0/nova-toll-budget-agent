"""Offline acceptance of the fresh development set, not model performance."""

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from eval import golden
from eval import golden_run as run
from oracle.build_oracle_data import build_connections, build_points


def test_complete_development_contract_and_reference_labels() -> None:
    golden.validate()
    cases = golden.load_cases()
    assert len(cases) == 100
    assert not any(case.held_out for case in cases)
    examples = run.development_examples()
    assert len(examples) == 135
    assert Counter(example.label == "good" for example in examples) == {
        True: 100,
        False: 35,
    }
    assert Counter(e.actor_validity for e in examples) == {"valid": 132, "invalid": 3}
    assert sum(e.application_stop is not None for e in examples) == 9
    for case in cases:
        assert case.actor.max_turns == 5
        assert "three_axle" not in case.model_dump_json()
        assert "adversarial_direct" not in case.coverage_tags
        assert "adversarial_tool" not in case.coverage_tags


def test_catalog_and_successful_routes_match_committed_oracle() -> None:
    points = build_points()
    catalog = json.loads((golden.ROOT / "prompt-points.json").read_text())
    assert len(catalog) == len(points) == 220
    for point in catalog:
        original = points[point["point_id"]]
        assert point["label"] == original.label
        assert point["aliases"] == list(original.aliases)
        assert point["point_type"] == original.point_type
        assert original.longitude is not None and original.latitude is not None
        assert point["location"]["coordinates"] == [
            float(original.longitude),
            float(original.latitude),
        ]
    connections = {
        (edge.from_point_id, edge.to_point_id)
        for edge in build_connections(points).values()
    }
    for case in golden.load_cases():
        for step in case.steps:
            fixture = golden.load_fixture(step.fixture)
            if fixture.result.get("error") or fixture.result.get("status"):
                continue
            directions = (
                [fixture.input]
                if fixture.tool == "get_current_toll_price"
                else [fixture.input["outbound"], fixture.input["return"]]
            )
            for direction in directions:
                assert isinstance(direction, dict)
                assert (
                    direction["origin_point_id"],
                    direction["destination_point_id"],
                ) in connections


def test_baseline_below_median_wording_preserves_amount_checks() -> None:
    root = golden.V2 / "eval/evidence/golden-100"
    receipt = json.loads((root / "receipt-baseline-1.json").read_text())
    report = json.loads((root / receipt["archive"] / "report.json").read_text())
    cases = {c.id: c for c in golden.load_cases()}
    rows = [
        a
        for a in report["attempts"]
        if a["id"] == "dev3-falling-gallows-quote-2"
        or a["case_id"] == "dev3-two-comparable-weeks"
    ]
    assert len(rows) == 4
    for row in rows:
        assert "unsupported_money" in row["checks"]
        turns = [golden.Turn.model_validate(t) for t in row["turns"]]
        case = cases[row["case_id"]]
        assert "unsupported_money" not in golden.grade_assertions(case, turns)
        turns[-1].response += " It is $999.99 below the median."
        assert "unsupported_money" in golden.grade_assertions(case, turns)


def test_gallows_review_preserves_evidence_and_source_failure() -> None:
    root = golden.V2 / "eval/evidence/golden-100"
    receipt = json.loads((root / "receipt-baseline-2.json").read_text())
    report = json.loads((root / receipt["archive"] / "report.json").read_text())
    rows = {
        a["trial"]: a
        for a in report["attempts"]
        if a["case_id"] == "dev3-gallows-hybrid-salary"
    }
    references = [
        e
        for e in run.development_examples()
        if e.case_id == "dev3-gallows-hybrid-salary"
        and e.label.startswith("review-annual-summary-")
    ]
    assert len(references) == 3
    for example in references:
        trial = int(example.label.rsplit("-", 1)[1])
        row = rows[trial]
        assert [t.model_dump(mode="json") for t in example.turns] == row["turns"]
        assert example.actor_replies == row["actor_replies"]
        assert example.expected is not None
        assert example.expected.outcome is (trial != 3)
        assert example.expected.grounding is (trial != 3)
        assert example.expected.rules
        assert example.actor_validity == "valid"
        assert example.expected_failures == []
        # New reference expectations never overwrite the measured baseline.
        assert row["verdicts"]["outcome"]["passed"] is False
    assert report["overall"]["successful_trials"] == 176


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("count", "exactly 100"),
        ("duplicate", "duplicate case ID"),
        ("held_out", "development-only"),
        ("actor_leak", "oracle leakage"),
        ("hash", "hash drift"),
        ("version", "unsupported corpus"),
    ],
)
def test_corrupted_corpus_is_rejected(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    root = tmp_path / "corpus"
    shutil.copytree(golden.ROOT, root)
    path = root / "cases.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines()]
    if mutation == "count":
        cases.pop()
    elif mutation == "duplicate":
        cases[1]["id"] = cases[0]["id"]
    elif mutation == "held_out":
        cases[0]["held_out"] = True
    elif mutation == "actor_leak":
        cases[0]["actor"]["facts"] += " get_current_toll_price"
    elif mutation == "hash":
        cases[0]["title"] += " changed"
    elif mutation == "version":
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "2.0.8"
        manifest_path.write_text(json.dumps(manifest))
    path.write_text("".join(json.dumps(case) + "\n" for case in cases))
    with pytest.raises(ValueError, match=reason):
        golden.validate(root)


def test_planned_trials_and_empty_holdout_have_no_success_rate() -> None:
    cases = golden.load_cases()
    development = run.summary([], cases)
    assert development["expected_trials"] == 300
    assert development["attempted_trials"] == 0
    assert development["pass_at_1"] is None
    assert development["pass_cubed"] is None
    assert not development["complete"]
    holdout = run.summary([], [case for case in cases if case.held_out])
    assert holdout["case_count"] == holdout["expected_trials"] == 0
    assert holdout["pass_at_1"] is None
    assert holdout["pass_cubed"] is None
    assert holdout["success_ci95"] is None
