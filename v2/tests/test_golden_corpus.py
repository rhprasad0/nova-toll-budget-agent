"""Offline acceptance checks for the reviewed corpus contract, never model accuracy."""

import json
import shutil
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from strands.models import Model
from strands_evals.types.evaluation import EvaluationData
from strands_evals.types.trace import TraceLevelInput

from eval import golden


def test_full_corpus_is_network_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline corpus validation attempted network access")

    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    golden.validate()


def test_actor_schema_has_one_decision_and_cannot_discard_a_reply() -> None:
    assert set(golden.ActorReply.model_json_schema()["properties"]) == {"message"}
    assert not golden.ActorReply(message="Use 240 days.").stop
    assert golden.ActorReply(message=None).stop
    assert not golden.ActorReply(message="Use 240 days.", stop=True).stop


def test_actor_and_judge_keep_private_expectations_separate() -> None:
    case = golden.load_cases()[12]
    secret = "PRIVATE_ORACLE_SENTINEL"
    case.expected_assertion = secret
    case.provenance.note = secret
    case.coverage_tags = [secret]
    model = Mock(spec=Model)
    actor = golden.make_actor(case, model)
    assert not actor.agent.tool_names
    assert secret not in str(actor.agent.system_prompt)
    assert secret not in golden.actor_profile(case).model_dump_json()
    assert case.actor.goal in str(actor.agent.system_prompt)
    assert case.prompt in golden.actor_profile(case).context
    assert golden.judge_case(case).expected_assertion == secret
    # Judge prompt contains the reference, full conversation, and actual evidence.
    data = EvaluationData[str, str](input=case.prompt, expected_assertion=secret)
    parsed = TraceLevelInput.model_validate(
        {
            "span_info": {
                "session_id": "offline",
                "start_time": case.frozen_time,
                "end_time": case.frozen_time,
            },
            "agent_response": {"text": "See the earlier observation."},
            "session_history": [
                {"role": "user", "content": [{"text": "Earlier user question"}]},
                [
                    {
                        "tool_call": {
                            "name": "get_current_toll_price",
                            "arguments": {"origin_point_id": "greenway:1:entry:EB"},
                        },
                        "tool_result": {"content": '{"total_usd":"5.80"}'},
                    }
                ],
            ],
        }
    )
    prompt = golden.make_judge(model)._format_reference_prompt(  # pyright: ignore[reportPrivateUsage]
        parsed, data
    )
    assert secret in prompt
    assert "TOOL EVIDENCE AND CONVERSATION" in prompt
    assert "Earlier user question" in prompt
    assert "5.80" in prompt
    assert "greenway:1:entry:EB" in prompt


def test_replay_is_fresh_strict_and_does_not_share_evidence() -> None:
    case = golden.load_cases()[0]
    fixture = golden.load_fixture(case.steps[0].fixture)
    first = golden.Replay(case)
    second = golden.Replay(case)
    with pytest.raises(ValueError, match="tool_arguments"):
        first.call("get_annual_toll_ballpark", fixture.input, [case.prompt])
    assert first.index == 0
    answer = first.call(fixture.tool, fixture.input, [case.prompt])
    answer.result["total_usd"] = "9999.00"
    assert (
        second.call(fixture.tool, fixture.input, [case.prompt]).result["total_usd"]
        == "5.80"
    )
    with pytest.raises(ValueError, match="unexpected_call"):
        first.call(fixture.tool, fixture.input, [case.prompt])


def test_earliest_turn_is_mechanical_but_consent_is_semantic() -> None:
    for number in (4, 13, 14, 15, 16, 17, 18, 20, 23):
        case = golden.load_cases()[number - 1]
        fixture = golden.load_fixture(case.steps[0].fixture)
        with pytest.raises(ValueError, match="premature_call"):
            golden.match_step(case, 0, fixture.tool, fixture.input, [case.prompt])
        # Replay supplies evidence; semantic authorization still needs judging.
        assert (
            golden.match_step(
                case, 0, fixture.tool, fixture.input, [case.prompt, "I don't know."]
            )
            == fixture
        )


def test_weekday_order_is_equivalent_but_invalid_argument_types_fail() -> None:
    case = golden.load_cases()[11]
    fixture = golden.load_fixture(case.steps[0].fixture)
    arguments = deepcopy(fixture.input)
    weekdays = arguments["weekdays"]
    assert isinstance(weekdays, list)
    weekdays.reverse()
    result = golden.Replay(case).call(fixture.tool, arguments, [case.prompt])
    assert result.input == arguments
    assert result.result == fixture.result
    arguments["planned_annual_commute_days"] = 240.0
    with pytest.raises(ValueError, match="tool_arguments"):
        golden.Replay(case).call(fixture.tool, arguments, [case.prompt])


