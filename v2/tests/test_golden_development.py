"""Offline grader-logic regressions over five retired development cases."""

import json
from pathlib import Path

import pytest

from eval import golden
from eval import golden_run as run
from oracle.build_oracle_data import build_connections, build_points

pytestmark = pytest.mark.usefixtures("grader_reference_data")


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
    original = golden.source_hashes()
    description = "Canonical origin point ID for this leg; resolve its entry/airport role and direction independently."
    assert description in source
    target.write_text(source.replace(description, "Use the resolved origin point ID."))
    assert golden.source_hashes() == original
    target.write_text(source + "\nUNAUTHORIZED_CHANGE = True\n")
    assert golden.source_hashes() != original


@pytest.mark.parametrize(
    "text,source,unsupported",
    [
        ("$125.20, about $125", "125.20", False),
        ("**$125.20**, approximately **$125**.", "125.20", False),
        ("USD 125.20, roughly 125 dollars", "125.20", False),
        ("$125.50, around $126", "125.50", False),
        ("-$125.50, about -$126", "-125.50", False),
        ("A $125.50 decrease, about $126 decrease", "-125.50", False),
        ("$125.20, about $126", "125.20", True),
        ("$125.20, $125", "125.20", True),
        ("About $125, then $125.20", "125.20", True),
        ("About $125", "125.20", True),
        ("$125.20, about $125.00", "125.20", True),
        ("$125.20, about $125k", "125.20", True),
        ("$125.20, about $125 decrease", "125.20", True),
        ("-$125.20, about $125", "-125.20", True),
        ("$0.20, about $0", "0.20", True),
        ("$125.20, about $125, but exactly $125", "125.20", True),
    ],
)
def test_qualified_rounding_preserves_exact_money_checks(
    text: str, source: str, unsupported: bool
) -> None:
    assert bool(golden.unsupported_money(text, {golden.Decimal(source)})) == unsupported


def test_rounding_can_restate_prior_answer_but_not_superseded_evidence() -> None:
    previous = {golden.Decimal("125.20")}
    assert not golden.unsupported_money("About $125", previous, previous)
    assert golden.unsupported_money("About $125", {golden.Decimal("140.20")}, previous)


def test_catalog_and_successful_routes_match_committed_oracle() -> None:
    points = build_points()
    catalog = json.loads(
        (golden.V2 / "eval/active/training/prompt-points.json").read_text()
    )
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


def test_planned_trials_and_empty_holdout_have_no_success_rate() -> None:
    cases = golden.load_cases()
    development = run.summary([], cases, trials_per_case=1)
    assert development["expected_trials"] == 5
    assert development["attempted_trials"] == 0
    assert development["pass_at_1"] is None
    assert development["pass_cubed"] is None
    assert development["pass_cubed_case_denominator"] is None
    assert not development["complete"]
    holdout = run.summary([], [case for case in cases if case.held_out])
    assert holdout["case_count"] == holdout["expected_trials"] == 0
    assert holdout["pass_at_1"] is None
    assert holdout["pass_cubed"] is None
    assert holdout["success_ci95"] is None


@pytest.mark.parametrize(
    "wording",
    [
        "Recent movement: **falling** by **$2.50 (27.9%)**.",
        "The current toll is **$2.50 (27.9%)** lower.",
        "It is $2.50 lower than the median.",
        "It is $2.50 (27.9%) below the median.",
        "The toll showed a $2.50 decrease.",
        "Recent movement: a **$2.50 (27.9%)** drop.",
        "The toll had a USD 2.50 reduction.",
    ],
)
def test_signed_comparison_does_not_match_absolute_value(wording: str) -> None:
    from decimal import Decimal

    assert golden.money(wording) == {Decimal("-2.50")}
    assert golden.money("$2.50 above the median") == {Decimal("2.50")}
    assert golden.money("The toll is $2.50, below the median") == {Decimal("2.50")}
    assert golden.money("The range is $2.50\u2013$3.50") == {
        Decimal("2.50"),
        Decimal("3.50"),
    }


