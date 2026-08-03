"""Code-graded Issue #19 junction-routing evaluations.

The live runner calls TollChat's OpenAI model while replacing only the RDS
connection with deterministic rows. Planner, oracle lookup, pricing envelopes,
and Dulles rates remain production code. ``--check`` makes no network calls.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

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

from agent.toll_agent import build_agent, plan_toll_route  # noqa: E402
from agent_tools import _oracle_route  # noqa: E402
from agent_tools.dulles_route import dulles_route  # noqa: E402
from agent_tools.i66_route import i66_route  # noqa: E402
from agent_tools.i495_route import i495_route  # noqa: E402

_CASES_PATH = Path(__file__).resolve().parent / "test-cases.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
_CHECK_TIME = "2026-08-03T12:00:00-04:00"
_FIXTURE_TIME = datetime.fromisoformat("2026-08-03T14:00:00-04:00")
_MONEY_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")
_FORBIDDEN_CLAIMS = (
    "outside the beltway",
    "route 267 detour",
    "not a direct i-66/i-495",
    "transurban",
)
_I495_NORTHBOUND_PAIRS = {1017, 1021, 1034, 1038}


def load_rows(path: Path = _CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    return [
        Case[str, str](
            name=row["id"],
            input=row["prompt"],
            expected_trajectory=row["expected_tools"],
            metadata=row,
        )
        for row in load_rows(path)
    ]


class _FixtureCursor:
    def __init__(self) -> None:
        self.params: dict[str, Any] = {}

    def __enter__(self) -> _FixtureCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _query: str, params: dict[str, Any]) -> None:
        self.params = params

    def fetchone(self) -> tuple[object, ...]:
        if od_pair_id := self.params.get("od_pair_id"):
            direction = (
                "I-495-NB" if od_pair_id in _I495_NORTHBOUND_PAIRS else "I-495-SB"
            )
            return (
                od_pair_id,
                direction,
                Decimal("2.75"),
                _FIXTURE_TIME,
                _FIXTURE_TIME,
            )
        start = self.params["start_zone_id"]
        end = self.params["end_zone_id"]
        direction = "I-66 WB" if start == 3200 else "I-66 EB"
        return (
            start,
            end,
            direction,
            Decimal("1.25"),
            _FIXTURE_TIME,
            _FIXTURE_TIME,
        )


class _FixtureConnection:
    def cursor(self) -> _FixtureCursor:
        return _FixtureCursor()

    def close(self) -> None:
        return None


@contextmanager
def controlled_pricing() -> Generator[None]:
    """Replace only the RDS connection; registered tools remain unchanged."""
    with patch.object(_oracle_route, "env_connect", return_value=_FixtureConnection()):
        yield


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


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


def _endpoint(result: dict[str, Any], role: str) -> dict[str, Any]:
    if role in result:
        return cast(dict[str, Any], result[role])
    legs = cast(list[dict[str, Any]], result.get("legs", []))
    leg = legs[0] if role == "entry" else legs[-1]
    return cast(dict[str, Any], leg.get(role, {}))


def _direction(result: dict[str, Any]) -> str | None:
    if value := result.get("direction"):
        return str(value)
    legs = cast(list[dict[str, Any]], result.get("legs", []))
    return str(legs[0].get("direction")) if legs else None


def evaluate_junction_calls(
    calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Grade exact tool order, planner transfer, shared time, and endpoints."""
    names = [str(call.get("name")) for call in calls]
    expected_names = cast(list[str], metadata["expected_tools"])
    if names != expected_names:
        return _result(
            False,
            f"expected ordered calls {expected_names}, got {names}",
            "tool_sequence",
        )

    plan_input = calls[0].get("input")
    required_plan = cast(dict[str, Any], metadata["plan_input"])
    if not isinstance(plan_input, dict):
        return _result(False, "planner input is not an object", "plan_input")
    actual_plan_input = cast(dict[str, Any], plan_input)
    if any(actual_plan_input.get(key) != value for key, value in required_plan.items()):
        return _result(
            False,
            f"planner input {plan_input} lacks {required_plan}",
            "plan_input",
        )
    if actual_plan_input.get("at_time") not in (None, ""):
        return _result(False, "planner invented a departure time", "plan_input")

    captured = [_tool_result(call) for call in calls]
    if any(result is None for result in captured):
        return _result(False, "a captured tool result is invalid", "bad_result")
    results = cast(list[dict[str, Any]], captured)
    if any("error" in result for result in results):
        return _result(False, f"tool error in {results}", "tool_error")

    plan = results[0]
    plan_time = plan.get("at_time")
    steps = cast(list[dict[str, Any]], plan.get("steps", []))
    if not isinstance(plan_time, str) or [step.get("kind") for step in steps] != [
        "priced",
        "connector",
        "priced",
    ]:
        return _result(False, f"unexpected planner result: {plan}", "plan_mismatch")

    expected_connector = cast(dict[str, Any], metadata["expected_connector"])
    connector = steps[1]
    if (
        connector.get("transfer_id") != expected_connector["transfer_id"]
        or connector.get("label") != expected_connector["label"]
        or connector.get("price_usd") != "0.00"
        or plan.get("routing_note") is not None
    ):
        return _result(
            False, f"unexpected connector step: {connector}", "connector_mismatch"
        )
    if [steps[0].get("tool"), steps[2].get("tool")] != expected_names[1:]:
        return _result(False, f"unexpected priced steps: {steps}", "plan_mismatch")

    for call, result, expected in zip(
        calls[1:],
        results[1:],
        cast(list[dict[str, Any]], metadata["expected_priced"]),
        strict=True,
    ):
        raw_input = call.get("input")
        if not isinstance(raw_input, dict):
            return _result(False, "pricing input is not an object", "shared_time")
        actual_input = cast(dict[str, Any], raw_input)
        if actual_input.get("at_time") != plan_time:
            return _result(
                False,
                f"{call.get('name')} did not reuse planner time {plan_time}: {raw_input}",
                "shared_time",
            )
        entry = _endpoint(result, "entry")
        exit_ = _endpoint(result, "exit")
        if (
            result.get("at_time") != plan_time
            or entry.get("node_id") != expected["entry"]
            or exit_.get("node_id") != expected["exit"]
            or _direction(result) != expected["direction"]
        ):
            return _result(
                False,
                f"unexpected {call.get('name')} result: {result}",
                "priced_result",
            )
    return _result(True, "ordered junction trace is grounded", "trace_grounded")


