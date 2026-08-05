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
_MONEY_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)")
_RATE_PERIOD_RE = re.compile(
    r"^\s*(?:[-*]\s*)?rate period\s*:\s*([a-z]+(?:[-_][a-z]+)?)"
    r"(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_REQUIRED_HEADINGS = ("route and fares", "calculation", "final price")
_ROUTE_ALIASES = {
    "I-95-NB": "I-95 Express Lanes northbound",
    "I-95-SB": "I-95 Express Lanes southbound",
    "I-495-NB": "I-495 Express Lanes northbound",
    "I-495-SB": "I-495 Express Lanes southbound",
    "I-66 EB": "I-66 Inside the Beltway eastbound",
    "I-66 WB": "I-66 Inside the Beltway westbound",
}
_FACILITY_LABELS = {
    "dulles_greenway": "Dulles Greenway",
    "dulles_toll_road": "Dulles Toll Road",
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
    """Grade the required access check and pricing call against the fixture."""
    expected = metadata["expected_trajectory"][0]
    names = [call.get("name") for call in calls]
    expected_names = [expected["tool"]]
    if expected["tool"] == "i95_route":
        expected_names.insert(0, "i95_access_options")
    if names != expected_names:
        return _result(
            False,
            f"expected calls {expected_names}, got {names}",
            "tool_mismatch",
        )

    pricing_call = calls[-1]
    raw_input = pricing_call.get("input")
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

    if expected["tool"] == "i95_route":
        raw_access_input = calls[0].get("input")
        access_input = (
            cast(dict[str, Any], raw_access_input)
            if isinstance(raw_access_input, dict)
            else None
        )
        required_access = {
            key: required_input[key] for key in ("origin", "destination")
        }
        if access_input is None or any(
            access_input.get(key) != value for key, value in required_access.items()
        ):
            return _result(False, "access check used different ramps", "access_input")
        access_result = _tool_result(calls[0])
        if access_result != {
            "status": "supported",
            "direction": metadata["expected_result"]["direction"],
        }:
            return _result(
                False, f"unexpected access result: {access_result}", "access_result"
            )

    captured = _tool_result(pricing_call)
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
    """Require the I-95 access check plus exact fixture-matching pricing."""

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
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered)
    return (
        term.lower() in lowered
        or term.replace("_", " ").lower() in lowered
        or re.sub(r"[^a-z0-9]+", " ", term.lower()) in normalized
    )


def _route_line(response: str, origin: str, destination: str) -> str | None:
    plain = re.sub(r"[ \t]+", " ", response.translate(str.maketrans("", "", "*_`")))
    match = re.search(
        rf"^[^\r\n]*{re.escape(origin)}\s*(?:→|->|\bto\b)\s*"
        rf"{re.escape(destination)}"
        rf"(?=[ \t]*(?:$|[-—,.!?;:(]|\b(?:via|on|using)\b))[^\r\n]*$",
        plain,
        re.IGNORECASE | re.MULTILINE,
    )
    return match.group(0) if match else None


def _has_facility_heading_before(response: str, position: int, facility: str) -> bool:
    """Allow a toll line immediately following its facility heading."""
    lines = response[:position].splitlines()
    if not lines:
        return False
    heading = lines[-1].strip().strip("-*_`# ")
    return heading.casefold() == _FACILITY_LABELS[facility].casefold()


def _route_term_present(response: str, term: str) -> bool:
    humanized = _ROUTE_ALIASES.get(term)
    if not humanized:
        return _term_present(response, term)
    facility, direction = humanized.rsplit(" ", 1)
    facilities = [facility]
    if term.startswith("I-95-"):
        facilities.append(facility.replace("I-95", "I-95/395"))
    opposite = {
        "northbound": "southbound",
        "southbound": "northbound",
        "eastbound": "westbound",
        "westbound": "eastbound",
    }[direction]
    if _term_present(response, opposite):
        return False
    return any(_term_present(response, name) for name in facilities)


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
        origin = expected_call["input"]["origin"]
        destination = expected_call["input"]["destination"]
        fare = str(metadata["expected_final_usd"])
        route_line = _route_line(response, origin, destination)
        missing_terms = [] if route_line else [f"{origin} → {destination}"]
        if not route_line or not _route_term_present(
            route_line, metadata["expected_route_label"]
        ):
            missing_terms.append(metadata["expected_route_label"])
        tolls = metadata["expected_result"].get("tolls", [])
        if not tolls and (
            not route_line or not re.search(rf"\$\s*{re.escape(fare)}\b", route_line)
        ):
            missing_terms.append(f"${fare} route fare")
        toll_matches: list[re.Match[str] | None] = []
        for toll in tolls:
            candidates = list(
                re.finditer(
                    rf"^[^\r\n]*{re.escape(toll['label'])}[^\r\n]*"
                    rf"\$\s*{re.escape(toll['price_usd'])}\b[^\r\n]*$",
                    response,
                    re.IGNORECASE | re.MULTILINE,
                )
            )
            expected_facility = str(toll["facility"])
            route_facility = str(metadata["expected_route_label"])
            if len(candidates) > 1:
                return _result(
                    False,
                    f"response repeated {_FACILITY_LABELS[expected_facility]} "
                    f"{toll['label']}: ${toll['price_usd']}",
                    "toll_multiplicity",
                )
            match = candidates[0] if candidates else None
            if match:
                line = match.group().casefold()
                explicit_facilities = {
                    facility
                    for facility, label in _FACILITY_LABELS.items()
                    if label.casefold() in line
                }
                facility_matches = explicit_facilities == {expected_facility} or (
                    not explicit_facilities
                    and (
                        expected_facility == route_facility
                        or _has_facility_heading_before(
                            response, match.start(), expected_facility
                        )
                    )
                )
                if len(_MONEY_RE.findall(line)) != 1 or not facility_matches:
                    match = None
            toll_matches.append(match)
        missing_terms.extend(
            f"{_FACILITY_LABELS[toll['facility']]} {toll['label']}: "
            f"${toll['price_usd']}"
            for toll, match in zip(tolls, toll_matches, strict=True)
            if not match
        )
        if missing_terms:
            return _result(
                False, f"response omitted route facts: {missing_terms}", "route_missing"
            )
        toll_positions = [match.start() for match in toll_matches if match]
        if toll_positions != sorted(toll_positions):
            return _result(
                False, "response listed toll items out of travel order", "toll_order"
            )

        amounts = set(_MONEY_RE.findall(response))
        expected_amounts = {fare, *(str(toll["price_usd"]) for toll in tolls)}
        if amounts != expected_amounts:
            return _result(
                False,
                f"response dollar values {sorted(amounts)} did not equal "
                f"{sorted(expected_amounts)}",
                "wrong_money",
            )
        plain_response = response.translate(str.maketrans("", "", "*_`"))
        operands = [str(toll["price_usd"]) for toll in tolls] or [fare]
        calculation = r"\s*\+\s*".join(
            rf"\$\s*{re.escape(amount)}" for amount in operands
        )
        if not re.search(
            rf"^\s*(?:[-+]\s+)?{calculation}\s*=\s*"
            rf"\$\s*{re.escape(fare)}\s*$",
            plain_response,
            re.MULTILINE,
        ):
            return _result(
                False, "response omitted exact component arithmetic", "bad_math"
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
            raw_observed = str(metadata["expected_result"]["legs"][0]["observed_at"])[
                :16
            ]
            if raw_observed in response:
                return _result(
                    False,
                    "response exposed the raw observation timestamp",
                    "raw_datetime",
                )
        else:
            matches = _RATE_PERIOD_RE.findall(plain_response)
            periods = {re.sub(r"[-\s]+", "_", period.lower()) for period, _ in matches}
            expected_period = str(metadata["expected_rate_period"]).lower()
            tail_periods = {
                re.sub(r"[-\s]+", "_", period.lower())
                for _, tail in matches
                for period in re.findall(
                    r"\b(?:off[-_ ]?peak|peak)\b", tail, re.IGNORECASE
                )
            }
            if periods != {expected_period} or tail_periods - {expected_period}:
                return _result(
                    False,
                    "response omitted or misstated the Greenway rate period",
                    "period_missing",
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

    def required_calls(
        metadata: dict[str, Any], pricing_call: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if pricing_call["name"] != "i95_route":
            return [pricing_call]
        required_input = pricing_call["input"]
        return [
            {
                "name": "i95_access_options",
                "input": {
                    "origin": required_input["origin"],
                    "destination": required_input["destination"],
                },
                "tool_result": {
                    "status": "supported",
                    "direction": metadata["expected_result"]["direction"],
                },
            },
            pricing_call,
        ]

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
        tolls = metadata["expected_result"].get("tolls", [])
        toll_lines = "".join(
            f"  - {_FACILITY_LABELS[toll['facility']]} "
            f"{toll['label']}: ${toll['price_usd']}\n"
            for toll in tolls
        )
        operands = [toll["price_usd"] for toll in tolls] or [fare]
        calculation = " + ".join(f"${amount}" for amount in operands)
        good_output = (
            "## Route and fares\n"
            f"- {origin} → {destination} — {expected['tool']} "
            f"({displayed_route}): ${fare}\n"
            f"{toll_lines}"
            f"  - {provenance}\n"
            "## Calculation\n"
            f"{calculation} = **${fare}**\n"
            "## Final price\n"
            f"${fare}"
        )
        assert trace_label(metadata, required_calls(metadata, call)) == "exact_result"
        assert response_label(metadata, call, good_output) == "grounded_response"
        prepared.append((metadata, call, good_output))

    metadata, call, good_output = prepared[0]
    expected = metadata["expected_trajectory"][0]
    assert (
        trace_label(
            metadata,
            required_calls(
                metadata, {**call, "input": {**expected["input"], "extra": True}}
            ),
        )
        == "exact_result"
    )
    assert trace_label(metadata, []) == "tool_mismatch"
    assert trace_label(metadata, [call, call]) == "tool_mismatch"
    assert (
        trace_label(metadata, [{**call, "name": "plan_toll_route"}]) == "tool_mismatch"
    )
    assert (
        trace_label(
            metadata,
            required_calls(
                metadata, {**call, "input": {**expected["input"], "at_time": "wrong"}}
            ),
        )
        == "input_mismatch"
    )
    assert (
        trace_label(
            metadata, required_calls(metadata, {**call, "tool_result": "not-json"})
        )
        == "bad_result"
    )
    assert (
        trace_label(
            metadata, required_calls(metadata, {**call, "tool_result": {"error": "no"}})
        )
        == "tool_error"
    )
    extra_leg: dict[str, Any] = {**metadata["expected_result"], "legs": [{}, {}]}
    assert (
        trace_label(
            metadata, required_calls(metadata, {**call, "tool_result": extra_leg})
        )
        == "leg_count"
    )
    wrong_result = {**metadata["expected_result"], "total_usd": "999.99"}
    assert (
        trace_label(
            metadata, required_calls(metadata, {**call, "tool_result": wrong_result})
        )
        == "result_mismatch"
    )
    access = required_calls(metadata, call)[0]
    assert (
        trace_label(
            metadata, [{**access, "tool_result": {"status": "supported"}}, call]
        )
        == "access_result"
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
    wrong_final = "$999.99".join(good_output.rsplit(f"${fare}", 1))
    assert response_label(metadata, call, wrong_final) == "wrong_money"
    assert (
        response_label(metadata, call, good_output + "\nExtra charge: $6")
        == "wrong_money"
    )
    assert (
        response_label(metadata, call, good_output.replace(" = ", " + ")) == "bad_math"
    )
    leading_operand = good_output.replace(
        f"${fare} = **${fare}**", f"${fare} + ${fare} = **${fare}**"
    )
    assert response_label(metadata, call, leading_operand) == "bad_math"
    listed_math = good_output.replace(
        f"${fare} = **${fare}**", f"- ${fare} = **${fare}**"
    )
    assert response_label(metadata, call, listed_math) == "grounded_response"
    assert (
        response_label(metadata, call, good_output + " 2026-07-29T10:00:00-04:00")
        == "raw_datetime"
    )
    assert (
        response_label(
            metadata,
            call,
            good_output + "\nTravel time: 2026-07-29T10:10:00-04:00",
        )
        == "grounded_response"
    )
    prefixed_origin = good_output.replace(
        "I-95 Near Route 17", "From I-95 Near Route 17", 1
    )
    assert response_label(metadata, call, prefixed_origin) == "grounded_response"
    reversed_route = good_output.replace(
        "I-95 Near Route 17 → Washington D.C.",
        "Washington D.C. → I-95 Near Route 17",
    )
    assert response_label(metadata, call, reversed_route) == "route_missing"
    assert (
        response_label(metadata, call, good_output.replace("i95_route ", ""))
        == "grounded_response"
    )
    prose_destination = good_output.replace(
        "Washington D.C. —", "Washington D.C. via I-95 northbound —"
    )
    assert response_label(metadata, call, prose_destination) == "grounded_response"
    general_lanes = good_output.replace(
        "I-95 Express Lanes northbound", "I-95 general-purpose lanes northbound"
    )
    assert response_label(metadata, call, general_lanes) == "route_missing"
    raw_code = good_output.replace("I-95 Express Lanes northbound", "I-95-NB")
    assert response_label(metadata, call, raw_code) == "route_missing"
    contradictory_code = good_output.replace(
        "I-95 Express Lanes northbound",
        "I-95-NB (I-95/395 Express Lanes southbound)",
    )
    assert response_label(metadata, call, contradictory_code) == "route_missing"
    unbound_fare = good_output.replace(f": ${fare}\n", ": fare unavailable\n", 1)
    assert response_label(metadata, call, unbound_fare) == "route_missing"

    metadata, call, good_output = prepared[1]
    omitted_direction = good_output.replace(
        " Express Lanes southbound", " Express Lanes"
    )
    assert response_label(metadata, call, omitted_direction) == "grounded_response"
    wrong_direction = good_output.replace("southbound", "northbound")
    assert response_label(metadata, call, wrong_direction) == "route_missing"

    metadata, call, good_output = prepared[4]
    assert (
        response_label(
            metadata,
            call,
            good_output.replace(
                "I-66 Inside the Beltway eastbound",
                "I-66 Inside the Beltway (eastbound)",
            ),
        )
        == "grounded_response"
    )
    wrong_corridor = good_output.replace("Inside the Beltway", "Outside the Beltway")
    assert response_label(metadata, call, wrong_corridor) == "route_missing"
    assert (
        response_label(
            metadata, call, good_output.replace("Washington", "Washington Blvd")
        )
        == "route_missing"
    )

    metadata, call, good_output = prepared[5]
    omitted_direction = good_output.replace(" westbound", "")
    assert response_label(metadata, call, omitted_direction) == "grounded_response"
    assert (
        response_label(
            metadata,
            call,
            good_output.replace("I-66 WB", "I-66 Inside the Beltway westbound"),
        )
        == "grounded_response"
    )

    for index, full_name in (
        (0, "I-95/395 Express Lanes northbound"),
        (2, "I-495 Express Lanes northbound"),
    ):
        metadata, call, good_output = prepared[index]
        alias = _ROUTE_ALIASES[metadata["expected_route_label"]]
        assert (
            response_label(metadata, call, good_output.replace(alias, full_name))
            == "grounded_response"
        )

    metadata, call, good_output = prepared[-1]
    markdown_period = good_output.replace("Rate period: peak", "**Rate period:** peak")
    assert response_label(metadata, call, markdown_period) == "grounded_response"
    explained_period = good_output.replace(
        "Rate period: peak", "Rate period: peak (weekday morning)"
    )
    assert response_label(metadata, call, explained_period) == "grounded_response"
    punctuated_period = good_output.replace("Rate period: peak", "Rate period: peak.")
    assert response_label(metadata, call, punctuated_period) == "grounded_response"
    repeated_period = good_output.replace(
        "Rate period: peak", "Rate period: peak (weekday peak hours)"
    )
    assert response_label(metadata, call, repeated_period) == "grounded_response"
    contradictory_period = good_output.replace(
        "Rate period: peak", "Rate period: peak, but actually off-peak"
    )
    assert response_label(metadata, call, contradictory_period) == "period_missing"
    for wrong_period in ("off_peak", "off peak", "off-peak"):
        wrong_output = good_output.replace(
            "Rate period: peak", f"Rate period: {wrong_period}"
        )
        assert response_label(metadata, call, wrong_output) == "period_missing"
    assert (
        response_label(
            metadata, call, good_output.replace("Mainline plaza", "Exit plaza")
        )
        == "route_missing"
    )
    unpriced_toll = good_output.replace("Mainline plaza: $5.80", "Mainline plaza")
    assert response_label(metadata, call, unpriced_toll) == "route_missing"
    missing_dtr = good_output.replace(
        "  - Dulles Toll Road Mainline plaza: $2.00\n", ""
    )
    assert response_label(metadata, call, missing_dtr) == "route_missing"
    wrong_facility = good_output.replace(
        "Dulles Toll Road Mainline plaza: $2.00",
        "Dulles Greenway Mainline plaza: $2.00",
    )
    assert response_label(metadata, call, wrong_facility) == "route_missing"
    implicit_route_facility = good_output.replace(
        "Dulles Greenway Mainline plaza: $5.80", "Mainline plaza: $5.80"
    )
    assert (
        response_label(metadata, call, implicit_route_facility) == "grounded_response"
    )
    headed_dtr = good_output.replace(
        "  - Dulles Toll Road Mainline plaza: $2.00\n",
        "  - Dulles Toll Road\n    - Mainline plaza: $2.00\n",
    )
    assert response_label(metadata, call, headed_dtr) == "grounded_response"
    wrong_headed_dtr = headed_dtr.replace(
        "  - Dulles Toll Road\n    - Mainline plaza: $2.00\n",
        "  - Dulles Greenway\n    - Mainline plaza: $2.00\n",
    )
    assert response_label(metadata, call, wrong_headed_dtr) == "route_missing"
    combined_tolls = good_output.replace(
        "  - Dulles Toll Road Mainline plaza: $2.00\n"
        "  - Dulles Greenway Mainline plaza: $5.80\n",
        "  - Dulles Toll Road Mainline plaza: $2.00; "
        "Dulles Greenway Mainline plaza: $5.80\n",
    )
    assert response_label(metadata, call, combined_tolls) == "route_missing"
    duplicated_dtr = good_output.replace(
        "  - Dulles Toll Road Mainline plaza: $2.00\n",
        "  - Dulles Toll Road Mainline plaza: $2.00\n"
        "  - Dulles Toll Road Mainline plaza: $2.00\n",
    )
    assert response_label(metadata, call, duplicated_dtr) == "toll_multiplicity"
    reversed_tolls = good_output.replace(
        "  - Dulles Toll Road Mainline plaza: $2.00\n"
        "  - Dulles Greenway Mainline plaza: $5.80\n",
        "  - Dulles Greenway Mainline plaza: $5.80\n"
        "  - Dulles Toll Road Mainline plaza: $2.00\n",
    )
    assert response_label(metadata, call, reversed_tolls) == "toll_order"
    nonadditive = good_output.replace("$2.00 + $5.80 = **$7.80**", "$5.80 = **$5.80**")
    assert response_label(metadata, call, nonadditive) == "bad_math"
    wrong_result = json.loads(json.dumps(metadata["expected_result"]))
    wrong_result["tolls"][0]["price_usd"] = "999.99"
    assert (
        trace_label(metadata, [{**call, "tool_result": wrong_result}])
        == "result_mismatch"
    )
    missing_fee_result = json.loads(json.dumps(metadata["expected_result"]))
    missing_fee_result["tolls"] = missing_fee_result["tolls"][1:]
    assert (
        trace_label(metadata, [{**call, "tool_result": missing_fee_result}])
        == "result_mismatch"
    )
    print("self-check ok (8 fixtures and synthetic grader mutations; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