def test_labeled_rejection_examples_and_semantic_limits() -> None:
    examples = [
        golden.Example.model_validate(e)
        for e in json.loads((golden.ROOT / "examples.json").read_text())
    ]
    by_label = {e.label: e for e in examples}
    cases = {c.id: c for c in golden.load_cases()}
    for label, required in {
        "wrong-route": "tool_arguments",
        "premature-call": "premature_call",
        "incorrect-money": "unsupported_money",
        "unsupported-substitution": "unexpected_call",
        "missing-clarification": "premature_call",
        "unapproved-alternative": "premature_call",
    }.items():
        example = by_label[label]
        assert required in golden.grade_assertions(
            cases[example.case_id], example.turns
        )
    for label in (
        "swapped-financial-label",
        "missing-means-free",
        "silent-modeling",
        "missing-day-proposal",
        "missing-available-baseline",
    ):
        example = by_label[label]
        assert not golden.grade_assertions(cases[example.case_id], example.turns)
        assert example.expected is not None and not example.expected.outcome
    assert golden.money("$120k and $0.685 per mile") == {
        golden.Decimal("120000"),
        golden.Decimal("0.685"),
    }


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("duplicate", "duplicate case ID"),
        ("missing", "No such file"),
        ("contract", "validation error"),
        ("total", "fixture total"),
        ("hash", "hash drift"),
        ("leak", "oracle leakage"),
        ("endpoint", "unknown endpoint"),
        ("approval", "approval must identify"),
    ],
)
def test_invalid_corpus_is_rejected(tmp_path: Path, mutation: str, reason: str) -> None:
    root = tmp_path / "golden"
    shutil.copytree(golden.ROOT, root)
    rows = [
        json.loads(line) for line in (root / "cases.jsonl").read_text().splitlines()
    ]
    if mutation == "duplicate":
        rows[1]["id"] = rows[0]["id"]
    elif mutation == "missing":
        (root / "fixtures" / rows[0]["steps"][0]["fixture"]).unlink()
    elif mutation in ("contract", "endpoint", "total"):
        path = root / "fixtures" / rows[0]["steps"][0]["fixture"]
        fixture = json.loads(path.read_text())
        if mutation == "contract":
            fixture["input"]["unexpected"] = True
        elif mutation == "total":
            fixture["result"]["total_usd"] = "900.00"
        else:
            fixture["input"]["origin_point_id"] = "unlisted:origin"
            fixture["result"]["origin_point_id"] = "unlisted:origin"
        path.write_text(json.dumps(fixture))
    elif mutation == "hash":
        rows[0]["expected_assertion"] += " Changed difficulty."
    elif mutation == "leak":
        rows[0]["actor"]["facts"] += " Call get_current_toll_price."
    elif mutation == "approval":
        (root / "review.json").write_text(
            json.dumps(
                {
                    "status": "approved",
                    "corpus_sha256": "wrong",
                    "reviewer": "someone",
                    "evidence": "review-url",
                }
            )
        )
    (root / "cases.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        )
    )
    with pytest.raises((ValueError, FileNotFoundError), match=reason):
        golden.validate(root)


def test_modified_tool_evidence_and_extra_calls_cannot_pass() -> None:
    case = golden.load_cases()[0]
    example = golden.Example.model_validate(
        json.loads((golden.ROOT / "examples.json").read_text())[0]
    )
    altered = deepcopy(example.turns)
    altered[0].calls[0].result["total_usd"] = "9999.00"
    assert "tool_evidence" in golden.grade_assertions(case, altered)
    altered = deepcopy(example.turns)
    altered[0].calls.append(deepcopy(altered[0].calls[0]))
    assert "tool_budget" in golden.grade_assertions(case, altered)
    assert "missing_call" in golden.grade_assertions(case, [])


def test_markdown_currency_lists_preserve_real_negative_prices() -> None:
    case = golden.load_cases()[0]
    example = golden.Example.model_validate(
        json.loads((golden.ROOT / "examples.json").read_text())[0]
    )
    for amount in ("- $5.80", "  - USD 5.80", "- 5.80 dollars"):
        example.turns[0].response = amount + " is the fixed toll."
        assert not golden.grade_assertions(case, example.turns)
    for amount in ("-$5.80", "$-5.80", "\u2212$5.80", "- -$5.80"):
        example.turns[0].response = amount + " is the fixed toll."
        assert "unsupported_money" in golden.grade_assertions(case, example.turns)


