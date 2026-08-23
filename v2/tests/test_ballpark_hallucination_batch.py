# pyright: basic

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval import ballpark_hallucination_batch as batch


def _case() -> dict[str, object]:
    request = {
        "outbound": {
            "origin_point_id": "i95:206NO",
            "destination_point_id": "i495:185ND",
            "departure_time": "08:30:00",
        },
        "return": {
            "origin_point_id": "i495:185SO",
            "destination_point_id": "i95:206SD",
            "departure_time": "17:30:00",
        },
        "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
        "planned_annual_commute_days": 240,
        "gross_annual_income_usd": "120000.00",
    }
    payload = {
        "evaluated_at": "2026-08-22T17:15:34-04:00",
        "target_window": {
            "start_date": "2026-05-30",
            "end_date": "2026-08-21",
            "date_count": 84,
        },
        "coverage": {
            "eligible_date_count": 60,
            "complete_pair_count": 50,
            "coverage_percent": "83.3",
            "by_weekday": [],
        },
        "income": {
            "gross_annual_usd": "120000.00",
            "estimated_after_tax_usd": "80000.00",
        },
        "assumptions": {
            "estimated_tax_fraction": "1/3",
            "vehicle_cost_per_mile_usd": "0.685",
        },
        "sample_status": "partial",
        "available_date_range": {
            "start_date": "2026-06-01",
            "end_date": "2026-08-21",
        },
        "scenarios": {
            "p50": {
                "daily_toll_usd": "58.70",
                "annual_toll_usd": "14088.00",
                "tolled_commute_share_of_after_tax_income_percent": "22.4",
            }
        },
    }
    return {
        "id": "springfield-westpark-0830-1730",
        "request": request,
        "prompts": [f"prompt {number}" for number in range(1, 6)],
        "source": {
            "tool_result": {
                "toolUseId": "call_ballpark_springfield_westpark",
                "status": "success",
                "content": [{"json": payload}],
            }
        },
    }


def _output(custom_id: str, text: str = "grounded") -> str:
    return json.dumps(
        {
            "custom_id": custom_id,
            "response": {
                "status_code": 200,
                "body": {
                    "status": "completed",
                    "incomplete_details": None,
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": text}],
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                },
            },
            "error": None,
        }
    )


def test_builds_production_shaped_rows_and_counts_exact_packet() -> None:
    requests = batch.build_requests(_case(), "developer prompt", repetitions=2)

    assert len(requests) == 10
    assert len({request["custom_id"] for request in requests}) == 10
    assert requests[0]["custom_id"].endswith(":v1:r001")
    body = requests[0]["body"]
    assert body["model"] == "gpt-5.6-luna"
    assert body["tool_choice"] == "none"
    assert body["store"] is False
    assert "stream" not in body
    assert {tool["name"] for tool in body["tools"]} == {
        "get_current_toll_price",
        "get_annual_toll_ballpark",
    }

    packet = batch.serialize_requests(requests)
    report = batch.preflight(packet)

    assert report["request_count"] == 10
    assert report["jsonl_bytes"] == len(packet.encode())
    assert report["jsonl_sha256"] == hashlib.sha256(packet.encode()).hexdigest()
    assert (
        report["guarded_queued_tokens"] == (report["tiktoken_tokens"] * 110 + 99) // 100
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("request_count", 50_001, "50,000"),
        ("jsonl_bytes", 200_000_001, "200,000,000"),
        ("tiktoken_tokens", 36_363_637, "40,000,000"),
    ],
)
def test_submission_gate_rejects_official_limits(
    field: str, value: int, message: str
) -> None:
    report = {
        "request_count": 1,
        "jsonl_bytes": 1,
        "tiktoken_tokens": 1,
    }
    report[field] = value

    with pytest.raises(ValueError, match=message):
        batch.enforce_limits(report, active_queued_tokens=0)


def test_submission_gate_includes_active_luna_tokens() -> None:
    report = {
        "request_count": 1_000,
        "jsonl_bytes": 112_000_000,
        "tiktoken_tokens": 35_154_000,
    }

    with pytest.raises(ValueError, match="active"):
        batch.enforce_limits(report, active_queued_tokens=1_300_000)


