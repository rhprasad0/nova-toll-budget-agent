"""Code-graded SOP regressions for the duplicate-tool guard."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from strands.types.content import Message, Messages  # noqa: E402
from strands_evals import Case, Experiment  # noqa: E402
from strands_evals.evaluators import Evaluator  # noqa: E402
from strands_evals.types.evaluation import (  # noqa: E402
    EvaluationData,
    EvaluationOutput,
)

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import (  # noqa: E402
    _DUPLICATE_TOOL_MESSAGE as DUPLICATE_MESSAGE,  # pyright: ignore[reportPrivateUsage]
)
from agent.toll_agent import build_agent  # noqa: E402

_CASES_PATH = Path(__file__).resolve().parent / "test-cases.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"


def load_rows(path: Path = _CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    return [
        Case[str, str](
            name=row["id"], input=row["conversation"][0]["content"], metadata=row
        )
        for row in load_rows(path)
    ]


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _signature(call: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(call.get("name")),
        json.dumps(call.get("input"), sort_keys=True, separators=(",", ":")),
    )


def extract_calls(messages: Messages) -> list[dict[str, Any]]:
    """Extract unique tool attempts and their results from cumulative history."""
    results: dict[str, dict[str, Any]] = {}
    for message in messages:
        for block in message.get("content", []):
            tool_result = block.get("toolResult")
            if tool_result:
                results[tool_result["toolUseId"]] = cast(dict[str, Any], tool_result)

    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in messages:
        for block in message.get("content", []):
            tool_use = block.get("toolUse")
            if not tool_use or tool_use["toolUseId"] in seen:
                continue
            tool_use_id = tool_use["toolUseId"]
            seen.add(tool_use_id)
            result = results.get(tool_use_id, {})
            text: str | None = None
            content = result.get("content")
            if isinstance(content, list):
                for item in cast(list[object], content):
                    value = (
                        cast(Mapping[str, object], item).get("text")
                        if isinstance(item, Mapping)
                        else None
                    )
                    if isinstance(value, str):
                        text = value
                        break
            calls.append(
                {
                    "tool_use_id": tool_use_id,
                    "name": tool_use["name"],
                    "input": tool_use["input"],
                    "tool_result": text,
                    "is_error": result.get("status") == "error",
                }
            )
    return calls


def _trace_messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        messages = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [message for trace in traces for message in walk(trace)]


def evaluate_guard_calls(
    turns: Sequence[Sequence[Mapping[str, object]]],
    expected_turns: Sequence[Sequence[Mapping[str, object]]],
) -> list[EvaluationOutput]:
    """Require one success per SOP call and only valid duplicate suppression."""
    if len(turns) != len(expected_turns):
        return _result(
            False,
            f"expected {len(expected_turns)} turns, got {len(turns)}",
            "turn_mismatch",
        )

    for turn_number, (calls, expected) in enumerate(
        zip(turns, expected_turns, strict=True), start=1
    ):
        successful: list[Mapping[str, object]] = []
        seen_successes: set[tuple[str, str]] = set()
        for call in calls:
            signature = _signature(call)
            if call.get("is_error"):
                if call.get("tool_result") != DUPLICATE_MESSAGE:
                    return _result(
                        False,
                        f"turn {turn_number} had a non-guard tool error: {call}",
                        "tool_error",
                    )
                if signature not in seen_successes:
                    return _result(
                        False,
                        f"turn {turn_number} suppressed without a matching success",
                        "orphan_suppression",
                    )
                continue
            if call.get("tool_result") is None:
                return _result(
                    False,
                    f"turn {turn_number} had no captured tool result: {call}",
                    "bad_result",
                )
            if signature in seen_successes:
                return _result(
                    False,
                    f"turn {turn_number} executed {signature[0]} twice",
                    "duplicate_success",
                )
            seen_successes.add(signature)
            successful.append(call)

        if len(successful) != len(expected):
            return _result(
                False,
                f"turn {turn_number} expected {len(expected)} successes, got {len(successful)}",
                "tool_mismatch",
            )
        for actual, wanted in zip(successful, expected, strict=True):
            wanted_input = cast(Mapping[str, object], wanted["input"])
            actual_input = cast(Mapping[str, object], actual.get("input", {}))
            if actual.get("name") != wanted["tool"] or any(
                actual_input.get(key) != value for key, value in wanted_input.items()
            ):
                return _result(
                    False,
                    f"turn {turn_number} expected {wanted}, got {actual}",
                    "tool_mismatch",
                )

    return _result(
        True, "all SOP calls executed once or were safely suppressed", "guard_ok"
    )


def task_function(case: Case[str, str]) -> dict[str, Any]:
    metadata = case.metadata or {}
    agent = build_agent()
    seen_ids: set[str] = set()
    turns: list[list[dict[str, Any]]] = []
    output = ""
    for message in metadata["conversation"]:
        response = agent(message["content"])
        output = str(response)
        summary: dict[str, Any] = response.metrics.get_summary()
        traces = cast(list[dict[str, Any]], summary.get("traces", []))
        calls = extract_calls(_trace_messages(traces))
        turns.append([call for call in calls if call["tool_use_id"] not in seen_ids])
        seen_ids.update(call["tool_use_id"] for call in calls)
    return {"output": output, "trajectory": [{"turns": turns}]}


class DuplicateToolGuardEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        trajectory = evaluation_case.actual_trajectory
        if not isinstance(trajectory, list) or len(trajectory) != 1:
            return _result(False, "trajectory missing", "bad_trajectory")
        turns = trajectory[0].get("turns", [])
        expected = (evaluation_case.metadata or {}).get("expected_turns", [])
        return evaluate_guard_calls(turns, expected)


def main() -> None:
    configure_local_pricing_env()
    report = Experiment[str, str](
        cases=load_cases(), evaluators=[DuplicateToolGuardEvaluator()]
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    if not all(report.test_passes):
        raise SystemExit("duplicate tool guard evaluation failed")


def _self_check() -> None:
    rows = load_rows()
    assert len(load_cases()) == len(rows) == 3
    tool_use = {
        "toolUse": {
            "toolUseId": "call-one",
            "name": "plan_toll_route",
            "input": {"origin": "Dumfries"},
        }
    }
    messages = cast(
        Messages,
        [
            {"role": "assistant", "content": [tool_use]},
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": "call-one",
                            "status": "success",
                            "content": [{"text": "{}"}],
                        }
                    }
                ],
            },
            {"role": "assistant", "content": [tool_use]},
        ],
    )
    assert [call["tool_use_id"] for call in extract_calls(messages)] == ["call-one"]
    assert _trace_messages([{"message": messages[0], "children": []}]) == [messages[0]]
    expected = [
        {"tool": "plan_toll_route", "input": {"origin": "Dumfries"}},
        {"tool": "i495_route", "input": {"destination": "Westpark Drive"}},
    ]
    normal = [
        {
            "name": call["tool"],
            "input": call["input"],
            "tool_result": "{}",
            "is_error": False,
        }
        for call in expected
    ]
    duplicate = {**normal[0], "is_error": True, "tool_result": DUPLICATE_MESSAGE}

    assert evaluate_guard_calls([normal], [expected])[0].label == "guard_ok"
    assert (
        evaluate_guard_calls([[normal[0], duplicate, normal[1]]], [expected])[0].label
        == "guard_ok"
    )
    assert (
        evaluate_guard_calls([[normal[0], normal[0], normal[1]]], [expected])[0].label
        == "duplicate_success"
    )
    changed = {**normal[0], "input": {"origin": "Cardinal Drive"}}
    changed_expected = [
        expected[0],
        {"tool": "plan_toll_route", "input": changed["input"]},
    ]
    assert (
        evaluate_guard_calls([[normal[0], changed]], [changed_expected])[0].label
        == "guard_ok"
    )
    assert (
        evaluate_guard_calls([[duplicate, normal[1]]], [expected])[0].label
        == "orphan_suppression"
    )
    assert evaluate_guard_calls([[normal[0]]], [expected])[0].label == "tool_mismatch"
    print("self-check ok (normal, suppression, changed input, and failure branches)")


if __name__ == "__main__":
    _self_check() if "--check" in sys.argv else main()
