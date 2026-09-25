"""Offline acceptance of the fresh development set, not model performance."""

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from eval import golden
from eval import golden_run as run
from oracle.build_oracle_data import build_connections, build_points


@pytest.mark.parametrize(
    "name,model",
    [
        (name, model)
        for name, models in golden.TOOL_INPUT_MODELS.items()
        for model in sorted(models)
    ],
)
def test_tool_digest_allows_only_literal_input_prose(name: str, model: str) -> None:
    source = f"""
class {model}(BaseModel):
    amount: Annotated[int, Field(ge=1, description="input prose")] = 1
    route: str = Field(alias="route_id", description="route prose")
    def validate(self):
        return self.amount > 0
class Output(BaseModel):
    amount: int = Field(description="output prose")
TOOL_SPEC: dict = {{"name": "tool", "description": "tool prose", "inputSchema": {model}.model_json_schema()}}
"""
    expected = golden.tool_source_digest(name, source)
    for before in ("input prose", "route prose", "tool prose"):
        changed = source.replace(before, "clearer wording")
        assert golden.tool_source_digest(name, changed) == expected
        assert (
            golden.hashlib.sha256(changed.encode()).digest()
            != golden.hashlib.sha256(source.encode()).digest()
        )
    for before, after in (
        ("ge=1", "ge=0"),
        ("Annotated[int", "Annotated[str"),
        ("] = 1", "] = 2"),
        ('alias="route_id"', 'alias="other"'),
        ("return self.amount > 0", "return True"),
        ("output prose", "changed output prose"),
        ('"name": "tool"', '"name": "other"'),
        (', description="input prose"', ""),
        ("ge=1,", "le=10, ge=1,"),
    ):
        assert (
            golden.tool_source_digest(name, source.replace(before, after)) != expected
        )
    for expression in ("build_description()", '"input " + "prose"', 'f"input {value}"'):
        with pytest.raises(ValueError, match="literal strings"):
            golden.tool_source_digest(name, source.replace('"input prose"', expression))


def test_shared_input_output_descriptions_remain_frozen() -> None:
    for name, tool in (
        ("agent_tools/current_price_domain.py", golden.current),
        ("agent_tools/get_annual_toll_ballpark.py", golden.annual),
    ):
        output_definitions = tool.TOOL_SPEC["outputSchema"]["json"]["$defs"]
        assert golden.TOOL_INPUT_MODELS[name].isdisjoint(output_definitions)
    name = "agent_tools/current_price_domain.py"
    source = (golden.V2 / name).read_text()
    changed = source.replace(
        "Supported value: two_axle_passenger.", "Changed profile wording."
    )
    assert changed != source
    assert golden.tool_source_digest(name, source) != golden.tool_source_digest(
        name, changed
    )


def test_tool_prose_keeps_pinned_corpus_but_runtime_changes_do_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "agent_tools/get_annual_toll_ballpark.py"
    source = (golden.V2 / name).read_text()
    target = tmp_path / name
    target.parent.mkdir(parents=True)
    monkeypatch.setattr(golden, "V2", tmp_path)
    monkeypatch.setattr(golden, "SOURCE_FILES", (name,))
    target.write_text(source)
    original = golden.hashes()
    description = "Canonical origin point ID for this leg; resolve its entry/airport role and direction independently."
    assert description in source
    target.write_text(source.replace(description, "Use the resolved origin point ID."))
    assert golden.hashes() == original
    target.write_text(source + "\nUNAUTHORIZED_CHANGE = True\n")
    assert golden.hashes() != original


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


@pytest.mark.parametrize(
    "case_id,response",
    [
        (
            "dev3-falling-gallows-quote",
            "The toll is **$1.80 (21.8%) below** the three-week median of **$8.25**.",
        ),
        (
            "dev3-two-comparable-weeks",
            "It is **$0.10 below** the median of the **2 available comparable weeks** ($8.65; expected 3).",
        ),
        (
            "dev3-two-comparable-weeks",
            "Below the recent median: **$8.65**, by **$0.10 (1.2%)**.",
        ),
        (
            "dev3-two-comparable-weeks",
            "$8.55 is $0.10 below the median of available comparable weeks ($8.65).",
        ),
    ],
)
def test_below_median_wording_preserves_amount_checks(
    case_id: str, response: str
) -> None:
    case = next(c for c in golden.load_cases() if c.id == case_id)
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == case_id and e.label == "good"
    )
    turns = [t.model_copy(deep=True) for t in example.turns]
    turns[-1].response = response
    assert "unsupported_money" not in golden.grade_assertions(case, turns)
    turns[-1].response += " It is $999.99 below the median."
    assert "unsupported_money" in golden.grade_assertions(case, turns)


def test_gallows_review_preserves_evidence_and_source_failure() -> None:
    # Pin the three retained reference transcripts without a second run archive.
    transcript_hashes = {
        1: "eec624b77b5cfb09d8964d73ab520fa8f5e8388fd36ec8b2de341481ce1aa03f",
        2: "d1bac1080f13d8073a149572ba31b0769cc622c64fdbc80ca5eea0778ad893d0",
        3: "7bbec1d4aa61ce6d572a05ed8b4c8454d86d90ef8272e279d7d0543a1e18e437",
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
        assert (
            golden.digest(
                {
                    "turns": [t.model_dump(mode="json") for t in example.turns],
                    "actor_replies": example.actor_replies,
                }
            )
            == transcript_hashes[trial]
        )
        assert example.expected is not None
        assert example.expected.outcome is (trial != 3)
        assert example.expected.grounding is (trial != 3)
        assert example.expected.rules is (trial != 3)
        assert example.actor_validity == "valid"
        assert example.expected_failures == []


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