def test_equivalent_falling_movement_keeps_financial_errors_failing() -> None:
    case = next(c for c in golden.load_cases() if c.id == "dev3-falling-gallows-quote")
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == case.id and e.label == "good"
    )
    assert not golden.grade_assertions(case, example.turns)
    for wording, unsupported in (
        ("The toll decreased by $2.50.", False),
        ("The toll showed a $2.50 decrease.", False),
        ("The toll showed a $2.50 increase.", True),
        ("The toll showed a $2.51 decrease.", True),
        ("The toll is $2.50.", True),
    ):
        turns = [turn.model_copy(deep=True) for turn in example.turns]
        turns[-1].response += " " + wording
        assert (
            "unsupported_money" in golden.grade_assertions(case, turns)
        ) is unsupported


@pytest.mark.parametrize(
    "case_id", ["dev3-two-comparable-weeks", "dev3-gallows-hybrid-salary"]
)
def test_approach_labels_do_not_make_duplicate_ids_interchangeable(
    case_id: str,
) -> None:
    from copy import deepcopy

    case = next(c for c in golden.load_cases() if c.id == case_id)
    fixture = golden.load_fixture(case.steps[0].fixture)
    golden.Replay(case).call(fixture.tool, fixture.input, [case.prompt])
    wrong = deepcopy(fixture.input)
    leg = wrong if fixture.tool == "get_current_toll_price" else wrong["outbound"]
    assert isinstance(leg, dict)
    endpoint = str(leg["destination_point_id"])
    assert endpoint.endswith("ND") and not endpoint.endswith("9ND")
    leg["destination_point_id"] = endpoint[:-2] + "9ND"
    with pytest.raises(ValueError, match="tool_arguments"):
        golden.Replay(case).call(fixture.tool, wrong, [case.prompt])


@pytest.mark.parametrize(
    "label",
    [
        "missing-history-denies-zero",
        "zero-denial-paraphrase",
        "rejected-price-quotation",
        "denial-then-asserted-zero",
        "missing-history-asserts-zero",
        "qualified-whole-dollar-restatement",
        "rounded-restatement-paraphrase",
        "incorrect-whole-dollar-restatement",
    ],
)
def test_semantic_money_classification_preserves_numeric_guard(label: str) -> None:
    example = next(e for e in run.development_examples() if e.label == label)
    case = next(c for c in golden.load_cases() if c.id == example.case_id)
    catalog: list[golden.MoneyMention] = []
    checks = golden.grade_assertions(case, example.turns, money_catalog=catalog)
    assert catalog and "unsupported_money" in checks
    assessment = run.GroundingAssessment(
        evidence="Synthetic semantic verdict passes; the numeric guard acts independently.",
        unmet_requirements=[],
        money=[
            run.MoneyInterpretation(
                id=m.id,
                evidence="Authored occurrence meaning for offline validation only.",
                kind="not_asserted"
                if m.id in example.non_asserted_money
                else "rounded"
                if m.id in example.rounded_money
                or label == "incorrect-whole-dollar-restatement"
                else "asserted",
            )
            for m in catalog
        ],
    )
    attempt = run.Attempt(
        id="test", case_id=case.id, trial=1, turns=example.turns, checks=checks
    )
    run.grounding_verdict(case, attempt, assessment, catalog)
    assert attempt.verdicts["grounding"].passed
    assert attempt.checks == example.expected_failures


@pytest.mark.parametrize("malformation", ["missing", "duplicate", "foreign"])
def test_money_classification_requires_exact_occurrence_coverage(
    malformation: str,
) -> None:
    example = next(
        e for e in run.development_examples() if e.label == "denial-then-asserted-zero"
    )
    case = next(c for c in golden.load_cases() if c.id == example.case_id)
    catalog: list[golden.MoneyMention] = []
    checks = golden.grade_assertions(case, example.turns, money_catalog=catalog)
    assert len(catalog) == 2 and catalog[0].amount == catalog[1].amount == "0"
    items = [
        run.MoneyInterpretation(id=m.id, kind="not_asserted", evidence="Test")
        for m in catalog
    ]
    if malformation == "missing":
        items.pop()
    elif malformation == "duplicate":
        items.append(items[0])
    else:
        items[-1] = run.MoneyInterpretation(
            id="foreign", kind="not_asserted", evidence="Test"
        )
    attempt = run.Attempt(
        id="test", case_id=case.id, trial=1, turns=example.turns, checks=checks
    )
    with pytest.raises(ValueError, match="invalid_money_classifications"):
        run.grounding_verdict(
            case,
            attempt,
            run.GroundingAssessment(
                evidence="Test", unmet_requirements=[], money=items
            ),
            catalog,
        )
    assert "unsupported_money" in attempt.checks
    assert not attempt.verdicts["grounding"].passed
