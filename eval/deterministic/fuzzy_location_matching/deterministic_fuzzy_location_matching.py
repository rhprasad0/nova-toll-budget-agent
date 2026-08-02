"""Runs the Strands Evals experiment for TollChat's fuzzy location-matching
and clarification behavior (see eval-plan.md). Both evaluators are
code-based, not LLM-judged: this evaluation only tests whether the agent's
Step 1 location resolution (agent-sops/nova-toll-pricing-assistant.sop.md)
asks before guessing an ambiguous location, converges to the exact oracle
label once the user picks one, resolves an unambiguous case-insensitive
match without asking, and never fabricates a price for an uncovered road.

Requires AWS_PROFILE=nova-toll (OpenAI key via SSM) and tailnet RDS access
to actually invoke the agent -- run explicitly, same convention as
tests/test_toll_agent_live.py. main() calls
agent.dev_chat.configure_local_pricing_env() first, the same
DB_HOST/DB_PORT-via-describe_db_instances + pricing_reader-defaults setup
the local dev console already uses, instead of expecting the caller's shell
to have exported those itself. `--check` runs the per-turn matching logic
against synthetic trajectories only, no network calls, and does not call
configure_local_pricing_env().
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

from strands.types.content import Messages  # noqa: E402
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
_PRICE_RE = re.compile(
    r"(?:\$\s*\d+(?:\.\d{1,2})?|\bUSD\s*\d+(?:\.\d{1,2})?\b|"
    r"\b\d+(?:\.\d{1,2})?\s*(?:USD|dollars?|bucks?)\b)",
    re.IGNORECASE,
)


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row: dict[str, Any] = json.loads(line)
        expected_tools = [
            step["tool"] for step in row["expected_trajectory"] if step.get("tool")
        ]
        cases.append(
            Case[str, str](
                name=row["id"],
                input=row["conversation"][0]["content"],
                expected_trajectory=expected_tools,
                metadata=row,
            )
        )
    return cases


def _contains_price(text: str) -> bool:
    return _PRICE_RE.search(text) is not None


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _report_passed(test_passes: list[bool]) -> bool:
    return all(test_passes)


def _metadata(case: Case[str, str]) -> dict[str, Any]:
    assert case.metadata is not None
    return case.metadata


def _turns(evaluation_case: EvaluationData[str, str]) -> list[dict[str, Any]]:
    trajectory = evaluation_case.actual_trajectory
    return (
        cast(list[dict[str, Any]], trajectory) if isinstance(trajectory, list) else []
    )


def _extract_tool_calls(messages: Messages) -> list[dict[str, Any]]:
    # extract_agent_tools_used_from_messages returns tool-call records
    # ({"name", "input", "tool_result", "is_error"}), not plain name
    # strings -- confirmed against the installed strands_evals package.
    return tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        messages
    )


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    turns: list[dict[str, str]] = _metadata(case)["conversation"]
    trajectory_by_turn: list[dict[str, Any]] = []
    response = None
    for turn in turns:
        before = len(agent.messages)
        response = agent(turn["content"])
        calls = _extract_tool_calls(agent.messages[before:])
        trajectory_by_turn.append({"response": str(response), "calls": calls})
    return {
        "output": str(response),
        "trajectory": trajectory_by_turn,
    }


class LocationResolutionEvaluator(Evaluator[str, str]):
    """Per-turn check of expected response behavior and exact tool calls."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        metadata: dict[str, Any] = evaluation_case.metadata or {}
        expected_turns: list[dict[str, Any]] = metadata.get("expected_trajectory", [])
        trajectory_by_turn = _turns(evaluation_case)

        for entry in expected_turns:
            turn_index = cast(int, entry["turn"]) - 1
            turn = (
                trajectory_by_turn[turn_index]
                if turn_index < len(trajectory_by_turn)
                else {}
            )
            actual_calls: list[dict[str, Any]] = turn.get("calls", [])
            expected_tool = entry.get("tool")

            response = str(turn.get("response", ""))
            expected_terms: list[str] = entry.get("response_must_contain_any", [])
            if (
                expected_terms
                and not any(
                    term.casefold() in response.casefold() for term in expected_terms
                )
            ) or (entry.get("response_must_be_question") and "?" not in response):
                return _result(
                    False,
                    f"turn {entry['turn']}: response did not match expected behavior",
                    "response_mismatch",
                )

            if expected_tool is None:
                if actual_calls:
                    return _result(
                        False,
                        f"turn {entry['turn']}: expected no tool call, got "
                        f"{[c['name'] for c in actual_calls]}",
                        "premature_tool_call",
                    )
                continue

            if len(actual_calls) != 1 or actual_calls[0]["name"] != expected_tool:
                return _result(
                    False,
                    f"turn {entry['turn']}: expected exactly one call to "
                    f"{expected_tool!r}, got {[c['name'] for c in actual_calls]}",
                    "tool_mismatch",
                )

            expected_input: dict[str, Any] = entry.get("input", {})
            actual_input: dict[str, Any] = actual_calls[0]["input"]
            # Subset match, not full dict equality: tools like i495_route
            # accept an optional at_time the case doesn't pin, and the
            # metric under test is the origin/destination hard label, not
            # every argument shape.
            labels_match = all(
                actual_input.get(key) == value for key, value in expected_input.items()
            )
            if not labels_match:
                return _result(
                    False,
                    f"turn {entry['turn']}: {expected_tool} called with "
                    f"{actual_input}, expected exact hard labels {expected_input}",
                    "label_mismatch",
                )

        return _result(
            True,
            "every turn matched its expected tool call (or absence)",
            "resolved",
        )


