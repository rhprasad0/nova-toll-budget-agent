"""Small contrasts for mechanical grading and assistant-only disclosure evidence."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from strands.models import Model

from eval import golden
from eval import golden_run as run
from tests.golden_support import case as golden_case

pytestmark = pytest.mark.usefixtures("golden_test_data")


def test_rules_reuse_replay_for_rejected_arguments_and_discovery() -> None:
    case = golden_case(22)
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == case.id and e.label == "good"
    )
    attempt = run.Attempt(
        id="discovery", case_id=case.id, trial=1, turns=deepcopy(example.turns)
    )
    assert attempt.turns[0].calls[0].result.get("error")
    assert run.mechanical_rules(case, attempt) == []
    wrong = deepcopy(attempt.turns[-1].calls[-1].input)
    attempt.rejected_tools = [
        golden.RejectedCall(
            turn=1,
            name=attempt.turns[0].calls[0].name,
            input=wrong,
            result={},
            reason="tool_arguments",
        )
    ]
    attempt.attempted_tools = [
        {"turn": 1, "name": attempt.rejected_tools[0].name, "input": wrong}
    ] + [
        {"turn": turn, "name": call.name, "input": call.input}
        for turn, response in enumerate(attempt.turns, 1)
        for call in response.calls
    ]
    # Rejection in turn 1 does not consume the step needed by the later selection.
    failures = run.mechanical_rules(case, attempt)
    assert len(failures) == 1
    assert '"error": "tool_arguments"' in failures[0].evidence
    attempt.attempted_tools = []
    with pytest.raises(ValueError, match="ambiguous_tool_order"):
        run.mechanical_rules(case, attempt)


def test_guard_request_order_includes_rejected_call_after_success() -> None:
    case = golden_case(1)
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == case.id and e.label == "good"
    )
    attempt = run.Attempt(
        id="guard-order", case_id=case.id, trial=1, turns=deepcopy(example.turns)
    )
    assert len(case.steps) == 1
    call = attempt.turns[0].calls[0]
    attempt.rejected_tools = [
        golden.RejectedCall(
            turn=1, name=call.name, input=call.input, result={}, reason="tool_budget"
        )
    ]
    request = {"turn": 1, "name": call.name, "input": call.input}
    attempt.attempted_tools = [request]  # Guard cancellation precedes tool execution.
    attempt.requested_tools = [request, request]
    failures = run.mechanical_rules(case, attempt)
    assert len(failures) == 1
    assert json.loads(failures[0].evidence)["error"] == "unexpected_call"
    attempt.requested_tools = []
    with pytest.raises(ValueError, match="ambiguous_tool_order"):
        run.mechanical_rules(case, attempt)


def test_mechanical_findings_isolate_wrong_id_and_ignore_weekday_order() -> None:
    case = golden_case(22)
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == case.id and e.label == "good"
    )
    attempt = run.Attempt(
        id="route", case_id=case.id, trial=1, turns=deepcopy(example.turns)
    )
    call = attempt.turns[-1].calls[0]
    weekdays = call.input["weekdays"]
    assert isinstance(weekdays, list)
    call.input["weekdays"] = list(reversed(weekdays))
    assert run.mechanical_rules(case, attempt) == []
    outbound = call.input["outbound"]
    assert isinstance(outbound, dict)
    permitted = outbound["destination_point_id"]
    outbound["destination_point_id"] = f"{permitted}9"
    findings = run.mechanical_rules(case, attempt)
    assert len(findings) == 1
    assert json.loads(findings[0].evidence) == {
        "turn": 2,
        "error": "tool_arguments",
        "differences": [
            {
                "field": "outbound.destination_point_id",
                "actual": f"{permitted}9",
                "permitted": permitted,
            }
        ],
    }
    assert run.argument_differences({"value": None}, {}) == [
        {
            "field": "value",
            "actual": None,
            "permitted": None,
            "actual_present": True,
            "permitted_present": False,
        }
    ]
    assert run.argument_differences({}, {"value": None})[0]["actual_present"] is False


def test_outcome_places_original_answers_beside_disclosure_requirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = golden_case(1)
    answer = "**Assumed vehicle cost:** $0.685 per straight-line tolled mile.\nNot individualized."
    attempt = run.Attempt(
        id="answers",
        case_id=case.id,
        trial=1,
        turns=[golden.Turn(user="USER ONLY", response=answer, calls=[])],
    )
    evaluator = Mock(
        side_effect=[
            SimpleNamespace(
                structured_output=run.OutcomeAssessment(
                    disclosures=[],
                    outcome=run.RequirementAssessment(
                        evidence="Satisfied", unmet_requirements=[]
                    ),
                    actor_validity=run.ActorAssessment(
                        status="valid", evidence="Consistent"
                    ),
                )
            ),
            SimpleNamespace(
                structured_output=run.ActorAssessment(
                    status="valid", evidence="Confirmed"
                )
            ),
        ]
    )
    monkeypatch.setattr(run, "Agent", Mock(return_value=evaluator))
    run.assess_outcome(
        case, attempt, Mock(spec=Model), "contract", "FULL TOOL EVIDENCE"
    )
    prompt = evaluator.call_args_list[0].args[0]
    block = prompt.split("ASSISTANT ANSWER LINES", 1)[1].split(
        "DISCLOSURE ASSESSMENT", 1
    )[0]
    assert (
        all(json.dumps(line) in block for line in answer.splitlines())
        and "USER ONLY" not in block
        and "FULL TOOL EVIDENCE" not in block
    )
    assert (
        prompt.index("COMPILED DISCLOSURE REQUIREMENTS")
        < prompt.index("ASSISTANT ANSWER LINES")
        < prompt.index("FULL TOOL EVIDENCE")
    )


@pytest.mark.parametrize("fixed_reference", [False, True])
def test_actor_confirmation_rejects_wrong_driver_facts_independently(
    monkeypatch: pytest.MonkeyPatch, fixed_reference: bool
) -> None:
    case = golden_case(1)
    attempt = run.Attempt(
        id="wrong-origin",
        case_id=case.id,
        trial=1,
        turns=[golden.Turn(user="Wrong origin", response="Correct price", calls=[])],
        actor_validity=run.ActorAssessment(status="valid", evidence="Combined pass"),
        verdicts={"outcome": run.Verdict(passed=True, evidence="Application answer")},
    )
    evaluator = Mock(
        return_value=SimpleNamespace(
            structured_output=run.ActorAssessment(
                status="invalid",
                evidence="Destination approach substituted for supplied origin",
            )
        )
    )
    factory = Mock(return_value=evaluator)
    monkeypatch.setattr(run, "Agent", factory)
    run.confirm_actor_validity(
        case, attempt, Mock(spec=Model), fixed_reference=fixed_reference
    )
    assert (
        attempt.actor_validity is not None
        and attempt.actor_validity.status == "invalid"
    )
    assert attempt.verdicts["outcome"].passed
    evidence = json.loads(attempt.actor_validity.evidence)
    assert evidence["combined"]["status"] == "valid"
    assert evidence["confirmation"]["status"] == "invalid"
    data = json.loads(evaluator.call_args.args[0])
    assert data["private_driver_profile"] == golden.actor_profile(case).model_dump(
        mode="json"
    )
    assert data["delivered_turns"] == [
        {"turn": 1, "user": "Wrong origin", "assistant": "Correct price"}
    ]
    assert "calls" not in evaluator.call_args.args[0]
    assert "including its initial request" in factory.call_args.kwargs["system_prompt"]
    assert (
        "do not invent outside geography" in factory.call_args.kwargs["system_prompt"]
    )
    assert (
        "Only corrections or changes explicitly supplied in the profile"
        in factory.call_args.kwargs["system_prompt"]
    )
    assert "cannot be reassigned entirely" in factory.call_args.kwargs["system_prompt"]
    assert (
        run.FIXED_REFERENCE_PROMPT in factory.call_args.kwargs["system_prompt"]
    ) is fixed_reference
    run.confirm_actor_validity(case, attempt, Mock(spec=Model))
    assert evaluator.call_count == 1  # A rejected actor cannot be rehabilitated.


@pytest.mark.parametrize("period,expected", [("peak", 2), ("off_peak", 1)])
def test_schedule_disclosure_applicability(period: str, expected: int) -> None:
    call = golden.Call(
        name="get_current_toll_price",
        input={},
        result={
            "components": [
                {
                    "source_kind": "schedule_derived",
                    "facility": "greenway",
                    "rate_period": period,
                }
            ]
        },
    )
    attempt = run.Attempt(
        id="schedule",
        case_id="synthetic",
        trial=1,
        turns=[golden.Turn(user="Price?", response="Published rate.", calls=[call])],
    )
    requirements = run.disclosure_requirements(attempt)
    assert len(requirements) == expected
    assert any(key.endswith("published_source") for key in requirements)
    assert any(key.endswith(".peak") for key in requirements) == (period == "peak")


def test_unavailable_annual_baseline_still_requires_vehicle_assumption() -> None:
    call = golden.Call(
        name="get_annual_toll_ballpark",
        input={},
        result={
            "sample_status": "no_complete_paired_days",
            "assumptions": {"vehicle_cost_per_mile_usd": "0.685"},
            "vehicle_cost": {"annual_usd": "500.00"},
        },
    )
    attempt = run.Attempt(
        id="baseline",
        case_id="synthetic",
        trial=1,
        turns=[golden.Turn(user="Annual?", response="No toll history.", calls=[call])],
    )
    assert list(run.disclosure_requirements(attempt)) == [
        "turn_1.call_1.vehicle_assumption"
    ]


@pytest.mark.parametrize(
    "line_ids,passed",
    [
        ([], False),
        (["turn_1.line_1"], True),
    ],
)
def test_disclosure_missing_or_supplied_in_earlier_answer(
    line_ids: list[str], passed: bool
) -> None:
    turns = [
        golden.Turn(
            user="Estimate",
            response="Assuming 68.5 cents per tolled mile, using straight-line distance.",
            calls=[],
        ),
        golden.Turn(user="Thanks", response="You're welcome.", calls=[]),
    ]
    assessment = run.OutcomeAssessment(
        disclosures=[
            run.DisclosureAssessment(requirement_id="vehicle", line_ids=line_ids)
        ],
        outcome=run.RequirementAssessment(
            evidence="Other requirements satisfied.", unmet_requirements=[]
        ),
        actor_validity=run.ActorAssessment(evidence="Consistent user.", status="valid"),
    )
    assert (
        run.disclosure_verdict(
            assessment, {"vehicle": "Disclose the assumed vehicle rate."}, turns
        ).passed
        == passed
    )


@pytest.mark.parametrize(
    "defect",
    [
        "tool_only",
        "user_only",
        "fabricated",
        "missing_id",
        "duplicate_id",
        "unknown_id",
    ],
)
def test_invalid_disclosure_evidence_is_a_measurement_error(defect: str) -> None:
    turn = golden.Turn(
        user="Assume $0.685 per mile",
        response="Vehicle cost is $10.",
        calls=[
            golden.Call(
                name="get_annual_toll_ballpark",
                input={},
                result={"assumption": "$0.685 per mile"},
            )
        ],
    )
    item = run.DisclosureAssessment(
        requirement_id="vehicle",
        line_ids=["FABRICATED" if defect == "fabricated" else f"{defect}.line_1"],
    )
    disclosures = (
        []
        if defect == "missing_id"
        else [item, item]
        if defect == "duplicate_id"
        else [item]
    )
    if defect == "unknown_id":
        item.requirement_id = "not_applicable"
    assessment = run.OutcomeAssessment(
        disclosures=disclosures,
        outcome=run.RequirementAssessment(
            evidence="Claimed support.", unmet_requirements=[]
        ),
        actor_validity=run.ActorAssessment(evidence="Consistent user.", status="valid"),
    )
    with pytest.raises(ValueError, match="invalid_disclosure_"):
        run.disclosure_verdict(
            assessment, {"vehicle": "Disclose vehicle assumption."}, [turn]
        )


@pytest.mark.parametrize("locations", [[3], [1, 3]])
def test_quote_locations_are_derived_and_repeated_answers_preserved(
    locations: list[int],
) -> None:
    quote = "Vehicle cost assumes 68.5 cents per straight-line tolled mile."
    turns = [
        golden.Turn(
            user=quote,
            response=quote if index in locations else "Other answer.",
            calls=[],
        )
        for index in range(1, 4)
    ]
    assessment = run.OutcomeAssessment(
        disclosures=[
            run.DisclosureAssessment(
                requirement_id="vehicle",
                line_ids=[f"turn_{index}.line_1" for index in locations],
            )
        ],
        outcome=run.RequirementAssessment(
            evidence="Other requirements satisfied.", unmet_requirements=[]
        ),
        actor_validity=run.ActorAssessment(evidence="Consistent user.", status="valid"),
    )
    verdict = run.disclosure_verdict(
        assessment, {"vehicle": "Disclose vehicle assumption."}, turns
    )
    assert verdict.passed
    assert json.loads(verdict.evidence)["disclosures"][0]["quotes"] == [
        {"line_id": f"turn_{index}.line_1", "quote": quote} for index in locations
    ]


def test_calibration_preserves_bad_quote_and_usage_then_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = next(
        e
        for e in run.development_examples()
        if e.case_id == golden_case(22).id and e.label == "good"
    )
    monkeypatch.setattr(run, "development_examples", lambda: [example])
    evaluator = Mock()

    def judge(
        case: golden.GoldenCase,
        attempt: run.Attempt,
        journal: run.Journal,
        *,
        fixed_reference: bool = False,
    ) -> None:
        requirements = run.disclosure_requirements(attempt)
        assert requirements
        assessment = run.OutcomeAssessment(
            disclosures=[
                run.DisclosureAssessment(
                    requirement_id=key,
                    line_ids=["FABRICATED DISCLOSURE"],
                )
                for key in requirements
            ],
            outcome=run.RequirementAssessment(
                evidence="Raw model claims disclosure.", unmet_requirements=[]
            ),
            actor_validity=run.ActorAssessment(
                evidence="Consistent user.", status="valid"
            ),
        )
        reserve = journal.reserve(attempt, "judge", 100)
        journal.finish(
            attempt, "judge", reserve, {"inputTokens": 100, "outputTokens": 20}, 0.1
        )
        evaluator.return_value = SimpleNamespace(structured_output=assessment)
        monkeypatch.setattr(run, "Agent", Mock(return_value=evaluator))
        run.assess_outcome(
            case,
            attempt,
            Mock(spec=Model),
            "contract",
            "conversation",
            fixed_reference=fixed_reference,
        )

    monkeypatch.setattr(run, "judge", judge)
    journal = run.Journal(tmp_path / "bad-citation", 25)
    with ThreadPoolExecutor(max_workers=1) as pool:
        row = run.calibrate(journal, pool)[0]
    assert row["status"] == "infrastructure" and not row["measurement_complete"]
    assert "FABRICATED DISCLOSURE" in row["verdicts"]["outcome"]["evidence"]
    assert row["measurements"][0]["complete"] and journal.spent > 0
    assert journal.stop_requested and not journal.unknown_usage
    assert evaluator.call_count == 1
    with pytest.raises(run.StopRun):
        journal.reserve(
            run.Attempt(id="next", case_id=example.case_id, trial=1), "judge", 100
        )


def test_disclosure_lines_preserve_markdown_and_multiline_context() -> None:
    text = "**Published rates**\n\n| Source | Price |\n| Fixed schedule | **$8.00** |"
    turns = [golden.Turn(user="Ignore this", response=text, calls=[])]
    lines = run.assistant_lines(turns)
    assert list(lines) == ["turn_1.line_1", "turn_1.line_3", "turn_1.line_4"]
    assessment = run.OutcomeAssessment(
        disclosures=[
            run.DisclosureAssessment(requirement_id="source", line_ids=list(lines))
        ],
        outcome=run.RequirementAssessment(
            evidence="Supported source.", unmet_requirements=[]
        ),
        actor_validity=run.ActorAssessment(evidence="Valid user.", status="valid"),
    )
    verdict = run.disclosure_verdict(assessment, {"source": "Published source"}, turns)
    assert verdict.passed
    assert [
        q["quote"] for q in json.loads(verdict.evidence)["disclosures"][0]["quotes"]
    ] == [line for line in text.splitlines() if line]
    assessment.outcome.unmet_requirements.append(
        run.UnmetRequirement(
            requirement="No contradictions",
            evidence="Another assertion denies the source.",
        )
    )
    assert not run.disclosure_verdict(
        assessment, {"source": "Published source"}, turns
    ).passed
