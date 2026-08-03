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
from itertools import pairwise, product
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
_ZERO_RE = re.compile(r"\$\s*0(?:\.00)?(?![\d.])")
_EXIT_RE = re.compile(r"\bExit\s+\d+(?:/\d+)?\b", re.I)
_UNBILLED_RE = re.compile(
    r"\b(?:untolled|not (?:a |separate )?billed|not included in (?:the )?fare arithmetic)\b",
    re.I,
)
_FORBIDDEN_CLAIMS = (
    "outside the beltway",
    "route 267 detour",
    "not a direct i-66/i-495",
    "transurban",
)
_I495_NORTHBOUND_PAIRS = {1017, 1021, 1034, 1038}
_DIRECTION_ALIASES = {
    "EB": ("EB", "eastbound"),
    "WB": ("WB", "westbound"),
    "Northbound": ("NB", "northbound"),
    "Southbound": ("SB", "southbound"),
}


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

    for step, call, result, expected in zip(
        steps[::2],
        calls[1:],
        results[1:],
        cast(list[dict[str, Any]], metadata["expected_priced"]),
        strict=True,
    ):
        raw_input = call.get("input")
        if not isinstance(raw_input, dict):
            return _result(False, "pricing input is not an object", "shared_time")
        actual_input = cast(dict[str, Any], raw_input)
        if any(
            actual_input.get(field) != step.get(field)
            for field in ("origin", "destination")
        ):
            return _result(
                False,
                f"{call.get('name')} input {raw_input} did not copy {step}",
                "plan_boundary",
            )
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
    for line in response.splitlines():
        folded = line.replace("Georg Wash. Mem. Pkwy.", "GW Parkway").casefold()
        position = 0
        for term in terms:
            position = folded.find(term.casefold(), position)
            if position < 0:
                break
            position += len(term)
        else:
            return True
    return False


def _response_label(label: str) -> str:
    """Use the shortest unambiguous user-facing form of a tool label."""
    if "Georg Wash. Mem. Pkwy." in label:
        return "GW Parkway"
    return label


def _route_label(label: str) -> str:
    if label.startswith("Exit "):
        return label.partition(" - ")[0]
    return _response_label(label)


def _route_labels(label: str) -> tuple[str, ...]:
    primary = _route_label(label)
    if "Georg Wash. Mem. Pkwy." in label:
        return primary, "George Wash. Mem. Pkwy.", "George Washington Memorial Parkway"
    if label.startswith("Exit 18/19"):
        return primary, "Route 267"
    if label.startswith("Exit 12"):
        return primary, "Reston Parkway", "Reston Pkwy"
    return (primary,)


def _line_has_direction(
    response: str,
    entry_terms: tuple[str, ...],
    exit_terms: tuple[str, ...],
    direction: str,
) -> bool:
    aliases = _DIRECTION_ALIASES[direction]
    wrong_aliases = tuple(
        alias
        for candidate, candidate_aliases in _DIRECTION_ALIASES.items()
        if candidate != direction
        for alias in candidate_aliases
    )

    def mentions(line: str, choices: tuple[str, ...]) -> bool:
        return any(
            re.search(rf"(?<!\w){re.escape(choice)}(?!\w)", line, re.IGNORECASE)
            for choice in choices
        )

    relevant = [
        line
        for line in response.splitlines()
        if any(
            _line_has(line, [entry, exit_])
            for entry in entry_terms
            for exit_ in exit_terms
        )
    ]
    return any(mentions(line, aliases) for line in relevant) and not any(
        mentions(line, wrong_aliases) for line in relevant
    )