def test_partial_history_includes_both_dtr_directions() -> None:
    result = golden.load_fixture("annual-partial.json").result
    facilities = result["facilities"]
    assert isinstance(facilities, list)
    dtr = next(f for f in facilities if isinstance(f, dict) and f["facility"] == "dtr")
    assert dtr["uses_current_fixed_rates"] is True
    assert dtr["uses_modeled"] is False
    assert dtr["scenarios"] == {
        q: {"daily_toll_usd": "12.00", "annual_toll_usd": "2880.00"}
        for q in ("p25", "p50", "p90")
    }
    scenarios = result["scenarios"]
    assert isinstance(scenarios, dict)
    assert [
        s["annual_toll_usd"] for s in scenarios.values() if isinstance(s, dict)
    ] == ["8544.00", "9504.00", "11424.00"]


def test_negated_zero_is_not_an_invented_price() -> None:
    case = golden.load_cases()[23]
    example = next(
        golden.Example.model_validate(item)
        for item in json.loads((golden.ROOT / "examples.json").read_text())
        if item["case_id"] == case.id and item["label"] == "good"
    )
    for wording in (
        "The missing toll is not $0.00.",
        "Do not treat the missing toll as $0.00.",
        "The missing toll is **not $0.00**.",
        "The missing toll data is **not treated as $0**.",
        "Missing data is never treated as $0.00.",
        "Historical toll cost: Unavailable—not assumed to be $0.",
    ):
        turns = deepcopy(example.turns)
        turns[-1].response += " " + wording
        assert "unsupported_money" not in golden.grade_assertions(case, turns)
        turns[-1].response += " The toll is $0.00."
        assert "unsupported_money" in golden.grade_assertions(case, turns)


def test_salary_suggestions_do_not_pass_the_current_contract() -> None:
    examples = [
        golden.Example.model_validate(e)
        for e in json.loads((golden.ROOT / "examples.json").read_text())
    ]
    suggestions = [
        e
        for e in examples
        if e.case_id == "annual-salary-range"
        and e.label
        in {
            "good-midpoint-choice",
            "good-income-choices",
            "good-income-range-example",
            "good-income-choice-question",
            "good-income-bullets",
        }
    ]
    assert suggestions
    for example in suggestions:
        assert example.expected is not None and not example.expected.rules


def test_annual_financial_cross_fields_are_not_just_schema_checked(
    tmp_path: Path,
) -> None:
    root = tmp_path / "corpus"
    (root / "fixtures").mkdir(parents=True)
    fixture = json.loads((golden.ROOT / "fixtures/annual-fixed.json").read_text())
    fixture["result"]["scenarios"]["p50"]["annual_total_tolled_commute_cost_usd"] = (
        "1.00"
    )
    (root / "fixtures/broken.json").write_text(json.dumps(fixture))
    with pytest.raises(ValueError, match="scenario arithmetic"):
        golden.load_fixture("broken.json", root)


def test_behavioral_groups_cannot_cross_splits() -> None:
    cases = deepcopy(golden.load_cases())
    reserved = next(c for c in cases if c.held_out)
    development = next(c for c in cases if not c.held_out)
    reserved.split_group = development.split_group
    with pytest.raises(ValueError, match="scenario group crosses"):
        golden.validate_coverage(cases)


def test_one_sample_cannot_imply_a_percentile_spread(tmp_path: Path) -> None:
    fixture = golden.load_fixture("annual2-coverage-one-pair-reserved.json")
    root = tmp_path / "corpus"
    (root / "fixtures").mkdir(parents=True)
    altered = fixture.model_dump(mode="json")
    altered["result"]["scenarios"]["p90"]["daily_toll_usd"] = "24.00"
    (root / "fixtures/broken.json").write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="one sampled pair"):
        golden.load_fixture("broken.json", root)


def test_current_route_failure_fixtures_validate_request_alignment(
    tmp_path: Path,
) -> None:
    fixture = next(
        golden.load_fixture(s.fixture)
        for c in golden.load_cases()
        if c.coverage_family == "current_i95"
        for s in c.steps
        if golden.load_fixture(s.fixture).result.get("point_ids")
    )
    root = tmp_path / "corpus"
    (root / "fixtures").mkdir(parents=True)
    altered = fixture.model_dump(mode="json")
    altered["input"]["origin_point_id"] = "airport_iad"
    if altered["result"]["point_ids"][0] == "airport_iad":
        altered["input"]["origin_point_id"] = "i95:206NO"
    (root / "fixtures/broken.json").write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="requested origin"):
        golden.load_fixture("broken.json", root)