def _fare_items(calls: list[dict[str, Any]]) -> list[tuple[str, Decimal]]:
    items: list[tuple[str, Decimal]] = []
    for call in calls[1:]:
        result = _tool_result(call) or {}
        if call.get("name") == "dulles_route":
            items.extend(
                (str(toll["label"]), Decimal(str(toll["price_usd"])))
                for toll in result.get("tolls", [])
            )
        else:
            entry = _endpoint(result, "entry")
            exit_ = _endpoint(result, "exit")
            items.append(
                (
                    f"{entry.get('label', '')} -> {exit_.get('label', '')}",
                    Decimal(str(result["total_usd"])),
                )
            )
    return items


def _line_has(response: str, terms: list[str]) -> bool:
    return any(
        all(
            term.casefold()
            in line.replace("Georg Wash. Mem. Pkwy.", "GW Parkway").casefold()
            for term in terms
        )
        for line in response.splitlines()
    )


def _response_label(label: str) -> str:
    """Use the shortest unambiguous user-facing form of a tool label."""
    if label.casefold().startswith(("entrance ramp at ", "exit ramp at ")):
        return label.split(" at ", 1)[0]
    if "Georg Wash. Mem. Pkwy." in label:
        return "GW Parkway"
    return label


def _calculation_matches(response: str, fares: list[Decimal], total: Decimal) -> bool:
    plain = response.replace("**", "").replace("__", "")
    for line in plain.splitlines():
        if "=" not in line:
            continue
        left, right = line.split("=", 1)
        operands = [Decimal(value) for value in _MONEY_RE.findall(left)]
        totals = [Decimal(value) for value in _MONEY_RE.findall(right)]
        if Counter(operands) == Counter(fares) and totals == [total]:
            return True
    return False


