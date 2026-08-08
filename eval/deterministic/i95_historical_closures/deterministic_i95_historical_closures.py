"""Code-graded live regression for Issue #17's historical I-95 closures.

The grader is deterministic; the live TollChat invocation is stochastic.
``--check`` only exercises the loader and grader against synthetic traces.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from strands.types.content import Message, Messages  # noqa: E402
from strands_evals import Case, Experiment  # noqa: E402
from strands_evals.evaluators import Evaluator  # noqa: E402
from strands_evals.extractors import tools_use_extractor  # noqa: E402
from strands_evals.types.evaluation import (  # noqa: E402
    EvaluationData,
    EvaluationOutput,
)
from strands_evals.types.trace import AgentInvocationSpan, Session  # noqa: E402

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402

_CASES_PATH = Path(__file__).resolve().parent / "test-cases.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
_MONEY_RE = re.compile(r"\$\s*\d|\b\d+\.\d{2}\b|\b(?:USD|dollars?)\b", re.I)
_UNAVAILABLE_RE = re.compile(r"\b(?:unavailable|cannot\s+(?:provide|price))\b", re.I)
_GENERAL_PURPOSE_RE = re.compile(
    r"\b(?:I-95\s+general[- ]purpose lanes|general[- ]purpose lanes\s+"
    r"(?:on|of)\s+(?:the\s+)?I-95)\b",
    re.I,
)
_URL_RE = re.compile(r"\b(?:https?://|www\.)", re.I)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.I)
_PHONE_RE = re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
_RECORDS_RE = re.compile(
    r"\b(?:incident (?:id|number)|archiv(?:e|al)|public records?|"
    r"record(?:s)? (?:are|is|available)|customer service|communications office)\b",
    re.I,
)
_REIMBURSEMENT_RE = re.compile(
    r"\b(?:reimburse(?:ment|d)?|refund|compensation|"
    r"(?:file|submit|pursue|make)\s+(?:a\s+)?claim|"
    r"claim\s+(?:advice|documentation|process|procedure|form|eligibility|outcome))\b",
    re.I,
)
_SOURCE_FOLLOWUP_RE = re.compile(
    r"\b(?:proof|evidence|(?:official|closure)\s+(?:documentation|notice))\b|"
    r"\b(?:verify|confirm)\w*\b.{0,40}\bclosure\b|"
    r"\bclosure\b.{0,40}\b(?:verify|confirm)\w*\b",
    re.I,
)
_AFFILIATION_RE = re.compile(
    r"\b(?:tollchat|we)\s+(?:are|is)\s+(?:an?\s+)?"
    r"(?:official|affiliated|a partner|a representative)\b.*\b(?:VDOT|Virginia 511)\b",
    re.I,
)
_SOURCE_REFERRAL = (
    "The registered pricing tool reported the Express Lanes unavailable for the "
    "requested trip and time, but it did not provide an official closure notice or "
    "source metadata. TollChat is not affiliated with VDOT or Virginia 511. You can "
    "verify through official VDOT or Virginia 511 channels."
)
_MONETARY_FIELDS = {"legs", "price_usd", "total_usd", "tolls"}


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row: dict[str, Any] = json.loads(line)
        cases.append(
            Case[str, str](
                name=row["id"],
                input=row["conversation"][0]["content"],
                expected_trajectory=[
                    call["tool"] for call in row["expected_trajectory"][0]["calls"]
                ],
                metadata=row,
            )
        )
    return cases


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _report_passed(test_passes: list[bool]) -> bool:
    return all(test_passes)


def _turns(evaluation_case: EvaluationData[str, str]) -> list[dict[str, Any]]:
    trajectory = evaluation_case.actual_trajectory
    return (
        cast(list[dict[str, Any]], trajectory) if isinstance(trajectory, list) else []
    )


def _trace_messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        messages = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [message for trace in traces for message in walk(trace)]


def _extract_tool_calls(messages: Messages) -> list[dict[str, Any]]:
    return tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        messages
    )


def _tool_result(call: dict[str, Any]) -> dict[str, Any] | None:
    value = call.get("tool_result")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    response = agent(str(case.input))
    summary: dict[str, Any] = response.metrics.get_summary()
    traces = cast(list[dict[str, Any]], summary.get("traces", []))
    calls = _extract_tool_calls(_trace_messages(traces))
    return {"output": str(response), "trajectory": [{"calls": calls}]}


class ClosureTraceEvaluator(Evaluator[str, str]):
    """Require the access check and its captured unavailable pricing result."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        metadata: dict[str, Any] = evaluation_case.metadata or {}
        turns = _turns(evaluation_case)
        calls = (
            cast(list[dict[str, Any]], turns[0].get("calls", []))
            if len(turns) == 1
            else []
        )
        return evaluate_closure_calls(calls, metadata)


