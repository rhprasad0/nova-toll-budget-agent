"""Manual, cost-only frozen benchmark; never changes application/eval defaults."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Generator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from strands.models import Model

from agent import toll_agent
from eval import golden
from eval import golden_run as run

VERSION = "1.0.0"
EFFORTS = {"agent": "medium", "actor": "low", "judge": "xhigh"}
REPETITIONS = 3
BUDGET = Decimal("2")
ASSET = golden.V2 / "agent/assets/costs-benchmark.json"
RATES = {
    "verified_at": "2026-10-03",
    "source": "https://developers.openai.com/api/docs/models/gpt-6-luna",
    "input_per_million": "0.10",
    "cached_per_million": "0.01",
    "write_per_million": "0.125",
    "output_per_million": "0.50",
    "long_context_threshold": 272000,
    "long_input_multiplier": "2",
    "long_output_multiplier": "1.5",
}


def select_cases(cases: list[golden.GoldenCase]) -> list[golden.GoldenCase]:
    selected: list[golden.GoldenCase] = []
    for family in (
        "current_complete",
        "current_state",
        "current_evidence",
        "annual_complete",
        "annual_inputs",
    ):
        group = [case for case in cases if case.coverage_family == family][:2]
        if len(group) != 2:
            raise ValueError("benchmark family missing")
        selected.extend(group)
    selected.append(
        next(
            case
            for case in cases
            if case.coverage_family == "annual_interpretation"
            and case.terminal_objective == "unavailable"
        )
    )
    selected.append(next(case for case in cases if case.kind == "mixed"))
    return selected


@contextmanager
def model_overrides() -> Generator[None]:
    """Scoped factories; judges retain their existing xhigh configuration."""
    original_agent, original_actor = toll_agent._build_model, run.build_eval_model

    def configured(model: Model, effort: str) -> Model:
        native = cast(Any, model)
        params = deepcopy(native.get_config()["params"])
        params["reasoning"] = {"effort": effort}
        native.update_config(params=params)
        return model

    with (
        patch.object(
            toll_agent,
            "_build_model",
            lambda: configured(original_agent(), EFFORTS["agent"]),
        ),
        patch.object(
            run,
            "build_eval_model",
            lambda: configured(original_actor(), EFFORTS["actor"]),
        ),
    ):
        yield


def charge(item: run.Measurement) -> Decimal:
    """Exact token costs, including cache writes and long-context requests."""
    if not item.complete:
        raise ValueError("unknown usage")
    # Reuse the harness's usage validation, rather than accepting invalid counts.
    run.cost(
        {
            "inputTokens": item.input_tokens,
            "outputTokens": item.output_tokens,
            "cacheReadInputTokens": item.cached_tokens,
            "cacheWriteInputTokens": item.written_tokens,
        }
    )
    long = item.input_tokens > int(RATES["long_context_threshold"])
    input_cost = (
        Decimal(item.input_tokens - item.cached_tokens - item.written_tokens)
        * Decimal(RATES["input_per_million"])
        + Decimal(item.cached_tokens) * Decimal(RATES["cached_per_million"])
        + Decimal(item.written_tokens) * Decimal(RATES["write_per_million"])
    )
    output_cost = Decimal(item.output_tokens) * Decimal(RATES["output_per_million"])
    return (
        input_cost * (Decimal(RATES["long_input_multiplier"]) if long else 1)
        + output_cost * (Decimal(RATES["long_output_multiplier"]) if long else 1)
    ) / 1_000_000


def aggregate(directory: Path, identity: dict[str, Any]) -> dict[str, Any]:
    events = [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text().splitlines()
    ]
    attempts = [
        run.Attempt.model_validate(
            {key: value for key, value in event.items() if key != "event"}
        )
        for event in events
        if event["event"] == "attempt_finished"
    ]
    expected = {
        (case["id"], number)
        for case in identity["cases"]
        for number in range(1, REPETITIONS + 1)
    }
    if (
        len(attempts) != len(expected)
        or {(attempt.case_id, attempt.trial) for attempt in attempts} != expected
        or any(
            not attempt.measurements
            or any(not item.complete for item in attempt.measurements)
            for attempt in attempts
        )
        or sum(event["event"] == "model_started" for event in events)
        != sum(event["event"] == "model_finished" for event in events)
    ):
        raise ValueError("incomplete benchmark")
    roles: dict[str, Any] = {}
    for role in EFFORTS:
        items = [
            item
            for attempt in attempts
            for item in attempt.measurements
            if item.role == role
        ]
        roles[role] = {
            "calls": len(items),
            **{
                field: sum(getattr(item, field) for item in items)
                for field in (
                    "input_tokens",
                    "cached_tokens",
                    "written_tokens",
                    "output_tokens",
                )
            },
            "cost_usd": format(sum((charge(item) for item in items), Decimal(0)), "f"),
        }
    total = sum((Decimal(role["cost_usd"]) for role in roles.values()), Decimal(0))
    if total > BUDGET:
        raise ValueError("benchmark exceeds budget")
    return {
        "schema_version": 1,
        "kind": "controlled-inference-benchmark",
        "status": "complete",
        "currency": "USD",
        "measured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": "gpt-6-luna",
        "reasoning_effort": EFFORTS,
        "max_output_tokens": {"agent": 2048, "actor": 2048, "judge": 8192},
        "rates": RATES,
        "budget_usd": str(BUDGET),
        "provenance": {
            "source_commit": identity["commit"],
            "source_sha256": identity["artifact_sha256"],
            "corpus_version": identity["corpus"]["version"],
            "cases_sha256": golden.digest(identity["cases"]),
            "harness_version": run.VERSION,
            "benchmark_version": VERSION,
            "tool_data": "frozen",
            "processing": "standard",
        },
        "sample": {
            "case_count": len(identity["cases"]),
            "repetitions": REPETITIONS,
            "expected_conversations": len(expected),
            "attempted_conversations": len(attempts),
            # A turn event is emitted only after a terminal, non-truncated response.
            "completed_turns": sum(event["event"] == "turn" for event in events),
            "failed_conversations": sum(
                bool(attempt.application_stop or attempt.error) for attempt in attempts
            ),
            "inconclusive_conversations": sum(
                attempt.status == "inconclusive" for attempt in attempts
            ),
        },
        "roles": roles,
        "total_cost_usd": format(total, "f"),
    }


def publish(snapshot: dict[str, Any]) -> None:
    content = json.dumps(snapshot, indent=2) + "\n"
    gate = golden.V2 / "scripts/cost_dashboard_release.py"
    digest = golden.hashlib.sha256(content.encode()).hexdigest()
    pinned, count = re.subn(
        r'("costs-benchmark.json": ")[0-9a-f]{64}(",)',
        lambda match: match[1] + digest + match[2],
        gate.read_text(),
    )
    if count != 1:
        raise ValueError("benchmark asset pin missing")
    ASSET.write_text(content)
    gate.write_text(pinned)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.resolve()
    if not directory.is_relative_to((golden.V2 / "eval/private").resolve()):
        parser.error("output must be under eval/private/")
    try:
        cases = select_cases(golden.load_cases())
        identity = run.identity(cases)  # Requires validated inputs and a clean commit.
        identity["reasoning_effort"] = EFFORTS
        identity["transport"]["actor_model_config"]["reasoning"] = {"effort": "low"}
        journal = run.Journal(directory, float(BUDGET))
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "purpose": "cost-only; scores do not establish evaluation reliability",
                    "identity": identity,
                    "budget_usd": str(BUDGET),
                    "repetitions": REPETITIONS,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
        key = toll_agent.load_openai_api_key()
        with (
            patch.object(toll_agent, "load_openai_api_key", return_value=key),
            model_overrides(),
        ):
            for number in range(1, REPETITIONS + 1):
                for case in cases:
                    if journal.stop_requested or journal.unknown_usage:
                        break
                    attempt = run.execute(case, number, journal)
                    print(
                        f"Conversation {case.number}, repeat {number}: {attempt.status}; measured spend ${journal.spent:.6f}",
                        flush=True,
                    )
        snapshot = aggregate(directory, identity)
        (directory / "benchmark.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        publish(snapshot)
        print(f"Published 36 conversations; inference ${snapshot['total_cost_usd']}.")
    except Exception as error:
        # Provider exceptions and private evidence never become public output.
        parser.exit(
            1,
            f"Benchmark stopped ({type(error).__name__}); public benchmark retained.\n",
        )


if __name__ == "__main__":
    main()