def evaluate_junction_response(
    response: str, calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Grade itemization and arithmetic only against captured tool results."""
    folded = response.casefold()
    forbidden = [claim for claim in _FORBIDDEN_CLAIMS if claim in folded]
    if forbidden:
        return _result(False, f"forbidden claims: {forbidden}", "forbidden_claim")
    if "$0.00" in response or "$0" in response:
        return _result(False, "connector sentinel was billed", "sentinel_billed")

    expected_connector = cast(dict[str, Any], metadata["expected_connector"])
    connector_label = str(expected_connector["label"])
    if connector_label.casefold() not in folded:
        return _result(False, "connector is not identified", "connector_missing")

    fare_items = _fare_items(calls)
    for label, fare in fare_items:
        if " -> " in label:
            entry, exit_ = label.split(" -> ", 1)
            terms = [_response_label(entry), _response_label(exit_), f"${fare:.2f}"]
        else:
            terms = [_response_label(label), f"${fare:.2f}"]
        if not _line_has(response, terms):
            return _result(
                False, f"fare item is not grounded on one line: {terms}", "item_missing"
            )

    fares = [fare for _, fare in fare_items]
    total = sum(fares, Decimal(0))
    if not _calculation_matches(response, fares, total):
        return _result(
            False, f"calculation does not sum {fares} to {total}", "bad_math"
        )
    allowed = {*fares, total}
    quoted = {Decimal(value) for value in _MONEY_RE.findall(response)}
    if unexpected := sorted(quoted - allowed):
        return _result(
            False, f"response invented amounts {unexpected}", "fabricated_amount"
        )
    if "final price" not in folded or not _line_has(response, [f"${total:.2f}"]):
        return _result(False, "final total is missing", "final_missing")
    return _result(True, "response is grounded in captured fares", "response_grounded")


def _calls_from_evaluation(
    evaluation_case: EvaluationData[str, str],
) -> list[dict[str, Any]]:
    trajectory = evaluation_case.actual_trajectory
    if (
        not isinstance(trajectory, list)
        or len(trajectory) != 1
        or not isinstance(trajectory[0], dict)
    ):
        return []
    turn = cast(dict[str, Any], trajectory[0])
    return cast(list[dict[str, Any]], turn.get("calls", []))


class JunctionTraceEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        return evaluate_junction_calls(
            _calls_from_evaluation(evaluation_case), evaluation_case.metadata or {}
        )


class JunctionResponseEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        return evaluate_junction_response(
            str(evaluation_case.actual_output or ""),
            _calls_from_evaluation(evaluation_case),
            evaluation_case.metadata or {},
        )


def main() -> None:
    with controlled_pricing():
        report = Experiment[str, str](
            cases=load_cases(),
            evaluators=[JunctionTraceEvaluator(), JunctionResponseEvaluator()],
        ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    if not all(report.test_passes):
        raise SystemExit("Issue #19 deterministic junction evaluation failed")


def _planned_calls(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": step["tool"],
            "input": {
                "origin": step["origin"],
                "destination": step["destination"],
                "at_time": plan["at_time"],
            },
        }
        for step in plan["steps"]
        if step["kind"] == "priced"
    ]


def _fixture_calls(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    plan = plan_toll_route(**metadata["plan_input"], at_time=_CHECK_TIME)
    calls = [
        {
            "name": "plan_toll_route",
            "input": metadata["plan_input"],
            "tool_result": plan,
        }
    ]
    tools = {
        "i66_route": i66_route,
        "i495_route": i495_route,
        "dulles_route": dulles_route,
    }
    with controlled_pricing():
        for planned in _planned_calls(plan):
            calls.append(
                {
                    **planned,
                    "tool_result": tools[planned["name"]](**planned["input"]),
                }
            )
    return calls


def _good_response(calls: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    items = _fare_items(calls)
    fares = [fare for _, fare in items]
    total = sum(fares, Decimal(0))
    lines = ["## Route and fares"]
    lines.extend(f"- {label}: ${fare:.2f}" for label, fare in items)
    lines.append(f"- Untolled connector: {metadata['expected_connector']['label']}")
    equation = " + ".join(f"${fare:.2f}" for fare in fares)
    lines.extend(
        [
            "## Calculation",
            f"{equation} = ${total:.2f}",
            "## Final price",
            f"${total:.2f}",
        ]
    )
    return "\n".join(lines)


def _self_check() -> None:
    rows = load_rows()
    assert len(rows) == 16
    assert len({row["id"] for row in rows}) == 16
    assert sum(row["id"].endswith("-paraphrase") for row in rows) == 8

    prepared: list[tuple[dict[str, Any], list[dict[str, Any]], str]] = []
    for metadata in rows:
        calls = _fixture_calls(metadata)
        response = _good_response(calls, metadata)
        assert evaluate_junction_calls(calls, metadata)[0].label == "trace_grounded"
        assert (
            evaluate_junction_response(response, calls, metadata)[0].label
            == "response_grounded"
        )
        prepared.append((metadata, calls, response))

    metadata, calls, response = prepared[0]
    assert evaluate_junction_calls(calls[1:], metadata)[0].label == "tool_sequence"
    wrong_time = json.loads(json.dumps(calls))
    wrong_time[1]["input"]["at_time"] = "wrong"
    assert evaluate_junction_calls(wrong_time, metadata)[0].label == "shared_time"
    wrong_connector = json.loads(json.dumps(calls))
    wrong_connector[0]["tool_result"]["steps"][1]["transfer_id"] = "reverse"
    assert (
        evaluate_junction_calls(wrong_connector, metadata)[0].label
        == "connector_mismatch"
    )
    tool_error = json.loads(json.dumps(calls))
    tool_error[1]["tool_result"] = {"error": "no"}
    assert evaluate_junction_calls(tool_error, metadata)[0].label == "tool_error"
    assert (
        evaluate_junction_response(
            response.replace(metadata["expected_connector"]["label"], "junction"),
            calls,
            metadata,
        )[0].label
        == "connector_missing"
    )
    assert (
        evaluate_junction_response(response + "\nExtra: $9.99", calls, metadata)[
            0
        ].label
        == "fabricated_amount"
    )
    assert (
        evaluate_junction_response(response + "\nJunction: $0.00", calls, metadata)[
            0
        ].label
        == "sentinel_billed"
    )
    assert (
        evaluate_junction_response(response + "\nRoute 267 detour", calls, metadata)[
            0
        ].label
        == "forbidden_claim"
    )
    bad_math = response.replace(" = $4.00", " = $9.99")
    assert evaluate_junction_response(bad_math, calls, metadata)[0].label == "bad_math"
    print("self-check ok (16 fixtures and synthetic grader mutations; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
