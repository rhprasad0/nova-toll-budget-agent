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
    assert len(examples) == 120
    assert Counter(example.label == "good" for example in examples) == {
        True: 100,
        False: 20,
    }
    assert all(example.actor_validity == "valid" for example in examples)
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
