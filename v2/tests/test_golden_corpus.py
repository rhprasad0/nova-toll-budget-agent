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


def test_clarification_and_consent_require_a_later_user_reply() -> None:
    for number in (4, 13, 14, 15, 16, 17, 18, 20, 23):
        case = golden.load_cases()[number - 1]
        fixture = golden.load_fixture(case.steps[0].fixture)
        with pytest.raises(ValueError, match="premature_call"):
            golden.match_step(case, 0, fixture.tool, fixture.input, [case.prompt])
        with pytest.raises(ValueError, match="missing_user_fact"):
            golden.match_step(
                case, 0, fixture.tool, fixture.input, [case.prompt, "I don't know."]
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
        assert example.semantic_verdict == "INCORRECT"
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
        ("i95", "I-95 direction"),
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
    elif mutation in ("contract", "i95", "total"):
        path = root / "fixtures" / rows[0]["steps"][0]["fixture"]
        fixture = json.loads(path.read_text())
        if mutation == "contract":
            fixture["input"]["unexpected"] = True
        elif mutation == "total":
            fixture["result"]["total_usd"] = "900.00"
        else:
            fixture["input"]["origin_point_id"] = "i95:206NO"
            fixture["result"]["origin_point_id"] = "i95:206NO"
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


@pytest.mark.parametrize(
    "label",
    [
        "good-income-choices",
        "good-income-range-example",
        "good-income-choice-question",
        "good-income-bullets",
    ],
)
def test_income_choices_require_consent_and_cannot_hide_other_money(label: str) -> None:
    case = next(c for c in golden.load_cases() if c.id == "annual-salary-range")
    example = next(
        golden.Example.model_validate(e)
        for e in json.loads((golden.ROOT / "examples.json").read_text())
        if e["case_id"] == case.id and e["label"] == label
    )
    assert not golden.grade_assertions(case, example.turns)
    for response in (
        "Your salary is $120,000.",
        "Please choose one income: $110,000, $125,000, or $130,000.",
        "Would you like to use $110,000, $125,000, or $130,000?",
        "Please provide one gross annual income estimate between $110,000 and $130,000—for example, $125,000.",
        "I will use $120,000 as your annual income.",
        "Which figure should I use?\n\n- $110,000\n- $125,000\n- $130,000\n",
        "Your income is:\n\n- $110,000\n- $120,000\n- $130,000\n",
        "Which figure should I use?\n\n- $110,000\n- The toll is $120,000\n- $130,000\n",
        example.turns[0].response + " The toll is $120,000.",
    ):
        turns = deepcopy(example.turns)
        turns[0].response = response
        assert "unsupported_money" in golden.grade_assertions(case, turns)
    turns = deepcopy(example.turns)
    turns[0].calls = turns[1].calls
    turns[1].calls = []
    assert "premature_call" in golden.grade_assertions(case, turns)
    assert "unsupported_money" in golden.grade_assertions(case, turns)


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