def _calculation_matches(response: str, fares: list[Decimal], total: Decimal) -> bool:
    plain = response.replace("**", "").replace("__", "")
    for line in plain.splitlines():
        if "=" not in line:
            continue
        left, right = line.split("=", 1)
        operand_matches = list(_MONEY_RE.finditer(left))
        operands = [Decimal(match.group(1)) for match in operand_matches]
        totals = [Decimal(value) for value in _MONEY_RE.findall(right)]
        additions = all(
            re.fullmatch(r"\s*\+\s*", left[first.end() : second.start()])
            for first, second in pairwise(operand_matches)
        )
        if additions and Counter(operands) == Counter(fares) and totals == [total]:
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
    zero_lines = [line for line in response.splitlines() if _ZERO_RE.search(line)]
    if any(not _UNBILLED_RE.search(line) for line in zero_lines):
        return _result(False, "connector sentinel was billed", "sentinel_billed")

    expected_connector = cast(dict[str, Any], metadata["expected_connector"])
    connector_label = str(expected_connector["label"])
    lines = response.splitlines()
    connector_indexes = [
        index
        for index, line in enumerate(lines)
        if connector_label.casefold() in line.casefold()
    ]
    if not connector_indexes:
        return _result(False, "connector is not identified", "connector_missing")
    for index in connector_indexes:
        connector_block = [lines[index]]
        for continuation in lines[index + 1 :]:
            if continuation and not continuation[0].isspace():
                break
            connector_block.append(continuation)
        if any(
            any(Decimal(value) != 0 for value in _MONEY_RE.findall(line))
            or (_ZERO_RE.search(line) and not _UNBILLED_RE.search(line))
            for line in connector_block
        ):
            return _result(False, "connector is attributed a fare", "connector_billed")

    for call, expected in zip(
        calls[1:],
        cast(list[dict[str, Any]], metadata["expected_priced"]),
        strict=True,
    ):
        result = _tool_result(call) or {}
        entry = _endpoint(result, "entry")
        exit_ = _endpoint(result, "exit")
        direction = str(expected["direction"])
        entry_labels = _route_labels(str(entry.get("label", "")))
        exit_labels = _route_labels(str(exit_.get("label", "")))
        if not _line_has_direction(response, entry_labels, exit_labels, direction):
            return _result(
                False,
                f"route leg does not state only {direction}: "
                f"{entry_labels} -> {exit_labels}",
                "direction_mismatch",
            )

    fare_items = _fare_items(calls)
    grounded_money_lines: set[int] = set()
    for label, fare in fare_items:
        expected_exit: str | None = None
        location_terms: tuple[str, ...] | None = None
        if " -> " in label:
            entry, exit_ = label.split(" -> ", 1)
            term_sets = (
                _route_labels(entry),
                _route_labels(exit_),
                (f"${fare:.2f}",),
            )
        elif label.casefold().startswith(("entrance ramp at ", "exit ramp at ")):
            ramp, location = label.split(" at ", 1)
            term_sets = ((ramp,), (f"${fare:.2f}",))
            location_terms = _route_labels(location)
            expected_exit = (
                match.group() if (match := _EXIT_RE.search(location)) else None
            )
        else:
            term_sets = ((_response_label(label),), (f"${fare:.2f}",))
        matching_lines: list[int] = []
        for index, line in enumerate(lines):
            actual_exit = _EXIT_RE.search(line)
            if (
                [Decimal(value) for value in _MONEY_RE.findall(line)] != [fare]
                or (
                    expected_exit is not None
                    and actual_exit is not None
                    and actual_exit.group().casefold() != expected_exit.casefold()
                )
                or not any(
                    _line_has(line, list(terms)) for terms in product(*term_sets)
                )
            ):
                continue
            context = line
            if location_terms is not None and line[:1].isspace():
                indent = len(line) - len(line.lstrip())
                context += next(
                    (
                        previous
                        for previous in reversed(lines[:index])
                        if previous.strip()
                        and len(previous) - len(previous.lstrip()) < indent
                    ),
                    "",
                )
            if location_terms is None or any(
                _line_has(context, [term]) for term in location_terms
            ):
                matching_lines.append(index)
        if len(matching_lines) != 1:
            return _result(
                False,
                f"fare item must appear on one grounded line: {term_sets}",
                "item_missing",
            )
        grounded_money_lines.update(matching_lines)

    fares = [fare for _, fare in fare_items]
    total = sum(fares, Decimal(0))
    calculation_lines = [
        index
        for index, line in enumerate(lines)
        if _calculation_matches(line, fares, total)
    ]
    if len(calculation_lines) != 1:
        return _result(
            False, f"calculation does not sum {fares} to {total}", "bad_math"
        )
    grounded_money_lines.update(calculation_lines)
    final_index = next(
        (
            index
            for index in range(len(lines) - 1, -1, -1)
            if "final price" in lines[index].casefold()
        ),
        None,
    )
    final_value_index = (
        next(
            (
                index
                for index in range(final_index + 1, len(lines))
                if lines[index].strip()
            ),
            None,
        )
        if final_index is not None
        else None
    )
    if final_value_index is None or [
        Decimal(value) for value in _MONEY_RE.findall(lines[final_value_index])
    ] != [total]:
        return _result(False, "final total is missing", "final_missing")
    grounded_money_lines.add(final_value_index)
    unbilled_zero_lines = {
        index
        for index, line in enumerate(lines)
        if (amounts := [Decimal(value) for value in _MONEY_RE.findall(line)])
        and all(amount == 0 for amount in amounts)
        and _UNBILLED_RE.search(line)
    }
    unexpected_money_lines = [
        line
        for index, line in enumerate(lines)
        if _MONEY_RE.search(line)
        and index not in grounded_money_lines | unbilled_zero_lines
    ]
    if unexpected_money_lines:
        return _result(
            False,
            f"response contains unattributed amounts: {unexpected_money_lines}",
            "fabricated_amount",
        )
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


