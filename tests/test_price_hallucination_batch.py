from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.deterministic.price_hallucination.batch import (
    build_multi_leg_requests,
    build_single_leg_requests,
    write_gate3_packet,
    write_multi_leg_packet,
)


def _case() -> dict:
    return {
        "id": "single_leg:i95-001",
        "stratum": "single_leg",
        "source": {
            "evidence_sha256": "e" * 64,
            "evidence": {
                "calls": [
                    {
                        "tool": "i95_route",
                        "input": {"origin": "A", "destination": "B"},
                        "result": {"total_usd": "7.80"},
                    }
                ]
            },
        },
        "prompts": [f"variant {number}" for number in range(1, 6)],
    }


def test_gate3_renders_production_parity_and_cost_ceiling(tmp_path: Path) -> None:
    requests, report = build_single_leg_requests([_case()], expected_requests=5)

    assert [request["custom_id"] for request in requests] == [
        f"single_leg:i95-001:v{number}" for number in range(1, 6)
    ]
    body = requests[0]["body"]
    assert body["model"] == "gpt-5.6-luna"
    assert body["max_output_tokens"] == 2048
    assert body["reasoning"] == {"effort": "low"}
    assert body["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert body["store"] is False
    assert body["tool_choice"] == "none"
    assert "stream" not in body
    assert len(body["tools"]) == 7
    assert body["input"][0]["role"] == "developer"
    assert "8/11/2026" in body["input"][0]["content"][0]["text"]
    assert body["input"][-1]["type"] == "function_call_output"
    assert report["unapproved_payload_differences"] == 0
    assert report["request_count"] == 5
    assert report["maximum_cost_usd"] > 0

    packet = write_gate3_packet([_case()], tmp_path, expected_requests=5)
    lines = (tmp_path / "single-leg-batch.jsonl").read_text().splitlines()
    assert len(lines) == 5
    assert json.loads(lines[0])["custom_id"] == "single_leg:i95-001:v1"
    assert packet["sha256"] in (tmp_path / "gate3-review.md").read_text()
    assert "single-leg-batch.jsonl" in (tmp_path / "gate3-packet.sha256").read_text()

    duplicate = _case()
    with pytest.raises(ValueError, match="unique"):
        build_single_leg_requests([_case(), duplicate], expected_requests=10)


def test_multi_leg_expands_repeats_and_shards_under_batch_limit(
    tmp_path: Path,
) -> None:
    case = _case()
    case["id"] = "multi_leg:i495-dtr-001"
    case["stratum"] = "multi_leg"
    case["source"]["evidence"]["calls"].append(
        {
            "tool": "dulles_route",
            "input": {"origin": "B", "destination": "C"},
            "result": {"total_usd": "2.00"},
        }
    )

    requests, report = build_multi_leg_requests(
        [case], repetitions=2, expected_requests=10
    )

    assert requests[0]["custom_id"] == "multi_leg:i495-dtr-001:v1:r01"
    assert requests[-1]["custom_id"] == "multi_leg:i495-dtr-001:v5:r02"
    assert [item.get("type") for item in requests[0]["body"]["input"]] == [
        "message",
        None,
        "function_call",
        "function_call",
        "function_call_output",
        "function_call_output",
    ]
    assert report["repetitions"] == 2
    assert report["unapproved_payload_differences"] == 0

    packet = write_multi_leg_packet(
        [case],
        tmp_path,
        repetitions=2,
        expected_requests=10,
        shard_request_limit=5,
    )
    shards = sorted(tmp_path.glob("multi-leg-batch-*.jsonl"))
    assert [len(path.read_text().splitlines()) for path in shards] == [5, 5]
    assert packet["shard_count"] == 2
    assert packet["sha256"] in (tmp_path / "gate5-review.md").read_text()
    assert all(size < 200_000_000 for size in packet["shard_bytes"])