def test_reconciles_unordered_outputs_and_rejects_missing_or_duplicate_ids() -> None:
    requests = batch.build_requests(_case(), "developer", repetitions=1)
    output = [_output(str(request["custom_id"])) for request in reversed(requests)]

    rows, failures = batch.reconcile_outputs(requests, output, [], status="completed")

    assert failures == []
    assert [row["custom_id"] for row in rows] == sorted(
        str(request["custom_id"]) for request in requests
    )

    with pytest.raises(ValueError, match="missing"):
        batch.reconcile_outputs(requests, output[:-1], [], status="completed")
    with pytest.raises(ValueError, match="duplicate"):
        batch.reconcile_outputs(requests, [*output, output[0]], [], status="completed")


def test_quantitative_grounding_accepts_equivalent_formats_and_flags_inventions() -> (
    None
):
    grounded = (
        "As of 8/22/2026, the 8:30 AM to 5:30 PM plan has 50 of 60 complete "
        "days (83.3%). P50 is $58.70 daily, $14,088 annually, and 22.4% of "
        "$80,000 after-tax income from $120,000 gross using a 1 out of 3 tax "
        "assumption."
    )

    assert batch.find_unsupported_claims(grounded, _case()) == {}

    unsupported = batch.find_unsupported_claims(
        grounded + " Coverage was 51 of 60 on 7/4/2027 at 9:45 AM, costing $99,999 or "
        "44% under one estimate and 45 percent under another.",
        _case(),
    )

    assert unsupported == {
        "money": ["99999"],
        "percent": ["44", "45"],
        "coverage": ["51 of 60"],
        "dates": ["2027-07-04"],
        "times": ["09:45:00"],
    }


def test_active_queue_counts_only_nonterminal_luna_rows() -> None:
    luna = batch.serialize_requests(
        batch.build_requests(_case(), "developer", repetitions=1)
    )
    other = luna.replace("gpt-5.6-luna", "gpt-4.1")
    batches = [
        SimpleNamespace(status="in_progress", input_file_id="luna"),
        SimpleNamespace(status="completed", input_file_id="done"),
        SimpleNamespace(status="validating", input_file_id="other"),
    ]

    class Client:
        class batches:
            @staticmethod
            def list(*, limit: int):
                assert limit == 100
                return batches

        class files:
            @staticmethod
            def content(file_id: str):
                return SimpleNamespace(text={"luna": luna, "other": other}[file_id])

    assert batch.active_luna_tokens(Client) == batch.preflight(luna)["tiktoken_tokens"]


def test_submit_uploads_exact_packet_and_persists_batch_ids(tmp_path: Path) -> None:
    requests = batch.build_requests(_case(), "developer", repetitions=1)
    packet = batch.serialize_requests(requests)
    packet_path = tmp_path / "input.jsonl"
    packet_path.write_text(packet)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "input_path": packet_path.name,
                "preflight": batch.preflight(packet),
                "batch_id": None,
            }
        )
    )
    uploads: list[bytes] = []

    class Client:
        class files:
            @staticmethod
            def create(*, file, purpose: str):
                assert purpose == "batch"
                uploads.append(file.read())
                return SimpleNamespace(id="file-123")

            @staticmethod
            def content(_file_id: str):
                raise AssertionError("no active batches expected")

        class batches:
            @staticmethod
            def list(*, limit: int):
                assert limit == 100
                return []

            @staticmethod
            def create(**kwargs):
                assert kwargs["endpoint"] == "/v1/responses"
                assert kwargs["completion_window"] == "24h"
                return SimpleNamespace(id="batch-123", status="validating")

    manifest = batch.submit(manifest_path, Client)

    assert uploads == [packet.encode()]
    assert manifest["batch_id"] == "batch-123"
    assert manifest["input_file_id"] == "file-123"
    assert json.loads(manifest_path.read_text())["batch_id"] == "batch-123"
    with pytest.raises(ValueError, match="already submitted"):
        batch.submit(manifest_path, Client)


