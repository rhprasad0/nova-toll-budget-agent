"""Code-graded live regression for eight routine single-leg toll trips.

The grader is deterministic; the live TollChat invocation is stochastic.
``--check`` exercises fixtures and grader branches without network access.
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

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402

_CASES_PATH = Path(__file__).resolve().parent / "test-cases.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
_MONEY_RE = re.compile(r"\$\s*(\d+\.\d{2})")
_RAW_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?")
_REQUIRED_HEADINGS = ("route and fares", "calculation", "final price")
_ROUTE_ALIASES = {
    "I-95-NB": "I-95 northbound",
    "I-95-SB": "I-95 southbound",
    "I-495-NB": "I-495 northbound",
    "I-495-SB": "I-495 southbound",
}


def load_rows(path: Path = _CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    return [
        Case[str, str](
            name=row["id"],
            input=row["conversation"][0]["content"],
            expected_trajectory=[row["expected_trajectory"][0]["tool"]],
            metadata=row,
        )
        for row in load_rows(path)
    ]


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


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


def evaluate_single_leg_calls(
    calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Grade one captured pricing call against its verified fixture."""
    expected = metadata["expected_trajectory"][0]
    if len(calls) != 1 or calls[0].get("name") != expected["tool"]:
        return _result(
            False,
            f"expected exactly one {expected['tool']} call, got "
            f"{[call.get('name') for call in calls]}",
            "tool_mismatch",
        )

    raw_input = calls[0].get("input")
    actual_input = (
        cast(dict[str, Any], raw_input) if isinstance(raw_input, dict) else {}
    )
    required_input: dict[str, Any] = expected["input"]
    if not isinstance(raw_input, dict) or any(
        actual_input.get(key) != value for key, value in required_input.items()
    ):
        return _result(
            False,
            f"tool input {actual_input} lacks required arguments {required_input}",
            "input_mismatch",
        )

    captured = _tool_result(calls[0])
    if captured is None:
        return _result(False, "missing or invalid captured tool result", "bad_result")
    if "error" in captured:
        return _result(
            False, f"pricing tool returned an error: {captured}", "tool_error"
        )
    legs = captured.get("legs")
    if not isinstance(legs, list) or len(cast(list[object], legs)) != 1:
        return _result(False, "pricing result was not exactly one leg", "leg_count")
    mismatches = [
        key
        for key, value in metadata["expected_result"].items()
        if captured.get(key) != value
    ]
    if mismatches:
        return _result(
            False, f"result mismatched keys: {mismatches}", "result_mismatch"
        )
    return _result(True, "exact single-leg fixture matched", "exact_result")


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    response = agent(str(case.input))
    summary: dict[str, Any] = response.metrics.get_summary()
    traces = cast(list[dict[str, Any]], summary.get("traces", []))
    calls = _extract_tool_calls(_trace_messages(traces))
    return {"output": str(response), "trajectory": [{"calls": calls}]}


class SingleLegTraceEvaluator(Evaluator[str, str]):
    """Require one exact pricing call and fixture-matching captured result."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        turns = _turns(evaluation_case)
        calls = (
            cast(list[dict[str, Any]], turns[0].get("calls", []))
            if len(turns) == 1
            else []
        )
        return evaluate_single_leg_calls(calls, evaluation_case.metadata or {})


def _term_present(response: str, term: str) -> bool:
    lowered = response.lower()
    return term.lower() in lowered or term.replace("_", " ").lower() in lowered


def _route_term_present(response: str, term: str) -> bool:
    humanized = _ROUTE_ALIASES.get(term)
    return _term_present(response, term) or bool(
        humanized and _term_present(response, humanized)
    )


class SingleLegResponseEvaluator(Evaluator[str, str]):
    """Require the fixture fare, arithmetic, route facts, and provenance."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        metadata = evaluation_case.metadata or {}
        response = str(evaluation_case.actual_output or "")
        lowered = response.lower()
        missing_headings = [h for h in _REQUIRED_HEADINGS if h not in lowered]
        if missing_headings:
            return _result(
                False,
                f"response omitted sections: {missing_headings}",
                "sections_missing",
            )

        expected_call = metadata["expected_trajectory"][0]
        required_terms = [
            expected_call["input"]["origin"],
            expected_call["input"]["destination"],
            expected_call["tool"],
        ]
        missing_terms = [
            term for term in required_terms if not _term_present(response, term)
        ]
        if not _route_term_present(response, metadata["expected_route_label"]):
            missing_terms.append(metadata["expected_route_label"])
        if missing_terms:
            return _result(
                False, f"response omitted route facts: {missing_terms}", "route_missing"
            )

        fare = str(metadata["expected_final_usd"])
        amounts = set(_MONEY_RE.findall(response))
        if amounts != {fare}:
            return _result(
                False,
                f"response dollar values {sorted(amounts)} did not equal only ${fare}",
                "wrong_money",
            )
        plain_response = response.translate(str.maketrans("", "", "*_`"))
        if not re.search(
            rf"\$\s*{re.escape(fare)}\s*=\s*\$\s*{re.escape(fare)}",
            plain_response,
        ):
            return _result(
                False, "response omitted exact one-fare arithmetic", "bad_math"
            )
        final_section = lowered.rsplit("final price", 1)[-1]
        if not re.search(rf"\$\s*{re.escape(fare)}", final_section):
            return _result(
                False, "final price section omitted fixture fare", "final_missing"
            )

        if observed := metadata.get("expected_observed_display"):
            if not re.search(
                rf"VDOT observed at:[\s*_`~]*{re.escape(str(observed))}",
                response,
                re.IGNORECASE,
            ):
                return _result(
                    False,
                    "response omitted the formatted VDOT observation",
                    "observed_missing",
                )
            if _RAW_DATE_RE.search(response):
                return _result(False, "response exposed a raw ISO date", "raw_datetime")
        elif not _term_present(response, str(metadata["expected_rate_period"])):
            return _result(
                False, "response omitted the Greenway rate period", "period_missing"
            )

        if "unpriced junction" in lowered or "complete price unavailable" in lowered:
            return _result(
                False,
                "response treated a single leg as a junction trip",
                "junction_response",
            )
        return _result(
            True, "response matched the exact single-leg fare", "grounded_response"
        )