def test_divergent_trip_infers_direction_and_requires_confirmation() -> None:
    case = next(c for c in golden.load_cases() if c.id == "annual-confirm-divergent")
    assert "northbound" not in case.prompt.lower()
    fixture = golden.load_fixture(case.steps[0].fixture)
    outbound = fixture.input["outbound"]
    assert isinstance(outbound, dict)
    assert outbound["origin_point_id"] == "i95:206NO"
    replay = golden.Replay(case)
    with pytest.raises(ValueError, match="premature_call"):
        replay.call(fixture.tool, fixture.input, [case.prompt])
    assert replay.call(fixture.tool, fixture.input, [case.prompt, "Yes, combine them."])


def test_one_way_current_actors_do_not_request_return_trips() -> None:
    cases = {c.id: c for c in golden.load_cases()}
    for case_id in ("greenway-current", "current-tool-error"):
        facts = cases[case_id].actor.facts
        assert "returning the other way" not in facts
        assert "one-way trip only; do not ask for a return trip" in facts
    assert "returning the other way" in cases["annual-fixed"].actor.facts


def test_origin_correction_actor_names_both_endpoints() -> None:
    case = next(c for c in golden.load_cases() if c.id == "greenway-origin-correction")
    rules = " ".join(case.actor.follow_up_rules)
    assert "enter at Battlefield Parkway instead of Leesburg Bypass" in rules
    assert "still going to Route 28" in rules


@pytest.mark.parametrize(
    "text,amounts",
    [
        ("Falling, down **$2.00 (47.1%)**; toll $2.25", {"-2.00", "2.25"}),
        ("decreased by $2.00; increased by $3.00", {"-2.00", "3.00"}),
        ("a reduction of __$2.00__; up `$3.00`", {"-2.00", "3.00"}),
        ("falling by $2.00; toll $2.25", {"-2.00", "2.25"}),
        ("down *$2.00*; up *$3.00*", {"-2.00", "3.00"}),
        ("down _$2.00_; toll _$2.25_", {"-2.00", "2.25"}),
        ("dropped $2.00; rose $3.00", {"-2.00", "3.00"}),
        ("down $-2.00; up \u2212$3.00", {"-2.00", "-3.00"}),
        ("- $2.00\nDown the road, the toll is $3.00", {"2.00", "3.00"}),
        ("up $2.00; down $9.99", {"2.00", "-9.99"}),
    ],
)
def test_directional_money_preserves_sign_and_other_amounts(
    text: str, amounts: set[str]
) -> None:
    assert golden.money(text) == {golden.Decimal(a) for a in amounts}


def test_reviewed_calibration_controls_and_reserved_boundary() -> None:
    from eval import golden_run

    cases = {c.id: c for c in golden.load_cases()}
    examples = golden_run.development_examples()
    reviewed = [e for e in examples if e.label.startswith("review-")]
    assert len(reviewed) == 7
    assert not any(e.case_id == "current-past-price" for e in examples)
    for example in reviewed:
        assert golden.grade_assertions(cases[example.case_id], example.turns) == (
            example.expected_failures
        )


@pytest.mark.parametrize(
    "wording", ["falling by $2.00", "down *$2.00*", "down _$2.00_"]
)
def test_downward_renderings_do_not_invent_money(wording: str) -> None:
    case = next(c for c in golden.load_cases() if c.id == "current-movement-falling")
    example = next(
        golden.Example.model_validate(item)
        for item in json.loads((golden.ROOT / "examples.json").read_text())
        if item["case_id"] == case.id and item["label"] == "review-down-wording-good"
    )
    turns = deepcopy(example.turns)
    turns[-1].response = wording
    assert "unsupported_money" not in golden.grade_assertions(case, turns)
    turns[-1].response = wording.replace("2.00", "9.99")
    assert "unsupported_money" in golden.grade_assertions(case, turns)


def test_semantic_controls_preserve_financial_checks_and_material_failures() -> None:
    from eval import golden_run

    cases = {c.id: c for c in golden.load_cases()}
    controls = [
        e for e in golden_run.development_examples() if e.label.startswith("semantic-")
    ]
    assert len(controls) == 4
    assert (
        sum(
            bool(e.expected and all(e.expected.model_dump().values())) for e in controls
        )
        == 2
    )
    for example in controls:
        case = cases[example.case_id]
        assert not case.held_out
        assert example.actor_validity == "valid"
        assert golden.grade_assertions(case, example.turns) == []
        corrupted = deepcopy(example.turns)
        corrupted[-1].response += " The toll is $9999.99."
        assert "unsupported_money" in golden.grade_assertions(case, corrupted)
    closure = next(e for e in controls if e.label == "semantic-closure-paraphrase")
    assert not closure.turns[-1].calls
    assert "###" not in closure.turns[-1].response
    for example in controls:
        if example.label in {
            "semantic-closure-fabricated-proof",
            "semantic-annual-false-tax-entitlement",
        }:
            assert example.expected is not None
            assert not any(example.expected.model_dump().values())