def test_submit_recovers_batch_created_before_manifest_was_persisted(
    tmp_path: Path,
) -> None:
    requests = batch.build_requests(_case(), "developer", repetitions=1)
    packet = batch.serialize_requests(requests)
    packet_path = tmp_path / "input.jsonl"
    packet_path.write_text(packet)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "input_path": packet_path.name,
                "input_file_id": "file-123",
                "preflight": batch.preflight(packet),
                "batch_id": None,
            }
        )
    )

    class Client:
        class files:
            @staticmethod
            def content(_file_id: str):
                raise AssertionError("recovery must happen before the queue recount")

        class batches:
            @staticmethod
            def list(*, limit: int):
                assert limit == 100
                return [
                    SimpleNamespace(
                        id="batch-existing",
                        input_file_id="file-123",
                        endpoint="/v1/responses",
                        metadata={
                            "source": "tollchat-v2-ballpark-hallucination",
                            "model": "gpt-5.6-luna",
                        },
                        status="validating",
                    )
                ]

            @staticmethod
            def create(**_kwargs):
                raise AssertionError("an existing Batch must not be duplicated")

    manifest = batch.submit(manifest_path, Client)

    assert manifest["batch_id"] == "batch-existing"
    assert manifest["status"] == "validating"
    assert json.loads(manifest_path.read_text())["batch_id"] == "batch-existing"


def test_prepare_refuses_to_overwrite_a_submitted_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"batch_id": "batch-existing"}))
    monkeypatch.setattr(
        batch,
        "capture_case",
        lambda: pytest.fail("live fixture must not run"),
    )

    with pytest.raises(ValueError, match="submitted Batch"):
        batch.prepare(tmp_path, tmp_path / "fixture.jsonl")


def test_review_includes_all_failures_and_four_passes_per_prompt() -> None:
    verdicts = [
        {
            "custom_id": f"case:v{variant}:r{repetition:03d}",
            "fully_grounded": repetition != 5,
        }
        for variant in range(1, 6)
        for repetition in range(1, 7)
    ]

    review = batch.select_review(verdicts)

    assert len([row for row in review if not row["fully_grounded"]]) == 5
    passing = [row for row in review if row["fully_grounded"]]
    assert len(passing) == 20
    assert {row["custom_id"].split(":")[1] for row in passing} == {
        "v1",
        "v2",
        "v3",
        "v4",
        "v5",
    }


def test_collect_returns_pending_then_grades_terminal_batch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requests = batch.build_requests(_case(), "developer", repetitions=1)
    packet = batch.serialize_requests(requests)
    packet_path = tmp_path / "input.jsonl"
    packet_path.write_text(packet)
    fixture_path = tmp_path / "fixture.jsonl"
    fixture_text = json.dumps(_case()) + "\n"
    fixture_path.write_text(fixture_text)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "batch_id": "batch-123",
                "input_file_id": "input",
                "input_path": packet_path.name,
                "fixture_path": fixture_path.name,
                "fixture_sha256": hashlib.sha256(fixture_text.encode()).hexdigest(),
                "preflight": batch.preflight(packet),
            }
        )
    )
    state = {"status": "in_progress"}
    output = "\n".join(_output(str(row["custom_id"])) for row in requests)

    class Client:
        class batches:
            @staticmethod
            def retrieve(_batch_id: str):
                return SimpleNamespace(
                    status=state["status"],
                    output_file_id="output" if state["status"] == "completed" else None,
                    error_file_id=None,
                )

        class files:
            @staticmethod
            def content(file_id: str):
                assert file_id == "output"
                return SimpleNamespace(text=output)

    assert batch.collect(manifest_path, Client) == {"status": "in_progress"}

    monkeypatch.setattr(
        batch,
        "grade_outputs",
        lambda _case, rows: {"counts": {"responses": len(rows)}, "verdicts": []},
    )
    state["status"] = "completed"
    result = batch.collect(manifest_path, Client)

    assert result["status"] == "completed"
    assert result["counts"] == {"responses": 5, "batch_failures": 0}
    assert (tmp_path / "batch-output.jsonl").read_text().strip() == output
    assert (tmp_path / "results.json").exists()
