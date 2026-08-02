"""Runs the Strands Evals experiment for TollChat's date/time handling (see
eval-plan.md). Both evaluators are code-based, not LLM-judged: this
evaluation only tests whether the agent (1) turns a user-stated date/time
into an `at_time` tool argument that resolves to the correct
America/New_York instant, whether or not the user's phrasing already named
Eastern time, and (2) reports that timestamp back to the user in US
Standard format (SOP Step 4), not the tool's raw ISO-8601 string.

Requires AWS_PROFILE=nova-toll (OpenAI key via SSM) and tailnet RDS access
to actually invoke the agent -- run explicitly, same convention as
tests/test_toll_agent_live.py and the fuzzy-location suite. `--check` runs
the per-case matching logic against synthetic trajectories only, no network
calls, and does not call configure_local_pricing_env().
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

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
from agent_tools._oracle_route import resolve_at_time  # noqa: E402

_CASES_PATH = Path(__file__).resolve().parent / "test-cases.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
_EASTERN = ZoneInfo("America/New_York")
_US_FORMAT_RE = re.compile(
    r"\b(?:1[0-2]|[1-9])/(?:3[01]|[12]\d|[1-9])/\d{4} "
    r"(?:1[0-2]|[1-9]):[0-5]\d (?:AM|PM) ET\b"
)
_NONSTANDARD_DATE_TIME_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?"
    r"(?:Z|[+-]\d{2}:\d{2})?)?"
    r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|\d{1,2}(?::\d{2})?\s*(?:AM|PM)"
    r"|(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*ET)?)\b",
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


def _trace_messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        messages = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [message for trace in traces for message in walk(trace)]


def _extract_tool_calls(messages: Messages) -> list[dict[str, Any]]:
    # extract_agent_tools_used_from_messages returns tool-call records
    # ({"name", "input", "tool_result", "is_error"}), not plain name
    # strings -- confirmed against the installed strands_evals package
    # (same extraction path as deterministic_fuzzy_location_matching.py).
    return tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        messages
    )


def _format_et(value: str) -> str:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=_EASTERN)
    timestamp = timestamp.astimezone(_EASTERN)
    clock = timestamp.strftime("%I:%M %p").lstrip("0")
    return f"{timestamp.month}/{timestamp.day}/{timestamp.year} {clock} ET"


def _tool_timestamps(
    evaluation_case: EvaluationData[str, str],
) -> tuple[list[str], list[str]]:
    turns = _turns(evaluation_case)
    calls = cast(list[dict[str, Any]], turns[0].get("calls", [])) if turns else []
    tool_result: Any = calls[0].get("tool_result") if calls else None
    if tool_result is None:
        return [], []
    if isinstance(tool_result, str):
        try:
            tool_result = json.loads(tool_result)
        except json.JSONDecodeError as error:
            raise ValueError("pricing tool returned invalid JSON") from error
    if not isinstance(tool_result, dict):
        raise ValueError("pricing tool result is not an object")
    result = cast(dict[str, Any], tool_result)
    legs: Any = result.get("legs")
    if legs is None:
        return [], []
    if not isinstance(legs, list):
        raise ValueError("pricing tool result does not contain exactly one leg")
    leg_list = cast(list[Any], legs)
    if len(leg_list) != 1 or not isinstance(leg_list[0], dict):
        raise ValueError("pricing tool result does not contain exactly one leg")
    leg = cast(dict[str, Any], leg_list[0])
    observed_at: Any = leg.get("observed_at")
    if not isinstance(observed_at, str):
        raise ValueError("observed_at is not a string")
    priced_as_of: Any = leg.get("priced_as_of")
    if priced_as_of is not None and not isinstance(priced_as_of, str):
        raise ValueError("priced_as_of is not a string")
    return [observed_at], [observed_at, *([priced_as_of] if priced_as_of else [])]


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    turns: list[dict[str, str]] = _metadata(case)["conversation"]
    trajectory_by_turn: list[dict[str, Any]] = []
    response = None
    for turn in turns:
        response = agent(turn["content"])
        summary: dict[str, Any] = response.metrics.get_summary()
        traces = cast(list[dict[str, Any]], summary.get("traces", []))
        calls = _extract_tool_calls(_trace_messages(traces))
        trajectory_by_turn.append({"response": str(response), "calls": calls})
    return {
        "output": str(response),
        "trajectory": trajectory_by_turn,
    }


class TimeInterpretationEvaluator(Evaluator[str, str]):
    """The tool-called at_time must resolve to the case's expected instant.

    Compares parsed instants, not strings: an at_time carrying an explicit
    non-Eastern offset is just as correct as an Eastern-equivalent naive
    value, as long as both name the same moment. Reuses resolve_at_time --
    the same function the production tools call -- instead of
    reimplementing its naive-value-means-Eastern assumption here.
    """

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        metadata: dict[str, Any] = evaluation_case.metadata or {}
        expected_turns: list[dict[str, Any]] = metadata.get("expected_trajectory", [])
        expected_instant = datetime.fromisoformat(metadata["expected_at_time_instant"])
        trajectory_by_turn = _turns(evaluation_case)

        for entry in expected_turns:
            turn_index = cast(int, entry["turn"]) - 1
            turn = (
                trajectory_by_turn[turn_index]
                if turn_index < len(trajectory_by_turn)
                else {}
            )
            actual_calls: list[dict[str, Any]] = turn.get("calls", [])
            expected_tool = entry["tool"]

            if len(actual_calls) != 1 or actual_calls[0]["name"] != expected_tool:
                return _result(
                    False,
                    f"turn {entry['turn']}: expected exactly one call to "
                    f"{expected_tool!r}, got {[c['name'] for c in actual_calls]}",
                    "tool_mismatch",
                )

            actual_input: dict[str, Any] = actual_calls[0]["input"]
            at_time = actual_input.get("at_time")
            if not at_time:
                return _result(
                    False,
                    f"turn {entry['turn']}: {expected_tool} called with no at_time",
                    "missing_at_time",
                )
            try:
                actual_instant = resolve_at_time(at_time)
            except ValueError as e:
                return _result(
                    False,
                    f"turn {entry['turn']}: at_time {at_time!r} unparseable: {e}",
                    "unparseable_at_time",
                )
            if actual_instant != expected_instant:
                return _result(
                    False,
                    f"turn {entry['turn']}: at_time {at_time!r} resolved to "
                    f"{actual_instant.isoformat()}, expected "
                    f"{expected_instant.isoformat()}",
                    "wrong_instant",
                )

        return _result(True, "at_time resolved to the expected instant", "resolved")


class USFormatEvaluator(Evaluator[str, str]):
    """Tool-returned timestamps must appear exactly in US Standard format."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        response = str(evaluation_case.actual_output or "")
        try:
            observed_at, tool_timestamps = _tool_timestamps(evaluation_case)
            expected_observed_at = {_format_et(value) for value in observed_at}
            allowed_timestamps = {_format_et(value) for value in tool_timestamps}
        except ValueError as error:
            return _result(
                False,
                f"could not read pricing-tool timestamps: {error}",
                "invalid_tool_result",
            )
        expected_instant = (evaluation_case.metadata or {}).get(
            "expected_at_time_instant"
        )
        if expected_instant:
            allowed_timestamps.add(_format_et(expected_instant))

        reported_timestamps = set(_US_FORMAT_RE.findall(response))
        response_without_us_timestamps = _US_FORMAT_RE.sub("", response)
        if _NONSTANDARD_DATE_TIME_RE.search(response_without_us_timestamps):
            return _result(
                False,
                "response contains a date/time outside M/D/YYYY h:MM AM/PM ET",
                "nonstandard_datetime",
            )

        unexpected = reported_timestamps - allowed_timestamps
        if unexpected:
            return _result(
                False,
                f"response contains unexpected timestamp(s): {sorted(unexpected)}",
                "unexpected_datetime",
            )

        missing = expected_observed_at - reported_timestamps
        if missing:
            return _result(
                False,
                f"response omitted tool-returned observed_at value(s): {sorted(missing)}",
                "observed_at_missing",
            )

        mislabeled = {
            value
            for value in expected_observed_at
            if not re.search(rf"VDOT observed at:[\s*_`~]*{re.escape(value)}", response)
        }
        if mislabeled:
            return _result(
                False,
                f"response did not label observed_at value(s): {sorted(mislabeled)}",
                "observed_at_label_missing",
            )

        if reported_timestamps:
            return _result(
                True, "response used exact US-format date/time", "us_formatted"
            )
        return _result(
            True,
            "tool returned no observed_at and response reported no explicit date/time",
            "not_applicable",
        )