def evaluate_closure_calls(
    calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Grade captured calls against one historical closure fixture."""
    expected_calls = metadata["expected_trajectory"][0]["calls"]
    if len(calls) != len(expected_calls) or [call.get("name") for call in calls] != [
        expected["tool"] for expected in expected_calls
    ]:
        return _result(
            False,
            f"expected calls {[expected['tool'] for expected in expected_calls]}, got "
            f"{[call.get('name') for call in calls]}",
            "tool_mismatch",
        )
    if any(
        not isinstance(call.get("input"), dict)
        or not all(
            call["input"].get(key) == value for key, value in expected["input"].items()
        )
        for call, expected in zip(calls, expected_calls, strict=True)
    ):
        return _result(
            False,
            "tool arguments did not match fixture",
            "input_mismatch",
        )
    access = _tool_result(calls[0])
    if access is None:
        return _result(False, "missing or invalid access result", "bad_access_result")
    if access != expected_calls[0]["expected_result"]:
        return _result(
            False, f"unexpected access result: {access}", "wrong_access_result"
        )

    captured = _tool_result(calls[1])
    if captured is None:
        return _result(False, "missing or invalid captured tool result", "bad_result")
    error = str(captured.get("error", ""))
    expected_od = str(metadata["expected_od_pair_id"])
    expected_status = str(metadata["expected_link_status"])
    if expected_od not in error or expected_status not in error:
        return _result(False, f"unexpected closure result: {captured}", "wrong_result")
    forbidden = sorted(_MONETARY_FIELDS & captured.keys())
    if forbidden:
        return _result(
            False,
            f"unavailable result exposed monetary fields: {forbidden}",
            "fare_exposed",
        )
    return _result(True, "exact call returned the expected closure", "closed")


class ClosureResponseEvaluator(Evaluator[str, str]):
    """Require an unavailable answer with no invented fare."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        response = str(evaluation_case.actual_output or "")
        if not _UNAVAILABLE_RE.search(response):
            return _result(
                False, "response did not report unavailability", "not_refused"
            )
        if not _GENERAL_PURPOSE_RE.search(response):
            return _result(
                False,
                "response did not suggest the I-95 general-purpose lanes",
                "alternative_missing",
            )
        if _MONEY_RE.search(response):
            return _result(
                False, "response quoted a fare for a closed lane", "fare_quoted"
            )
        return _result(True, "response reported unavailable with no fare", "refused")


class ClosureSourceResponseEvaluator(Evaluator[str, str]):
    """Require a grounded referral when no source metadata was returned."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        trajectory = evaluation_case.actual_trajectory
        responses = [str(evaluation_case.actual_output or "")]
        if isinstance(trajectory, Session):
            invocations = [
                span
                for trace in trajectory.traces
                for span in trace.spans
                if isinstance(span, AgentInvocationSpan)
            ]
            if len(invocations) < 2:
                return _result(
                    False,
                    "simulation omitted the source follow-up",
                    "source_followup_missing",
                )
            if len(invocations) > 2:
                return _result(
                    False,
                    "simulation exceeded the two-turn contract",
                    "unexpected_turn_count",
                )
            followup_prompt = invocations[1].user_prompt
            if _REIMBURSEMENT_RE.search(
                followup_prompt
            ) or not _SOURCE_FOLLOWUP_RE.search(followup_prompt):
                return _result(
                    False,
                    "simulation did not ask for official closure proof",
                    "source_followup_invalid",
                )
            if any(
                _REIMBURSEMENT_RE.search(span.agent_response) for span in invocations
            ):
                return _result(
                    False, "response gave reimbursement advice", "reimbursement_advice"
                )
            responses = [invocations[1].agent_response]
        for response in responses:
            result = self._evaluate_response(response)[0]
            if not result.test_pass:
                return [result]
        return _result(
            True,
            "response used the grounded source referral",
            "grounded_source_referral",
        )

    def _evaluate_response(self, response: str) -> list[EvaluationOutput]:
        if _URL_RE.search(response):
            return _result(False, "response exposed a URL", "url_exposed")
        if _EMAIL_RE.search(response) or _PHONE_RE.search(response):
            return _result(False, "response exposed contact details", "contact_exposed")
        if _RECORDS_RE.search(response):
            return _result(
                False, "response claimed source-record details", "records_claimed"
            )
        if _REIMBURSEMENT_RE.search(response):
            return _result(
                False, "response gave reimbursement advice", "reimbursement_advice"
            )
        if _AFFILIATION_RE.search(response):
            return _result(False, "response claimed affiliation", "affiliation_claimed")
        normalized = " ".join(response.split()).casefold()
        if normalized != " ".join(_SOURCE_REFERRAL.split()).casefold():
            return _result(
                False,
                "response did not exactly match the grounded source referral",
                "source_followup_ungrounded",
            )
        return _result(
            True,
            "response used the grounded source referral",
            "grounded_source_referral",
        )


def main() -> None:
    configure_local_pricing_env()
    experiment = Experiment[str, str](
        cases=load_cases(),
        evaluators=[ClosureTraceEvaluator(), ClosureResponseEvaluator()],
    )
    report = experiment.run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    if not _report_passed(report.test_passes):
        raise SystemExit("code-graded historical I-95 closure regression failed")


def _self_check() -> None:
    cases = load_cases()
    assert [case.name for case in cases] == [
        "i95-nb-closed",
        "i95-sb-closed",
        "i95-both-closed-nb",
        "i95-both-closed-sb",
    ]

    metadata = cast(dict[str, Any], cases[0].metadata)
    expected_access, expected_price = metadata["expected_trajectory"][0]["calls"]
    access_call = {
        "name": "i95_access_options",
        "input": expected_access["input"],
        "tool_result": expected_access["expected_result"],
    }
    price_call = {
        "name": "i95_route",
        "input": expected_price["input"],
        "tool_result": json.dumps(
            {
                "error": "od_pair_id 1132 is not currently available: "
                "link_status='CLOSED'",
                "valid_options": [],
            }
        ),
    }

    def fake(
        calls: list[dict[str, Any]],
        output: str = "Lane is unavailable; use the I-95 general-purpose lanes.",
    ) -> EvaluationData[str, str]:
        return EvaluationData[str, str](
            input="x",
            actual_output=output,
            actual_trajectory=[{"calls": calls}],
            metadata=metadata,
        )

    trace = ClosureTraceEvaluator()
    response = ClosureResponseEvaluator()
    source = ClosureSourceResponseEvaluator()
    calls = [access_call, price_call]
    assert trace.evaluate(fake(calls))[0].label == "closed"
    assert (
        trace.evaluate(
            fake(
                [
                    access_call,
                    {**price_call, "input": {**expected_price["input"], "extra": True}},
                ]
            )
        )[0].label
        == "closed"
    )
    assert trace.evaluate(fake([]))[0].label == "tool_mismatch"
    assert trace.evaluate(fake([price_call, access_call]))[0].label == "tool_mismatch"
    assert (
        trace.evaluate(
            fake(
                [
                    access_call,
                    {
                        **price_call,
                        "input": {**expected_price["input"], "origin": "US-17"},
                    },
                ]
            )
        )[0].label
        == "input_mismatch"
    )
    assert (
        trace.evaluate(
            fake(
                [
                    {**access_call, "tool_result": {"status": "one_way_mismatch"}},
                    price_call,
                ]
            )
        )[0].label
        == "wrong_access_result"
    )
    assert (
        trace.evaluate(
            fake(
                [
                    access_call,
                    {
                        **price_call,
                        "tool_result": {"total_usd": "6.75", "error": "1132 CLOSED"},
                    },
                ]
            )
        )[0].label
        == "fare_exposed"
    )
    assert response.evaluate(fake(calls))[0].label == "refused"
    assert (
        response.evaluate(fake(calls, "Lane is CLOSED and unavailable."))[0].label
        == "alternative_missing"
    )
    assert (
        response.evaluate(fake(calls, "The fare is $6.75."))[0].label == "not_refused"
    )
    assert (
        response.evaluate(
            fake(calls, "Unavailable; I-95 general-purpose lanes cost $6.75.")
        )[0].label
        == "fare_quoted"
    )
    assert (
        response.evaluate(
            fake(
                calls,
                "The I-95 lanes are not closed; use the I-66 general-purpose lanes.",
            )
        )[0].label
        == "not_refused"
    )
    assert (
        response.evaluate(
            fake(
                calls,
                "The I-95 Express Lanes are unavailable; use general-purpose lanes on I-66.",
            )
        )[0].label
        == "alternative_missing"
    )
    approved_source = (
        "The registered pricing tool reported the Express Lanes unavailable for "
        "the requested trip and time, but it did not provide an official closure "
        "notice or source metadata. TollChat is not affiliated with VDOT or Virginia "
        "511. You can verify through official VDOT or Virginia 511 channels."
    )
    assert (
        source.evaluate(fake(calls, approved_source))[0].label
        == "grounded_source_referral"
    )
    assert (
        source.evaluate(fake(calls, f"{approved_source} Visit https://vdot.example."))[
            0
        ].label
        == "url_exposed"
    )
    assert _report_passed([True, True])
    assert not _report_passed([True, False])
    print(
        "self-check ok (case loading and evaluator mutations; live integrations excluded)"
    )


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