class NoFabricatedPriceEvaluator(Evaluator[str, str]):
    """For cases marked expect_no_price: no pricing tool ever fired across
    the whole conversation, and the final response states no dollar amount."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        metadata: dict[str, Any] = evaluation_case.metadata or {}
        if not metadata.get("expect_no_price"):
            return _result(
                True,
                "case does not require a price-free response",
                "not_applicable",
            )

        any_tool_called = any(turn.get("calls", []) for turn in _turns(evaluation_case))
        contains_price = _contains_price(str(evaluation_case.actual_output or ""))

        if any_tool_called or contains_price:
            return _result(
                False,
                "expected a coverage decline with no tool call and no price, got "
                f"tool_called={any_tool_called} contains_price={contains_price}",
                "fabricated_or_substituted",
            )
        return _result(
            True,
            "no pricing tool called and no price stated",
            "declined_cleanly",
        )


def main() -> None:
    configure_local_pricing_env()
    cases = load_cases()
    experiment = Experiment[str, str](
        cases=cases,
        evaluators=[
            LocationResolutionEvaluator(),
            NoFabricatedPriceEvaluator(),
        ],
    )
    report = experiment.run_evaluations(task_function)

    _RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report.to_file(str(_RESULTS_DIR / f"{stamp}.json"))

    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    if not _report_passed(report.test_passes):
        raise SystemExit("deterministic fuzzy-location evaluation failed")


def _self_check() -> None:
    """Exercise the pure matching logic against synthetic trajectories."""
    cases = load_cases()
    assert [case.name for case in cases] == [
        "ambiguous-alias-mclean-multiturn",
        "unambiguous-case-insensitive-single-turn",
        "uncovered-road-no-substitution",
    ]
    assert cases[1].expected_trajectory == ["i95_route"]
    assert cases[2].expected_trajectory == []
    assert _report_passed([True, True])
    assert not _report_passed([True, False])

    for price in ("$4.25", "4.25 dollars", "USD 4.25"):
        assert _contains_price(price)
    assert not _contains_price("no price here")

    def _fake_case(
        metadata: dict[str, Any],
        trajectory: list[dict[str, Any]],
        actual_output: str = "",
    ) -> EvaluationData[str, str]:
        return EvaluationData[str, str](
            input="x",
            actual_output=actual_output,
            actual_trajectory=trajectory,
            metadata=metadata,
        )

    resolver = LocationResolutionEvaluator()
    expected_route = {
        "turn": 1,
        "tool": "i495_route",
        "input": {"origin": "A", "destination": "B"},
    }
    actual_route = {
        "name": "i495_route",
        "input": {"origin": "A", "destination": "B", "at_time": None},
    }
    clarification = {
        "turn": 1,
        "tool": None,
        "response_must_be_question": True,
        "response_must_contain_any": ["I-495", "I-66"],
    }
    resolver_checks: list[tuple[dict[str, Any], list[dict[str, Any]], str]] = [
        (
            {"expected_trajectory": [expected_route]},
            [{"response": "", "calls": [actual_route]}],
            "resolved",
        ),
        (
            {
                "expected_trajectory": [clarification],
            },
            [{"response": "I cannot help with that.", "calls": []}],
            "response_mismatch",
        ),
        (
            {
                "expected_trajectory": [clarification],
            },
            [{"response": "Did you mean I-495 or I-66?", "calls": []}],
            "resolved",
        ),
        (
            {"expected_trajectory": [{"turn": 1, "tool": None}]},
            [{"response": "", "calls": [actual_route]}],
            "premature_tool_call",
        ),
        (
            {
                "expected_trajectory": [expected_route],
            },
            [
                {
                    "response": "",
                    "calls": [
                        {
                            "name": "i495_route",
                            "input": {"origin": "a-ish", "destination": "B"},
                        }
                    ],
                }
            ],
            "label_mismatch",
        ),
    ]
    for metadata, trajectory, label in resolver_checks:
        assert resolver.evaluate(_fake_case(metadata, trajectory))[0].label == label

    transport_case = Case[str, str](
        name="trajectory-transport",
        input="x",
        metadata={"expected_trajectory": [clarification]},
    )

    def _transport_task(_: Case[str, str]) -> dict[str, Any]:
        return {
            "output": "Did you mean I-495 or I-66?",
            "trajectory": [{"response": "Did you mean I-495 or I-66?", "calls": []}],
        }

    report = Experiment[str, str](
        cases=[transport_case], evaluators=[LocationResolutionEvaluator()]
    ).run_evaluations(_transport_task)
    assert report.test_passes == [True]

    price_check = NoFabricatedPriceEvaluator()
    for expect_no_price, output, label in (
        (True, "That road is outside coverage.", "declined_cleanly"),
        (True, "That trip costs 3.50 dollars.", "fabricated_or_substituted"),
        (False, "", "not_applicable"),
    ):
        price_metadata: dict[str, Any] = {
            "expect_no_price": expect_no_price,
        }
        assert (
            price_check.evaluate(_fake_case(price_metadata, [], output))[0].label
            == label
        )

    print("self-check ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