def main() -> None:
    configure_local_pricing_env()
    report = Experiment[str, str](
        cases=load_cases(),
        evaluators=[SingleLegTraceEvaluator(), SingleLegResponseEvaluator()],
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    if not all(report.test_passes):
        raise SystemExit("deterministic single-leg base evaluation failed")


def _self_check() -> None:
    rows = load_rows()
    cases = load_cases()
    assert len(rows) == len(cases) == 8
    assert [case.name for case in cases] == [row["id"] for row in rows]
    assert len({case.name for case in cases}) == 8
    assert {row["expected_trajectory"][0]["tool"] for row in rows} == {
        "i95_route",
        "i495_route",
        "i66_route",
        "dulles_route",
    }

    trace = SingleLegTraceEvaluator()
    response = SingleLegResponseEvaluator()

    def fake(
        metadata: dict[str, Any],
        calls: list[dict[str, Any]],
        output: str = "",
    ) -> EvaluationData[str, str]:
        return EvaluationData[str, str](
            input="x",
            actual_output=output,
            actual_trajectory=[{"calls": calls}],
            metadata=metadata,
        )

    def trace_label(
        metadata: dict[str, Any], calls: list[dict[str, Any]]
    ) -> str | None:
        return trace.evaluate(fake(metadata, calls))[0].label

    def response_label(
        metadata: dict[str, Any], call: dict[str, Any], output: str
    ) -> str | None:
        return response.evaluate(fake(metadata, [call], output))[0].label

    prepared: list[tuple[dict[str, Any], dict[str, Any], str]] = []

    for metadata in rows:
        expected = metadata["expected_trajectory"][0]
        call = {
            "name": expected["tool"],
            "input": expected["input"],
            "tool_result": json.dumps(metadata["expected_result"]),
        }
        fare = metadata["expected_final_usd"]
        origin = expected["input"]["origin"]
        destination = expected["input"]["destination"]
        provenance = (
            f"VDOT observed at: {metadata['expected_observed_display']}"
            if metadata.get("expected_observed_display")
            else f"Rate period: {metadata['expected_rate_period']}"
        )
        displayed_route = _ROUTE_ALIASES.get(
            metadata["expected_route_label"], metadata["expected_route_label"]
        )
        good_output = (
            "## Route and fares\n"
            f"- {origin} → {destination} — {expected['tool']} "
            f"({displayed_route}): ${fare}\n"
            f"  - {provenance}\n"
            "## Calculation\n"
            f"${fare} = **${fare}**\n"
            "## Final price\n"
            f"${fare}"
        )
        assert trace_label(metadata, [call]) == "exact_result"
        assert response_label(metadata, call, good_output) == "grounded_response"
        prepared.append((metadata, call, good_output))

    metadata, call, good_output = prepared[0]
    expected = metadata["expected_trajectory"][0]
    assert (
        trace_label(metadata, [{**call, "input": {**expected["input"], "extra": True}}])
        == "exact_result"
    )
    assert trace_label(metadata, []) == "tool_mismatch"
    assert trace_label(metadata, [call, call]) == "tool_mismatch"
    assert (
        trace_label(metadata, [{**call, "name": "plan_toll_route"}]) == "tool_mismatch"
    )
    assert (
        trace_label(
            metadata, [{**call, "input": {**expected["input"], "at_time": "wrong"}}]
        )
        == "input_mismatch"
    )
    assert trace_label(metadata, [{**call, "tool_result": "not-json"}]) == "bad_result"
    assert (
        trace_label(metadata, [{**call, "tool_result": {"error": "no"}}])
        == "tool_error"
    )
    extra_leg: dict[str, Any] = {**metadata["expected_result"], "legs": [{}, {}]}
    assert trace_label(metadata, [{**call, "tool_result": extra_leg}]) == "leg_count"
    wrong_result = {**metadata["expected_result"], "total_usd": "999.99"}
    assert (
        trace_label(metadata, [{**call, "tool_result": wrong_result}])
        == "result_mismatch"
    )

    displayed_route = _ROUTE_ALIASES[metadata["expected_route_label"]]
    assert (
        response_label(
            metadata, call, good_output.replace(displayed_route, "wrong road")
        )
        == "route_missing"
    )
    assert (
        response_label(metadata, call, good_output.replace("Calculation", "Math"))
        == "sections_missing"
    )
    fare = metadata["expected_final_usd"]
    assert (
        response_label(metadata, call, good_output.replace(f"${fare}", "$999.99"))
        == "wrong_money"
    )
    assert (
        response_label(metadata, call, good_output.replace(" = ", " + ")) == "bad_math"
    )
    assert (
        response_label(metadata, call, good_output + " 2026-07-29T10:00:00-04:00")
        == "raw_datetime"
    )

    metadata, call, _ = prepared[-1]
    wrong_result = json.loads(json.dumps(metadata["expected_result"]))
    wrong_result["tolls"][0]["price_usd"] = "999.99"
    assert (
        trace_label(metadata, [{**call, "tool_result": wrong_result}])
        == "result_mismatch"
    )
    print("self-check ok (8 fixtures and synthetic grader mutations; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