def fixture_calls(metadata: dict[str, Any]) -> list[dict[str, Any]]:
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
        for step in plan["steps"]:
            if step["kind"] != "priced":
                continue
            name = step["tool"]
            tool_input = {
                "origin": step["origin"],
                "destination": step["destination"],
                "at_time": plan["at_time"],
            }
            calls.append(
                {
                    "name": name,
                    "input": tool_input,
                    "tool_result": tools[name](**tool_input),
                }
            )
    return calls


def _good_response(calls: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    items = _fare_items(calls)
    fares = [fare for _, fare in items]
    total = sum(fares, Decimal(0))
    lines = ["## Route and fares"]
    for index, (call, expected) in enumerate(
        zip(
            calls[1:],
            cast(list[dict[str, Any]], metadata["expected_priced"]),
            strict=True,
        )
    ):
        result = _tool_result(call) or {}
        entry = _route_label(str(_endpoint(result, "entry").get("label", "")))
        exit_ = _route_label(str(_endpoint(result, "exit").get("label", "")))
        direction = expected["direction"]
        if call.get("name") == "dulles_route":
            lines.append(f"- {entry} -> {exit_}, {direction}:")
            lines.extend(
                f"  - {toll['label']}: ${Decimal(str(toll['price_usd'])):.2f}"
                for toll in result.get("tolls", [])
            )
        else:
            lines.append(
                f"- {entry} -> {exit_}, {direction}: "
                f"${Decimal(str(result['total_usd'])):.2f}"
            )
        if index == 0:
            lines.append(
                f"- Untolled connector: {metadata['expected_connector']['label']}"
            )
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
    assert all("tool" not in item for row in rows for item in row["expected_priced"])

    prepared: list[tuple[dict[str, Any], list[dict[str, Any]], str]] = []
    for metadata in rows:
        calls = fixture_calls(metadata)
        response = _good_response(calls, metadata)
        assert evaluate_junction_calls(calls, metadata)[0].label == "trace_grounded"
        assert (
            evaluate_junction_response(response, calls, metadata)[0].label
            == "response_grounded"
        )
        prepared.append((metadata, calls, response))

    alias_metadata, alias_calls, alias_response = prepared[6]
    alias_response = alias_response.replace(
        "Exit 18/19 -> Exit 12", "Route 267 -> Reston Parkway"
    )
    assert (
        evaluate_junction_response(alias_response, alias_calls, alias_metadata)[0].label
        == "response_grounded"
    )
    parkway_metadata, parkway_calls, parkway_response = prepared[15]
    parkway_response = parkway_response.replace("GW Parkway", "George Wash. Mem. Pkwy.")
    assert (
        evaluate_junction_response(parkway_response, parkway_calls, parkway_metadata)[
            0
        ].label
        == "response_grounded"
    )
    for index, ramp in ((4, "Entrance"), (6, "Exit")):
        ramp_metadata, ramp_calls, ramp_response = prepared[index]
        short_ramp_response = re.sub(
            rf"{ramp} ramp at Exit 12[^:]*", f"{ramp} ramp toll", ramp_response
        )
        assert short_ramp_response != ramp_response
        assert (
            evaluate_junction_response(short_ramp_response, ramp_calls, ramp_metadata)[
                0
            ].label
            == "response_grounded"
        )
        wrong_ramp_response = ramp_response.replace(
            f"{ramp} ramp at Exit 12", f"{ramp} ramp at Exit 99"
        )
        assert wrong_ramp_response != ramp_response
        assert (
            evaluate_junction_response(wrong_ramp_response, ramp_calls, ramp_metadata)[
                0
            ].label
            == "item_missing"
        )

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
    wrong_plan_boundary = json.loads(json.dumps(calls))
    first_step = wrong_plan_boundary[0]["tool_result"]["steps"][0]
    first_step["origin"], first_step["destination"] = (
        first_step["destination"],
        first_step["origin"],
    )
    assert (
        evaluate_junction_calls(wrong_plan_boundary, metadata)[0].label
        == "plan_boundary"
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
        evaluate_junction_response(response + "\nService fee: $1.25", calls, metadata)[
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
    unbilled_sentinel = response.replace(
        metadata["expected_connector"]["label"],
        f"{metadata['expected_connector']['label']} "
        "($0.00 planner sentinel, not a billed fare)",
    )
    assert (
        evaluate_junction_response(unbilled_sentinel, calls, metadata)[0].label
        == "response_grounded"
    )
    contradictory_direction = response + (
        "\n- Lee Highway - Scott Street -> I-495 S, EB"
    )
    assert (
        evaluate_junction_response(contradictory_direction, calls, metadata)[0].label
        == "direction_mismatch"
    )
    billed_connector = response.replace(
        metadata["expected_connector"]["label"],
        f"{metadata['expected_connector']['label']}: $1.25",
    )
    assert (
        evaluate_junction_response(billed_connector, calls, metadata)[0].label
        == "connector_billed"
    )
    nested_connector_fare = response.replace(
        metadata["expected_connector"]["label"],
        f"{metadata['expected_connector']['label']}\n  - Fare: $1.25",
    )
    assert (
        evaluate_junction_response(nested_connector_fare, calls, metadata)[0].label
        == "connector_billed"
    )
    assert (
        evaluate_junction_response(response + "\nRoute 267 detour", calls, metadata)[
            0
        ].label
        == "forbidden_claim"
    )
    wrong_direction = response.replace(
        "Lee Highway - Scott Street -> I-495 S",
        "Lee Highway - Scott Street -> I-495 S, eastbound",
    )
    assert (
        evaluate_junction_response(wrong_direction, calls, metadata)[0].label
        == "direction_mismatch"
    )
    reversed_leg = response.replace(
        "Lee Highway - Scott Street -> I-495 S",
        "I-495 S -> Lee Highway - Scott Street",
    )
    assert reversed_leg != response
    assert (
        evaluate_junction_response(reversed_leg, calls, metadata)[0].label
        == "direction_mismatch"
    )
    missing_direction = response.replace(", WB", "", 1)
    assert (
        evaluate_junction_response(missing_direction, calls, metadata)[0].label
        == "direction_mismatch"
    )
    wrong_second_direction = response.replace(", Southbound", ", Northbound", 1)
    assert (
        evaluate_junction_response(wrong_second_direction, calls, metadata)[0].label
        == "direction_mismatch"
    )
    bad_math = response.replace(" = $4.00", " = $9.99")
    assert evaluate_junction_response(bad_math, calls, metadata)[0].label == "bad_math"
    subtraction = response.replace(" + ", " - ", 1)
    assert subtraction != response
    assert (
        evaluate_junction_response(subtraction, calls, metadata)[0].label == "bad_math"
    )
    missing_final = "\n".join(response.splitlines()[:-1])
    assert (
        evaluate_junction_response(missing_final, calls, metadata)[0].label
        == "final_missing"
    )
    print("self-check ok (16 fixtures and synthetic grader mutations; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
