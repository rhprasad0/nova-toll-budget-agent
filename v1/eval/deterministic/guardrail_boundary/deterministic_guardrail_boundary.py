"""Code-grade the deployed Bedrock Guardrail without invoking a model."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

import boto3

_CASES_PATH = Path(__file__).with_name("test-cases.jsonl")
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"


class GuardrailClient(Protocol):
    def apply_guardrail(self, **kwargs: object) -> dict[str, Any]: ...


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in _CASES_PATH.read_text().splitlines() if line]


def _blocked_categories(response: dict[str, Any]) -> list[str]:
    return sorted(
        str(item["type"])
        for assessment in response.get("assessments", [])
        for item in assessment.get("contentPolicy", {}).get("filters", [])
        if item.get("action") == "BLOCKED"
    )


def evaluate(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    action = response.get("action")
    categories = _blocked_categories(response)
    expected_category = case.get("expected_category")
    passed = action == case["expected_action"] and (
        expected_category is None or expected_category in categories
    )
    return {
        "id": case["id"],
        "source": case["source"],
        "expected_action": case["expected_action"],
        "actual_action": action,
        "expected_category": expected_category,
        "blocked_categories": categories,
        "passed": passed,
    }


def can_save(version: str) -> bool:
    return version.isdigit() and int(version) > 0


def _self_check() -> None:
    cases = load_cases()
    assert len(cases) == 6
    for case in cases:
        category = case.get("expected_category")
        response = {
            "action": case["expected_action"],
            "assessments": [
                {
                    "contentPolicy": {
                        "filters": (
                            [{"type": category, "action": "BLOCKED"}]
                            if category
                            else []
                        )
                    }
                }
            ],
        }
        assert evaluate(case, response)["passed"]
    assert not can_save("DRAFT")
    print("self-check ok (six guardrail boundary cases; no network)")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--guardrail-id")
    parser.add_argument("--guardrail-version")
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE"))
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument("--save", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    if args.check:
        _self_check()
        return
    if not args.guardrail_id or not args.guardrail_version:
        raise SystemExit("--guardrail-id and --guardrail-version are required")
    if args.save and not can_save(args.guardrail_version):
        raise SystemExit("only numbered guardrail versions may be curated")

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = cast(
        GuardrailClient,
        session.client("bedrock-runtime"),  # pyright: ignore[reportUnknownMemberType]
    )
    results: list[dict[str, Any]] = []
    for case in load_cases():
        response = client.apply_guardrail(
            guardrailIdentifier=args.guardrail_id,
            guardrailVersion=args.guardrail_version,
            source=case["source"],
            outputScope="FULL",
            content=[{"text": {"text": case["content"]}}],
        )
        results.append(evaluate(case, response))

    passed = all(result["passed"] for result in results)
    report: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "issue": 69,
        "status": "passed" if passed else "failed",
        "scenario": "Bedrock Guardrail input/output boundary regression",
        "evidence_type": "Metadata-only live ApplyGuardrail evaluation",
        "guardrail_id": args.guardrail_id,
        "guardrail_version": args.guardrail_version,
        "aws_region": args.region,
        "cases": results,
        "summary": {
            "passed": sum(result["passed"] for result in results),
            "total": len(results),
        },
    }
    print(json.dumps(report, indent=2))
    if not passed:
        raise SystemExit("guardrail boundary evaluation failed")
    if args.save:
        _RESULTS_DIR.mkdir(exist_ok=True)
        output = (
            _RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-guardrail-boundary.json"
        )
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(output, file=sys.stderr)


if __name__ == "__main__":
    main()
