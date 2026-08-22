# pyright: basic
"""Code-grade Westpark current-toll routing regressions."""

from __future__ import annotations

import json
import os
import re
import sys
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import boto3
from strands.types.content import Message, Messages
from strands_evals import Case, Experiment
from strands_evals.evaluators import Evaluator
from strands_evals.extractors import tools_use_extractor
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput

_V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2_ROOT))

from agent.toll_agent import build_agent  # noqa: E402

_CASES_PATH = Path(__file__).with_name("test-cases.jsonl")
_RESULTS_DIR = Path(__file__).with_name("results")
_PROFILE = {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll",
}
_EMOJIS = ("🚗", "💵", "🛣️", "📈", "📉", "➡️", "🔄", "⚠️", "🎉", "✅", "🚧")


def load_rows(path: Path = _CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_cases(path: Path = _CASES_PATH, suite: str = "all") -> list[Case[str, str]]:
    return [
        Case[str, str](name=row["id"], input=row["prompt"], metadata=row)
        for row in load_rows(path)
        if suite == "all" or row.get("suite") == suite
    ]


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _tool_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    for item in result.get("content", []):
        if isinstance(item, dict) and isinstance(item.get("json"), dict):
            return cast(dict[str, Any], item["json"])
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            try:
                value = json.loads(item["text"])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return cast(dict[str, Any], value)
    return None


def _trace_messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        messages = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [message for trace in traces for message in walk(trace)]


def _calls(response: object) -> list[dict[str, Any]]:
    summary = cast(dict[str, Any], cast(Any, response).metrics.get_summary())
    messages = _trace_messages(cast(list[dict[str, Any]], summary.get("traces", [])))
    calls = cast(
        list[dict[str, Any]],
        tools_use_extractor.extract_agent_tools_used_from_messages(messages),
    )
    tool_ids = [
        block["toolUse"]["toolUseId"]
        for message in messages
        if message.get("role") == "assistant"
        for block in message.get("content", [])
        if "toolUse" in block
    ]
    results = {
        result["toolUseId"]: result
        for message in messages
        if message.get("role") == "user"
        for block in message.get("content", [])
        if (result := block.get("toolResult"))
    }
    for call, tool_id in zip(calls, tool_ids, strict=True):
        result = cast(dict[str, Any], results.get(tool_id, {}))
        call["tool_result"] = _tool_payload(result)
        call["is_error"] = result.get("status") == "error"
    return calls


def evaluate_westpark_turn(
    calls: list[dict[str, Any]], response: str, metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if len(calls) != 1 or calls[0].get("name") != "get_current_toll_price":
        return _result(
            False, "expected exactly one current-price call", "tool_mismatch"
        )
    call = calls[0]
    if call.get("input") != metadata["expected_call"]:
        return _result(False, "current-price arguments did not match", "input_mismatch")
    payload = call.get("tool_result")
    if call.get("is_error") or not isinstance(payload, dict) or "error" in payload:
        return _result(False, "current-price tool returned an error", "tool_error")
    expected = metadata["expected_call"]
    point_ids = payload.get("point_ids", [])
    actual_origin = payload.get("origin_point_id") or (
        point_ids[0] if isinstance(point_ids, list) and point_ids else None
    )
    actual_destination = payload.get("destination_point_id") or (
        point_ids[-1] if isinstance(point_ids, list) and point_ids else None
    )
    if (
        actual_origin != expected["origin_point_id"]
        or actual_destination != expected["destination_point_id"]
    ):
        return _result(False, "tool result endpoints did not match", "result_mismatch")

    if "total_usd" in payload:
        expected_price = f"${payload['total_usd']}"
        if expected_price not in response:
            return _result(
                False, f"response omitted {expected_price}", "ungrounded_price"
            )
        if len(payload.get("components", [])) != 2:
            return _result(
                False, "priced route did not contain two components", "bad_route"
            )
        if "EST" not in response:
            return _result(False, "response omitted observation time", "missing_time")
    elif payload.get("status") == "currently_unavailable":
        if not any(term in response.casefold() for term in ("unavailable", "closed")):
            return _result(False, "closure result was not explained", "missing_closure")
    else:
        return _result(
            False, "tool returned no usable current toll", "tool_unavailable"
        )

    if not any(mark in response for mark in ("#", "**", "- ")):
        return _result(False, "response did not use Markdown", "missing_markdown")
    if not any(emoji in response for emoji in _EMOJIS):
        return _result(False, "response did not include an emoji", "missing_emoji")
    return _result(True, "exact route call and grounded response passed", "passed")


def evaluate_restart_turns(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if len(turns) != 2:
        return _result(False, "expected exactly two conversation turns", "turn_count")
    expected_calls = metadata["expected_calls"]
    for index, turn in enumerate(turns):
        calls = turn.get("calls", [])
        if len(calls) != 1 or calls[0].get("name") != "get_current_toll_price":
            return _result(
                False,
                f"turn {index + 1} expected exactly one current-price call",
                "tool_mismatch",
            )
        if calls[0].get("input") != expected_calls[index]:
            return _result(
                False, f"turn {index + 1} used the wrong endpoints", "input_mismatch"
            )
        if calls[0].get("is_error"):
            return _result(False, f"turn {index + 1} tool failed", "tool_error")

    initial_call = turns[0]["calls"][0]
    initial_payload = initial_call.get("tool_result")
    if not isinstance(initial_payload, dict) or initial_payload.get("status") != (
        "invalid_origin"
    ):
        return _result(False, "initial result was not invalid_origin", "bad_route")
    reason = initial_payload.get("reason", {})
    details = reason.get("details", {}) if isinstance(reason, dict) else {}
    if (
        reason.get("code") != "i95_northbound_requires_i495_restart"
        or details.get("suggested_restart_point_id") != "i495:192NO"
        or details.get("suggested_destination_point_id") != "i495:185ND"
        or "alternatives" in details
    ):
        return _result(False, "initial restart contract was malformed", "bad_route")

    initial_response = str(turns[0].get("response", ""))
    folded = initial_response.casefold()
    if not (
        any(term in folded for term in ("would you like", "want me to", "should i"))
        and "i-495" in folded
        and "general-purpose" in folded
        and re.search(r"not (?:be )?included", folded)
    ):
        return _result(False, "restart offer or disclosure was missing", "bad_offer")
    if re.search(r"\$\s*\d", initial_response) or any(
        name in folded for name in ("edsall", "seminary")
    ):
        return _result(
            False, "initial offer included a price or bad alternative", "bad_offer"
        )

    accepted_call = turns[1]["calls"][0]
    accepted_payload = accepted_call.get("tool_result")
    if not isinstance(accepted_payload, dict) or "total_usd" not in accepted_payload:
        return _result(False, "accepted restart returned no price", "tool_unavailable")
    accepted_response = str(turns[1].get("response", ""))
    if f"${accepted_payload['total_usd']}" not in accepted_response:
        return _result(
            False, "accepted response omitted the tool price", "ungrounded_price"
        )
    if "EST" not in accepted_response:
        return _result(
            False, "accepted response omitted observation time", "missing_time"
        )
    if not any(mark in accepted_response for mark in ("#", "**", "- ")):
        return _result(False, "accepted response omitted Markdown", "missing_markdown")
    if not any(emoji in accepted_response for emoji in _EMOJIS):
        return _result(False, "accepted response omitted an emoji", "missing_emoji")
    return _result(True, "restart offer and accepted TP1NB price passed", "passed")


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    turns = []
    response: object = ""
    previous_call_count = 0
    for prompt in (case.metadata or {}).get("conversation", [str(case.input)]):
        response = agent(prompt)
        all_calls = _calls(response)
        turns.append(
            {"response": str(response), "calls": all_calls[previous_call_count:]}
        )
        previous_call_count = len(all_calls)
    return {"output": str(response), "trajectory": turns}


class WestparkEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        trajectory = evaluation_case.actual_trajectory
        turns = (
            cast(list[dict[str, Any]], trajectory)
            if isinstance(trajectory, list)
            else []
        )
        metadata = evaluation_case.metadata or {}
        if metadata.get("suite") == "restart":
            return evaluate_restart_turns(turns, metadata)
        calls = turns[0].get("calls", []) if len(turns) == 1 else []
        return evaluate_westpark_turn(
            cast(list[dict[str, Any]], calls),
            str(evaluation_case.actual_output or ""),
            metadata,
        )


def _configure_database() -> None:
    os.environ.setdefault("DB_NAME", "nova_toll")
    default_ca = Path("infra/build/ca/rds-ca-bundle.pem")
    if default_ca.exists():
        os.environ.setdefault("DB_CA_BUNDLE_PATH", str(default_ca))
    if "DB_HOST" not in os.environ or "DB_PORT" not in os.environ:
        instance = boto3.client("rds", region_name="us-east-1").describe_db_instances(
            DBInstanceIdentifier="nova-toll-db"
        )["DBInstances"][0]
        os.environ["DB_HOST"] = instance["Endpoint"]["Address"]
        os.environ["DB_PORT"] = str(instance["Endpoint"]["Port"])


def main(suite: str = "all") -> None:
    _configure_database()
    report = Experiment[str, str](
        cases=load_cases(suite=suite), evaluators=[WestparkEvaluator()]
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    report.display(include_input=False)
    if not all(report.test_passes):
        raise SystemExit("Westpark evaluation failed")


def _self_check() -> None:
    rows = load_rows()
    assert [row["id"] for row in rows] == [
        "reagan-airport-to-westpark",
        "pentagon-eads-to-westpark",
        "northbound-i95-to-westpark-restart",
    ]
    metadata = rows[0]
    success = {
        "name": "get_current_toll_price",
        "input": metadata["expected_call"],
        "tool_result": {
            "origin_point_id": "airport_dca",
            "destination_point_id": "i495:1859ND",
            "total_usd": "16.40",
            "components": [{"route_step_id": "step-1"}, {"route_step_id": "step-2"}],
        },
        "is_error": False,
    }
    good_response = "### 🚗 Current toll\n\n**Estimate: $16.40** at 9:30 AM EST."
    assert evaluate_westpark_turn([success], good_response, metadata)[0].test_pass
    assert (
        evaluate_westpark_turn([], good_response, metadata)[0].label == "tool_mismatch"
    )
    wrong_input = {
        **success,
        "input": {**metadata["expected_call"], "destination_point_id": "wrong"},
    }
    assert (
        evaluate_westpark_turn([wrong_input], good_response, metadata)[0].label
        == "input_mismatch"
    )
    error = {**success, "tool_result": {"error": "pricing_unavailable"}}
    assert (
        evaluate_westpark_turn([error], good_response, metadata)[0].label
        == "tool_error"
    )
    assert (
        evaluate_westpark_turn([success], "$16.40 at 9:30 AM EST", metadata)[0].label
        == "missing_markdown"
    )
    closure = {
        **success,
        "tool_result": {
            "status": "currently_unavailable",
            "point_ids": ["airport_dca", "i495:1859ND"],
        },
    }
    assert evaluate_westpark_turn([closure], "### 🚧 Closed", metadata)[0].test_pass
    restart = rows[2]
    restart_turns = [
        {
            "response": (
                "### 🛣️ Start after the junction\n\nWould you like me to price "
                "from I-495? The general-purpose segment is not included."
            ),
            "calls": [
                {
                    "name": "get_current_toll_price",
                    "input": restart["expected_calls"][0],
                    "tool_result": {
                        "status": "invalid_origin",
                        "reason": {
                            "code": "i95_northbound_requires_i495_restart",
                            "details": {
                                "point_id": "i95:206NO",
                                "point_type": "entry",
                                "suggested_restart_point_id": "i495:192NO",
                                "suggested_destination_point_id": "i495:185ND",
                            },
                        },
                    },
                    "is_error": False,
                }
            ],
        },
        {
            "response": "### 🚗 Current toll\n\n**Estimate: $4.50** at 9:30 AM EST.",
            "calls": [
                {
                    "name": "get_current_toll_price",
                    "input": restart["expected_calls"][1],
                    "tool_result": {
                        "origin_point_id": "i495:192NO",
                        "destination_point_id": "i495:185ND",
                        "total_usd": "4.50",
                    },
                    "is_error": False,
                }
            ],
        },
    ]
    assert evaluate_restart_turns(restart_turns, restart)[0].test_pass
    bad_offer = json.loads(json.dumps(restart_turns))
    bad_offer[0]["response"] += " Try Edsall Road."
    assert evaluate_restart_turns(bad_offer, restart)[0].label == "bad_offer"
    print("self-check ok (fixtures and evaluator pass/fail branches; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        parser = ArgumentParser()
        parser.add_argument(
            "--suite", choices=("all", "direct", "restart"), default="all"
        )
        main(parser.parse_args().suite)