def main() -> None:
    configure_local_pricing_env()
    cases = load_cases()
    experiment = Experiment[str, str](
        cases=cases,
        evaluators=[
            TimeInterpretationEvaluator(),
            USFormatEvaluator(),
        ],
    )
    report = experiment.run_evaluations(task_function)

    _RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report.to_file(str(_RESULTS_DIR / f"{stamp}.json"))

    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    if not _report_passed(report.test_passes):
        raise SystemExit("deterministic NY-time/US-format evaluation failed")


def _self_check() -> None:
    """Exercise the pure matching logic against synthetic trajectories."""
    cases = load_cases()
    assert [case.name for case in cases] == [
        "naive-eastern-edt",
        "non-eastern-zone-converted",
        "naive-eastern-est-dst-boundary",
    ]
    assert cases[0].expected_trajectory == ["i495_route"]
    assert _report_passed([True, True])
    assert not _report_passed([True, False])

    assert _format_et("2026-07-15T12:30:00-07:00") == "7/15/2026 3:30 PM ET"

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

    def _trajectory(
        tool_input: dict[str, Any], tool_result: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        call = {"name": "i495_route", "input": tool_input}
        if tool_result is not None:
            call["tool_result"] = json.dumps(tool_result)
        return [{"calls": [call]}]

    time_checker = TimeInterpretationEvaluator()
    time_metadata = {
        "expected_trajectory": [{"turn": 1, "tool": "i495_route"}],
        "expected_at_time_instant": "2026-07-15T17:00:00-04:00",
    }
    time_checks: list[tuple[list[dict[str, Any]], str]] = [
        (
            _trajectory({"at_time": "2026-07-15T14:00:00-07:00"}),
            "resolved",
        ),
        (
            _trajectory({"at_time": "2026-07-15T17:00:00"}),
            "resolved",
        ),
        (
            # Naive passthrough bug: 14:00 assumed Eastern is 3h off from
            # the expected 17:00 Eastern instant (2 PM Pacific).
            _trajectory({"at_time": "2026-07-15T14:00:00"}),
            "wrong_instant",
        ),
        (_trajectory({}), "missing_at_time"),
        (_trajectory({"at_time": "not-a-date"}), "unparseable_at_time"),
        ([{"calls": []}], "tool_mismatch"),
    ]
    for trajectory, label in time_checks:
        assert (
            time_checker.evaluate(_fake_case(time_metadata, trajectory))[0].label
            == label
        ), label

    format_checker = USFormatEvaluator()

    def _format_case(
        output: str,
        tool_result: dict[str, Any],
        expected_at_time: str | None = None,
    ) -> EvaluationData[str, str]:
        metadata = (
            {"expected_at_time_instant": expected_at_time} if expected_at_time else {}
        )
        return _fake_case(
            metadata,
            _trajectory({}, tool_result),
            output,
        )

    success = {
        "legs": [
            {
                "observed_at": "2026-07-15T15:20:00-04:00",
                "priced_as_of": "2026-07-15T15:30:00-04:00",
            }
        ]
    }
    unavailable = {"error": "price unavailable"}
    format_checks = [
        (
            _format_case("VDOT observed at: 7/15/2026 3:20 PM ET", success),
            "us_formatted",
        ),
        (
            _format_case("- **VDOT observed at:** 7/15/2026 3:20 PM ET", success),
            "us_formatted",
        ),
        (
            _format_case(
                "VDOT observed at: 7/15/2026 3:20 PM ET; "
                "priced as of: 7/15/2026 3:30 PM ET",
                success,
            ),
            "us_formatted",
        ),
        (
            _format_case("Requested time: 7/15/2026 3:20 PM ET", success),
            "observed_at_label_missing",
        ),
        (
            _format_case("7/15/2026 3:20 PM ET", success),
            "observed_at_label_missing",
        ),
        (_format_case("The toll is $32.35.", success), "observed_at_missing"),
        (
            _format_case("VDOT observed at: 1/1/1999 1:11 AM ET", success),
            "unexpected_datetime",
        ),
        (
            _format_case(
                "VDOT observed at: 2026-07-15T15:20-04:00; "
                "requested 7/15/2026 3:30 PM ET",
                success,
                "2026-07-15T15:30:00-04:00",
            ),
            "nonstandard_datetime",
        ),
        (
            _format_case(
                "Requested time: November 3, 2026 at 10:00 AM ET; unavailable.",
                unavailable,
                "2026-11-03T10:00:00-05:00",
            ),
            "nonstandard_datetime",
        ),
        (
            _format_case(
                "VDOT observed at: 7/15/2026 3:20 PM ET; requested July 15th, 2026.",
                success,
            ),
            "nonstandard_datetime",
        ),
        (
            _format_case(
                "Requested time: 11/3/2026 at 10 AM ET; unavailable.",
                unavailable,
                "2026-11-03T10:00:00-05:00",
            ),
            "nonstandard_datetime",
        ),
        (
            _format_case(
                "Requested time: 11/3/2026 15:00 ET; unavailable.",
                unavailable,
                "2026-11-03T15:00:00-05:00",
            ),
            "nonstandard_datetime",
        ),
        (
            _format_case(
                "Requested time: 11/3/2026 10:00 AM ET; unavailable.",
                unavailable,
                "2026-11-03T10:00:00-05:00",
            ),
            "us_formatted",
        ),
        (
            _format_case("The requested price is unavailable.", unavailable),
            "not_applicable",
        ),
    ]
    for evaluation_case, label in format_checks:
        assert format_checker.evaluate(evaluation_case)[0].label == label, label

    print("self-check ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
