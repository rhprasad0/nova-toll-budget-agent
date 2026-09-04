# pyright: basic
# ruff: noqa: ANN401
"""Offline annual-affordability corpus validation and review rendering."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_V2_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _V2_ROOT.parent
sys.path.insert(0, str(_V2_ROOT))
from agent_tools.get_annual_toll_ballpark import (  # noqa: E402
    _OUTPUT_ADAPTER,
    _BallparkRequest,
)

_DEFAULT_MANIFEST = Path(__file__).with_name("golden") / "manifest.json"
_SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
_BEHAVIORS = {
    "missing_inputs",
    "income_clarification",
    "annual_day_estimate",
    "route_unavailable",
    "schedule_correction",
    "unmatched_location_refusal",
}
_SCENARIOS = {
    "complete_fixed_rate",
    "clarified_destination",
    "missing_schedule_inputs",
    "income_clarification",
    "route_unavailable",
    "annual_day_estimation",
    "partial_historical_coverage",
    "hourly_income_clarification",
    "invalid_schedule_correction",
    "unmatched_location_refusal",
}
_CASE_KEYS = {
    "id",
    "suite",
    "windows",
    "weekdays",
    "prompt",
    "conversation",
    "follow_up",
    "expected_call",
    "expected_calls",
    "expected_clarification",
    "expected_missing_fields",
    "expected_estimated_annual_commute_days",
    "forbidden_inferred_income_usd",
    "expected_route_status",
    "annual_behavior",
    "capability",
    "scenario_family",
    "outcome",
    "risk_tags",
    "evidence_type",
    "provenance",
    "fixture_id",
    "expected_assertion",
}
_LEGACY_KEYS = {
    "id",
    "suite",
    "windows",
    "weekdays",
    "prompt",
    "conversation",
    "follow_up",
    "expected_call",
    "expected_calls",
    "expected_clarification",
    "expected_reasons",
    "expected_availability",
    "expected_required_i95_directions",
    "allow_pricing_unavailable",
    "allowed_route_statuses",
    "expected_component_count",
    "i66_direction",
}
_MANIFEST_KEYS = {
    "corpus",
    "dataset_version",
    "format_version",
    "legacy_source_sha256",
    "contract_versions",
    "case_shards",
    "fixtures",
    "counts",
    "coverage",
    "payloads",
    "capture_history",
    "dataset_sha256",
}
_FIXTURE_KEYS = {
    "fixture_id",
    "capability",
    "result_kind",
    "request",
    "route",
    "source",
    "payload",
}
_SOURCE_KEYS = {"evidence_type", "captured_at", "tool_contract_version"}
_EXPECTED_CONTRACTS = {
    "get_annual_toll_ballpark": "3.0.0",
    "agent_system_prompt": "2.0.2",
    "system_prompt_renderer": "1.0.0",
}
_RESULT_KIND_OUTCOMES = {
    "success": {
        "success",
        "clarified_success",
        "confirmed_success",
        "corrected_success",
    },
    "partial_success": {"partial_success"},
    "route_unavailable": {"structured_unavailability"},
}
_V1_CASE_CONTRACT = {
    "leesburg-route-28-annual-affordability": {
        "scenario_family": "complete_fixed_rate",
        "outcome": "success",
        "fixture_id": "greenway-success",
        "canonical_sha256": "44619868c94ad51c2fd6adbcfd804c7a58c68c0205c3d66dd4ac0e5a9f4f8390",
    },
    "springfield-franconia-tysons-annual-affordability": {
        "scenario_family": "clarified_destination",
        "outcome": "partial_success",
        "fixture_id": "springfield-tysons-success",
        "canonical_sha256": "1a79d4c396d80f5d6e08a46dc7f918fca526976e9d64ff37a16b58b3727acc4d",
    },
    "leesburg-route-28-schedule-inputs": {
        "scenario_family": "missing_schedule_inputs",
        "outcome": "clarification_without_tool",
        "fixture_id": None,
        "canonical_sha256": "7bd58923411b2fbb9aae560c27d480915e932e17c30811f1c1cfd9fb5cff787d",
    },
    "leesburg-route-28-income-clarification": {
        "scenario_family": "income_clarification",
        "outcome": "clarified_success",
        "fixture_id": "greenway-success",
        "canonical_sha256": "806bd9f80de4ef1a0377b25b8e955c0be4096ff35fc0a22134d03b667d5c61a8",
    },
    "dulles-to-reagan-annual-unavailable": {
        "scenario_family": "route_unavailable",
        "outcome": "structured_unavailability",
        "fixture_id": "dulles-reagan-route-unavailable",
        "canonical_sha256": "7b6ff6be627befc041b893dec73c6aed867ac0cf9d31ee1abd54594fe7514186",
    },
    "leesburg-route-28-annual-day-confirmation": {
        "scenario_family": "annual_day_estimation",
        "outcome": "confirmed_success",
        "fixture_id": "greenway-success",
        "canonical_sha256": "c4d90f4baf84211754b2870c59c673613f56c130647bdb949d53c38f2b3638bf",
    },
    "leesburg-to-washington-annual-partial": {
        "scenario_family": "partial_historical_coverage",
        "outcome": "partial_success",
        "fixture_id": "leesburg-washington-partial-0830",
        "canonical_sha256": "cf904735208b5bb4b71cf209cb9532f49e42a4e5c7fae8e920b225fb4231afc7",
    },
    "greenway-hourly-income-clarification": {
        "scenario_family": "hourly_income_clarification",
        "outcome": "clarified_success",
        "fixture_id": "greenway-success",
        "canonical_sha256": "1dddb18a8a124ae0419a96f2b06e06be86f11e37c77a2ca89335a5b428e1885c",
    },
    "greenway-invalid-schedule-correction": {
        "scenario_family": "invalid_schedule_correction",
        "outcome": "corrected_success",
        "fixture_id": "greenway-success",
        "canonical_sha256": "845e504dfb02ccb3597ce11999fb42926cd48bc07311cc6109fed39a63b5cce5",
    },
    "winchester-unsupported-location-refusal": {
        "scenario_family": "unmatched_location_refusal",
        "outcome": "refusal_without_tool",
        "fixture_id": None,
        "canonical_sha256": "057d656bdb44215945c5d009f6ff78bfe8f5fa41f8a4139679525deea7a55cc6",
    },
}
_V1_LEGACY_CASE_CONTRACT = {
    "reagan-airport-to-westpark": "6bcd21edbea91f25bdf39f1a18abfd8d9d1668eafac0b1e951b2eb96a785e789",
    "pentagon-eads-to-westpark": "b20d8c090035e45f54b8c4be0f700242eb1b38ae15bdb48dd67dd068d1b84e09",
    "springfield-franconia-to-westpark": "eb79de052a3970ba6e85bb72d21eb135399ecff9aa099af529be255ae445649f",
    "dulles-airport-to-backlick-tp1sb-fallback": "ee027fda8bb87f5c904571e5d34b5af59bc27af2286693b8899c6b07d3beabfd",
    "old-keene-mill-to-reagan-i95-unavailable": "e57946b6654c52b0a0a0a615719635ff80fa4edca07bd47d2d7cb87d002599a5",
    "dulles-to-reagan-current-price": "d5de4e9bf606853b224f0da128f1e3fa9420804ae967760715e8c413417e17e5",
    "i66-west-to-route-7-current-price": "967851429db599c9c8a12b9e91b2124cd8d1f38deef613cc1df3d163202d90e2",
    "route-7-to-i495-south-current-price": "1bbfb2afdd1918369bf7c9a709a4958b07f36f505cc5effa275c591be80a295e",
    "leesburg-to-washington-i395-current-price": "6cb3e447bae2d43f6d9f8a52fb3d6dfd7ec8fe396b1b52f69bb432d37f7ff42f",
}
_V1_FIXTURE_CONTRACT = {
    "greenway-success": {
        "evidence_type": "retained_production_capture",
        "captured_at": "2026-08-22T16:40:59.392081-04:00",
        "tool_contract_version": "3.0.0",
        "raw_sha256": "c4cea708c6cb38fb4d6ad58011db9ddf413056e37c88216187f6bbe4d638c5cd",
    },
    "springfield-tysons-success": {
        "evidence_type": "retained_production_capture",
        "captured_at": "2026-08-22T16:41:08.049956-04:00",
        "tool_contract_version": "3.0.0",
        "raw_sha256": "5269b117cf8653dd96083a6847549ee1d8716b7dce79311bc6334a2490c2ba0f",
    },
    "dulles-reagan-route-unavailable": {
        "evidence_type": "retained_production_capture",
        "captured_at": "2026-08-22T16:41:39-04:00",
        "tool_contract_version": "3.0.0",
        "raw_sha256": "8c5133b44720a04dc856efcd8a50b21bb07b62b4d4b26fa137b3a71244d54414",
    },
    "leesburg-washington-partial-0830": {
        "evidence_type": "live_read_only_capture",
        "captured_at": "2026-09-04T10:55:38.987941-04:00",
        "tool_contract_version": "3.0.0",
        "raw_sha256": "fd3dd8b4d865a367339b4a7373034eb9a812bb06a51087432d453810c1172753",
    },
}
_V1_CAPTURE_PROVENANCE_SHA256 = (
    "6b6ab80903433324cdfb11b670cf20cb826c0f472700e08d6df2d5741578960e"
)


class CorpusError(ValueError):
    """Raised when a corpus release is not internally consistent."""


@dataclass(frozen=True)
class Corpus:
    manifest: dict[str, Any]
    legacy_rows: list[dict[str, Any]]
    annual_rows: list[dict[str, Any]]
    fixtures: dict[str, dict[str, Any]]

    @property
    def rows(self) -> list[dict[str, Any]]:
        return [*self.legacy_rows, *self.annual_rows]


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CorpusError(f"invalid JSON: {path}: {error}") from error


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise CorpusError(f"cannot read JSONL: {path}: {error}") from error
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise CorpusError(f"blank JSONL line {path}:{line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise CorpusError(f"invalid JSONL {path}:{line_number}: {error}") from error
        if not isinstance(value, dict):
            raise CorpusError(f"JSONL row is not an object: {path}:{line_number}")
        rows.append(value)
    if not rows:
        raise CorpusError(f"empty JSONL: {path}")
    return rows


def _semver(value: Any, field: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        raise CorpusError(f"{field} is not strict SemVer: {value!r}")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_capture_timestamp(value: Any, label: str) -> str:
    """Normalize aware capture provenance to UTC ISO timestamps at second precision."""
    if not isinstance(value, str):
        raise CorpusError(f"{label} capture timestamp is not text")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise CorpusError(f"{label} capture timestamp is not ISO-8601") from error
    if timestamp.tzinfo is None:
        raise CorpusError(f"{label} capture timestamp has no timezone")
    return timestamp.astimezone(UTC).replace(microsecond=0).isoformat()


def _path(root: Path, value: Any) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
    ):
        raise CorpusError(f"payload path is not relative POSIX: {value!r}")
    candidate = (root / value).resolve()
    if candidate != root.resolve() and root.resolve() not in candidate.parents:
        raise CorpusError(f"payload path escapes corpus: {value!r}")
    if Path(value).as_posix() != value:
        raise CorpusError(f"payload path is not normalized POSIX: {value!r}")
    return candidate


def _request(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CorpusError(f"{label} request is not an object")
    try:
        _BallparkRequest.model_validate(value)
    except Exception as error:
        raise CorpusError(
            f"{label} request violates annual input contract: {error}"
        ) from error
    return value


def _assert_route(fixture: dict[str, Any], label: str) -> None:
    request = fixture["request"]
    route = fixture["route"]
    if not isinstance(route, dict) or set(route) != {"outbound", "return"}:
        raise CorpusError(f"{label} route metadata is invalid")
    for direction in ("outbound", "return"):
        call = request[direction]
        expected = [call["origin_point_id"], call["destination_point_id"]]
        if route[direction] != expected:
            raise CorpusError(f"{label} route metadata disagrees with request")


def _validate_case(row: dict[str, Any], label: str) -> None:
    unknown = set(row) - _CASE_KEYS
    if unknown:
        raise CorpusError(f"{label} has unknown keys: {sorted(unknown)}")
    if not isinstance(row.get("id"), str) or not _ID.fullmatch(row["id"]):
        raise CorpusError(f"{label} has unstable case ID")
    if "job-offer" in row["id"] or "job-offer" in str(row.get("prompt", "")):
        raise CorpusError(f"{label} retains non-generic job-offer naming")
    if (
        row.get("suite") != "annual"
        or not isinstance(row.get("prompt"), str)
        or not row["prompt"].strip()
    ):
        raise CorpusError(f"{label} is not a valid annual evaluator case")
    if (
        row.get("capability") != "annual_affordability"
        or row.get("scenario_family") not in _SCENARIOS
    ):
        raise CorpusError(f"{label} has invalid generic capability/scenario metadata")
    for field in ("outcome", "evidence_type", "provenance"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise CorpusError(f"{label} is missing generic metadata: {field}")
    if (
        not isinstance(row.get("risk_tags"), list)
        or not row["risk_tags"]
        or not all(isinstance(item, str) and item for item in row["risk_tags"])
    ):
        raise CorpusError(f"{label} has invalid risk tags")
    assertion = row.get("expected_assertion")
    if (
        not isinstance(assertion, str)
        or "Required:" not in assertion
        or "Prohibited:" not in assertion
    ):
        raise CorpusError(
            f"{label} needs a human-readable required/prohibited assertion"
        )
    if "expected_call" in row:
        _request(row["expected_call"], label)
    elif row.get("annual_behavior") not in {
        "missing_inputs",
        "unmatched_location_refusal",
    }:
        raise CorpusError(f"{label} is missing its expected annual call")
    behavior = row.get("annual_behavior")
    if behavior is not None and behavior not in _BEHAVIORS:
        raise CorpusError(f"{label} has an unknown annual behavior")
    if "conversation" in row and (
        not isinstance(row["conversation"], list)
        or not row["conversation"]
        or not all(isinstance(item, str) and item for item in row["conversation"])
    ):
        raise CorpusError(f"{label} has invalid conversation turns")
    if "expected_clarification" in row and (
        not isinstance(row["expected_clarification"], list)
        or not row["expected_clarification"]
    ):
        raise CorpusError(f"{label} has invalid clarification metadata")
    if behavior == "income_clarification" and (
        not isinstance(row.get("forbidden_inferred_income_usd"), str)
        or "conversation" not in row
        or len(row["conversation"]) != 2
    ):
        raise CorpusError(f"{label} income clarification contract is incomplete")
    if behavior == "schedule_correction":
        call = row.get("expected_call", {})
        if (
            not isinstance(row.get("conversation"), list)
            or len(row["conversation"]) != 2
        ):
            raise CorpusError(f"{label} schedule correction needs two turns")
        if (
            call.get("outbound", {}).get("departure_time") != "08:00:00"
            or call.get("return", {}).get("departure_time") != "17:30:00"
            or call.get("planned_annual_commute_days") != 240
        ):
            raise CorpusError(
                f"{label} schedule correction does not use corrected values"
            )
        if (
            "300" not in row["conversation"][0]
            or not any(value in row["conversation"][0] for value in ("17:30", "5:30"))
            or "08:00" not in row["conversation"][1]
        ):
            raise CorpusError(
                f"{label} schedule correction lost its invalid-input regression"
            )
    if behavior == "unmatched_location_refusal" and (
        "expected_call" in row
        or "fixture_id" in row
        or "winchester" not in row["prompt"].casefold()
    ):
        raise CorpusError(f"{label} refusal must have no call or fixture")


def _validate_legacy(row: dict[str, Any], label: str) -> None:
    if set(row) - _LEGACY_KEYS:
        raise CorpusError(f"{label} has unknown legacy keys")
    if not isinstance(row.get("id"), str) or not _ID.fullmatch(row["id"]):
        raise CorpusError(f"{label} has an unstable case ID")
    if (
        row.get("suite") == "annual"
        or not isinstance(row.get("prompt"), str)
        or not row["prompt"].strip()
    ):
        raise CorpusError(f"{label} is not a valid current-price case")
    if "expected_call" not in row and "expected_calls" not in row:
        raise CorpusError(f"{label} is missing its evaluator call contract")


def _validate_v1_legacy_contract(legacy: list[dict[str, Any]]) -> None:
    if {row.get("id") for row in legacy} != set(_V1_LEGACY_CASE_CONTRACT):
        raise CorpusError("legacy rows do not match the trusted v1 case contract")
    for row in legacy:
        if _sha256_bytes(_canonical(row)) != _V1_LEGACY_CASE_CONTRACT[row["id"]]:
            raise CorpusError(
                f"legacy case {row['id']} disagrees with the trusted v1 behavior contract"
            )


def _validate_v1_case_contract(
    annual: list[dict[str, Any]],
    fixtures: dict[str, dict[str, Any]],
    fixture_paths: dict[str, Path],
) -> None:
    if {row.get("id") for row in annual} != set(_V1_CASE_CONTRACT):
        raise CorpusError("annual rows do not match the trusted v1 case contract")
    for row in annual:
        expected = _V1_CASE_CONTRACT[row["id"]]
        if {
            "scenario_family": row.get("scenario_family"),
            "outcome": row.get("outcome"),
            "fixture_id": row.get("fixture_id"),
        } != {
            key: expected[key] for key in ("scenario_family", "outcome", "fixture_id")
        }:
            raise CorpusError(
                f"case {row['id']} disagrees with the trusted v1 contract"
            )
        if _sha256_bytes(_canonical(row)) != expected["canonical_sha256"]:
            raise CorpusError(
                f"case {row['id']} disagrees with the trusted v1 behavior contract"
            )
    expected_fixture_ids = {
        value["fixture_id"]
        for value in _V1_CASE_CONTRACT.values()
        if value["fixture_id"] is not None
    }
    if set(fixtures) != expected_fixture_ids or set(fixtures) != set(
        _V1_FIXTURE_CONTRACT
    ):
        raise CorpusError("fixtures do not match the trusted v1 case contract")
    for fixture_id, expected_source in _V1_FIXTURE_CONTRACT.items():
        if fixtures[fixture_id].get("source") != {
            key: expected_source[key] for key in _SOURCE_KEYS
        }:
            raise CorpusError(
                f"fixture {fixture_id} disagrees with the trusted v1 source contract"
            )
        if (
            _sha256_bytes(fixture_paths[fixture_id].read_bytes())
            != expected_source["raw_sha256"]
        ):
            raise CorpusError(
                f"fixture {fixture_id} disagrees with the trusted v1 file contract"
            )


def _validate_pinned_provenance(value: Any, *, initial_release: bool) -> None:
    if not isinstance(value, list) or not value:
        raise CorpusError("pinned provenance is malformed")
    required = {
        "capture_id",
        "captured_at",
        "tool_contract_version",
        "result",
        "corpus_use",
    }
    for item in value:
        if not isinstance(item, dict) or set(item) != required:
            raise CorpusError("pinned provenance entry is malformed")
        if (
            not isinstance(item["capture_id"], str)
            or not _ID.fullmatch(item["capture_id"])
            or not all(
                isinstance(item[key], str) and item[key].strip()
                for key in required - {"capture_id"}
            )
            or item["tool_contract_version"]
            != _EXPECTED_CONTRACTS["get_annual_toll_ballpark"]
        ):
            raise CorpusError("pinned provenance entry is malformed")
    if initial_release and (
        _sha256_bytes(_canonical({"capture_history": value}))
        != _V1_CAPTURE_PROVENANCE_SHA256
    ):
        raise CorpusError("pinned provenance disagrees with the trusted v1 contract")


def _validate_fixture(fixture: dict[str, Any], path: Path, label: str) -> None:
    if set(fixture) != _FIXTURE_KEYS:
        raise CorpusError(f"{label} has unknown or missing fixture keys")
    fixture_id = fixture.get("fixture_id")
    if not isinstance(fixture_id, str) or not _ID.fullmatch(fixture_id):
        raise CorpusError(f"{label} has an invalid fixture ID")
    if fixture.get("capability") != "annual_affordability" or fixture.get(
        "result_kind"
    ) not in {"success", "partial_success", "route_unavailable"}:
        raise CorpusError(f"{label} has invalid fixture type")
    _request(fixture.get("request"), label)
    _assert_route(fixture, label)
    source = fixture.get("source")
    if (
        not isinstance(source, dict)
        or set(source) != _SOURCE_KEYS
        or source.get("tool_contract_version")
        != _EXPECTED_CONTRACTS["get_annual_toll_ballpark"]
        or source.get("evidence_type")
        not in {"retained_production_capture", "live_read_only_capture"}
    ):
        raise CorpusError(f"{label} has invalid source/tool contract metadata")
    if not isinstance(source.get("captured_at"), str) or not isinstance(
        source.get("evidence_type"), str
    ):
        raise CorpusError(f"{label} source metadata is incomplete")
    payload = fixture.get("payload")
    if not isinstance(payload, dict):
        raise CorpusError(f"{label} payload is not an object")
    try:
        typed = _OUTPUT_ADAPTER.validate_json(json.dumps(payload, ensure_ascii=False))
    except Exception as error:
        raise CorpusError(
            f"{label} payload fails annual output adapter: {error}"
        ) from error
    result_kind = fixture["result_kind"]
    sample_status = getattr(typed, "sample_status", None)
    scenarios = getattr(typed, "scenarios", None)
    typed_reason = getattr(typed, "reason", None)
    if result_kind == "success" and (
        sample_status != "complete" or scenarios is None or typed_reason is not None
    ):
        raise CorpusError(f"{label} result kind disagrees with typed payload")
    if result_kind == "partial_success" and (
        sample_status != "partial" or scenarios is None or typed_reason is not None
    ):
        raise CorpusError(f"{label} result kind disagrees with typed payload")
    if result_kind == "route_unavailable" and typed_reason != "route_unavailable":
        raise CorpusError(f"{label} result kind disagrees with typed payload")
    request = fixture["request"]
    if fixture["result_kind"] in {"success", "partial_success"} and (
        payload.get("weekdays") != request["weekdays"]
        or payload.get("planned_annual_commute_days")
        != request["planned_annual_commute_days"]
        or payload.get("income", {}).get("gross_annual_usd")
        != request["gross_annual_income_usd"]
        or payload.get("evaluated_at") != source["captured_at"]
    ):
        raise CorpusError(f"{label} payload request/provenance disagrees")
    if fixture["result_kind"] == "route_unavailable":
        if (
            payload.get("error") != "ballpark_unavailable"
            or payload.get("reason") != "route_unavailable"
        ):
            raise CorpusError(f"{label} route-unavailable result is not typed")
        for direction in ("outbound", "return"):
            status = payload.get(direction)
            if not isinstance(status, dict) or any(
                status.get(key) != request[direction][key]
                for key in ("origin_point_id", "destination_point_id")
            ):
                raise CorpusError(f"{label} unavailable payload route disagrees")
            expected_status = (
                "valid" if direction == "outbound" else "no_supported_route"
            )
            expected_reason = None if direction == "outbound" else "no_supported_route"
            reason = status.get("reason")
            actual_reason = (
                None
                if reason is None
                else reason.get("code")
                if isinstance(reason, dict)
                else "<invalid>"
            )
            if status.get("status") != expected_status or (
                actual_reason != expected_reason
            ):
                raise CorpusError(f"{label} unavailable status/reason disagrees")
    coverage = payload.get("coverage")
    if fixture["fixture_id"] == "leesburg-washington-partial-0830" and (
        not isinstance(coverage, dict)
        or payload.get("sample_status") != "partial"
        or coverage.get("eligible_date_count") != 60
        or coverage.get("complete_pair_count") != 51
        or coverage.get("coverage_percent") != "85.0"
    ):
        raise CorpusError(f"{label} is not the accepted 51/60 partial capture")
    dumped = json.dumps(fixture, ensure_ascii=False)
    if (
        re.search(
            r"https?://|(?:password|secret|token|credential|user_text|endpoint)\s*[:=]",
            dumped,
            re.IGNORECASE,
        )
        or "arn:aws:" in dumped
    ):
        raise CorpusError(f"{label} contains prohibited secret, endpoint, or user data")
    if path.name.startswith("synthetic") or "diagnostic" in fixture_id:
        raise CorpusError(f"{label} is not an accepted authentic fixture")


def _legacy_rows(manifest_path: Path) -> list[dict[str, Any]]:
    return _jsonl(_legacy_source_path(manifest_path))


def _legacy_source_path(manifest_path: Path) -> Path:
    """Return the sibling legacy source whose bytes are covered by the manifest."""
    return (manifest_path.parent.parent / "test-cases.jsonl").resolve()


def _base_manifest(
    manifest_path: Path, base_ref: str | None
) -> tuple[dict[str, Any] | None, dict[str, bytes]]:
    if not base_ref or base_ref == "0" * 40:
        return None, {}
    if _REPO_ROOT not in manifest_path.resolve().parents:
        raise CorpusError(
            "base ref comparison requires a manifest inside the repository"
        )
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{base_ref}^{{commit}}"],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if resolved.returncode:
        raise CorpusError(f"base ref cannot be resolved: {base_ref}")
    base_ref = resolved.stdout.decode().strip()
    relative = manifest_path.resolve().relative_to(_REPO_ROOT).as_posix()
    shown = subprocess.run(
        ["git", "show", f"{base_ref}:{relative}"],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if shown.returncode:
        return None, {}
    try:
        old = json.loads(shown.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorpusError(f"base manifest is invalid: {error}") from error
    old_payloads: dict[str, bytes] = {}
    for item in old.get("payloads", []):
        path = item.get("path") if isinstance(item, dict) else None
        if isinstance(path, str):
            payload = subprocess.run(
                [
                    "git",
                    "show",
                    f"{base_ref}:{manifest_path.parent.relative_to(_REPO_ROOT).as_posix()}/{path}",
                ],
                cwd=_REPO_ROOT,
                capture_output=True,
                check=False,
            )
            if payload.returncode == 0:
                old_payloads[path] = payload.stdout
    return old, old_payloads


def validate(
    manifest_path: Path = _DEFAULT_MANIFEST, base_ref: str | None = None
) -> Corpus:
    manifest_path = manifest_path.resolve()
    manifest = _json(manifest_path)
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise CorpusError("manifest has unknown or missing top-level keys")
    if manifest.get("corpus") != "annual-affordability":
        raise CorpusError("manifest corpus name is not generic annual-affordability")
    dataset_version = _semver(manifest.get("dataset_version"), "dataset_version")
    if dataset_version < (1, 0, 0):
        raise CorpusError("dataset_version must be at least 1.0.0")
    initial_release = dataset_version == (1, 0, 0)
    if manifest.get("format_version") != "1.0.0":
        _semver(manifest.get("format_version"), "format_version")
        raise CorpusError("format_version must be 1.0.0")
    legacy_source_hash = manifest.get("legacy_source_sha256")
    if not isinstance(legacy_source_hash, str) or not _SHA256.fullmatch(
        legacy_source_hash
    ):
        raise CorpusError("legacy source hash is malformed")
    legacy_source = _legacy_source_path(manifest_path)
    try:
        actual_legacy_source_hash = _sha256_bytes(legacy_source.read_bytes())
    except OSError as error:
        raise CorpusError(f"legacy source is unavailable: {legacy_source}") from error
    if legacy_source_hash != actual_legacy_source_hash:
        raise CorpusError("legacy source hash mismatch")
    if manifest.get("contract_versions") != _EXPECTED_CONTRACTS:
        raise CorpusError("contract versions do not match current contracts")
    _validate_pinned_provenance(
        manifest.get("capture_history"), initial_release=initial_release
    )
    shards = manifest.get("case_shards")
    if not isinstance(shards, list) or not shards:
        raise CorpusError("manifest must declare annual case shards")
    if initial_release and shards != [
        {"path": "cases/annual-affordability.jsonl", "count": 10}
    ]:
        raise CorpusError("annual shard declaration is incorrect")
    annual: list[dict[str, Any]] = []
    shard_paths: set[Path] = set()
    for shard in shards:
        if not isinstance(shard, dict) or set(shard) != {"path", "count"}:
            raise CorpusError("annual shard declaration is malformed")
        shard_path = _path(manifest_path.parent, shard["path"])
        if shard_path in shard_paths or shard_path.suffix != ".jsonl":
            raise CorpusError("annual shard paths must be unique JSONL files")
        shard_paths.add(shard_path)
        rows = _jsonl(shard_path)
        if type(shard["count"]) is not int or shard["count"] != len(rows):
            raise CorpusError("annual shard count does not reconcile")
        annual.extend(rows)
    legacy = _legacy_rows(manifest_path)
    if len(legacy) != 9 or any(row.get("suite") == "annual" for row in legacy):
        raise CorpusError("legacy file must contain exactly nine current cases")
    for index, row in enumerate(legacy):
        _validate_legacy(row, f"legacy row {index + 1}")
    if initial_release:
        _validate_v1_legacy_contract(legacy)
    for index, row in enumerate(annual):
        _validate_case(row, f"annual row {index + 1}")
    ids = [row.get("id") for row in [*legacy, *annual]]
    if any(not isinstance(case_id, str) for case_id in ids) or len(ids) != len(
        set(ids)
    ):
        raise CorpusError("case IDs are not unique across legacy and golden rows")
    contents = [
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for row in annual
    ]
    if len(contents) != len(set(contents)):
        raise CorpusError("duplicate annual case content")
    legacy_content = {
        json.dumps(
            {
                key: row[key]
                for key in row
                if key
                not in {
                    "id",
                    "capability",
                    "scenario_family",
                    "outcome",
                    "risk_tags",
                    "evidence_type",
                    "provenance",
                    "fixture_id",
                    "expected_assertion",
                }
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for row in legacy
    }
    if any(
        json.dumps(
            {
                key: row[key]
                for key in row
                if key
                not in {
                    "id",
                    "capability",
                    "scenario_family",
                    "outcome",
                    "risk_tags",
                    "evidence_type",
                    "provenance",
                    "fixture_id",
                    "expected_assertion",
                }
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        in legacy_content
        for row in annual
    ):
        raise CorpusError("annual case content is duplicated in the legacy file")
    fixtures_declared = manifest.get("fixtures")
    if not isinstance(fixtures_declared, list) or not fixtures_declared:
        raise CorpusError("manifest must declare fixtures")
    fixtures: dict[str, dict[str, Any]] = {}
    fixture_paths: dict[str, Path] = {}
    for item in fixtures_declared:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "path",
            "result_kind",
            "case_ids",
        }:
            raise CorpusError("fixture declaration is malformed")
        fixture_id = item.get("id")
        if not isinstance(fixture_id, str) or fixture_id in fixtures:
            raise CorpusError("fixture IDs are not unique")
        fixture_path = _path(manifest_path.parent, item.get("path"))
        fixture = _json(fixture_path)
        if (
            not isinstance(fixture, dict)
            or fixture.get("fixture_id") != fixture_id
            or item.get("result_kind") != fixture.get("result_kind")
        ):
            raise CorpusError(f"fixture declaration disagrees with {fixture_path}")
        _validate_fixture(fixture, fixture_path, f"fixture {fixture_id}")
        if not isinstance(item.get("case_ids"), list) or not all(
            isinstance(case_id, str) for case_id in item["case_ids"]
        ):
            raise CorpusError(f"fixture {fixture_id} has invalid case references")
        fixtures[fixture_id] = fixture
        fixture_paths[fixture_id] = fixture_path
    if initial_release:
        _validate_v1_case_contract(annual, fixtures, fixture_paths)
    annual_by_id = {row["id"]: row for row in annual}
    for row in annual:
        fixture_id = row.get("fixture_id")
        if fixture_id is not None and fixture_id not in fixtures:
            raise CorpusError(f"case {row['id']} references an undeclared fixture")
        if (
            fixture_id is not None
            and row.get("expected_call") != fixtures[fixture_id]["request"]
        ):
            raise CorpusError(f"case {row['id']} route disagrees with its fixture")
        if fixture_id is not None:
            fixture = fixtures[fixture_id]
            result_kind = fixture["result_kind"]
            if row.get("outcome") not in _RESULT_KIND_OUTCOMES[result_kind]:
                raise CorpusError(
                    f"case {row['id']} outcome disagrees with its fixture"
                )
            source = fixture["source"]
            if row.get("evidence_type") != source["evidence_type"]:
                raise CorpusError(
                    f"case {row['id']} evidence type disagrees with its fixture"
                )
            if _normalized_capture_timestamp(
                row.get("provenance"), f"case {row['id']}"
            ) != _normalized_capture_timestamp(
                source["captured_at"], f"fixture {fixture_id}"
            ):
                raise CorpusError(
                    f"case {row['id']} provenance disagrees with its fixture"
                )
        if (
            row.get("annual_behavior")
            not in {"missing_inputs", "unmatched_location_refusal"}
            and fixture_id is None
        ):
            raise CorpusError(f"case {row['id']} needs a fixture reference")
    for item in fixtures_declared:
        if not item["case_ids"]:
            raise CorpusError(f"fixture {item['id']} must reference a case")
        refs = sorted(
            case_id
            for case_id, row in annual_by_id.items()
            if row.get("fixture_id") == item["id"]
        )
        if refs != sorted(item["case_ids"]):
            raise CorpusError(f"fixture {item['id']} case references do not reconcile")
    counts = {
        "legacy_current": len(legacy),
        "golden_annual": len(annual),
        "runtime_cases": len(legacy) + len(annual),
        "fixtures": len(fixtures),
    }
    if manifest.get("counts") != counts:
        raise CorpusError("manifest counts do not reconcile")
    scenario_counts: dict[str, int] = {}
    for row in annual:
        scenario_counts[row["scenario_family"]] = (
            scenario_counts.get(row["scenario_family"], 0) + 1
        )
    expected_coverage = {
        **counts,
        "annual_scenario_families": scenario_counts,
    }
    if manifest.get("coverage") != expected_coverage:
        raise CorpusError("coverage metadata does not reconcile")
    payload_items = manifest.get("payloads")
    expected_payload_paths = sorted(
        [
            *(shard["path"] for shard in shards),
            *(item["path"] for item in fixtures_declared),
        ]
    )
    if (
        not isinstance(payload_items, list)
        or [item.get("path") for item in payload_items if isinstance(item, dict)]
        != expected_payload_paths
    ):
        raise CorpusError("payload paths are not sorted or do not enumerate the corpus")
    for item in payload_items:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or not isinstance(item["sha256"], str)
            or not _SHA256.fullmatch(item["sha256"])
        ):
            raise CorpusError("payload declaration is malformed")
        payload_path = _path(manifest_path.parent, item["path"])
        actual = _sha256_bytes(payload_path.read_bytes())
        if item["sha256"] != actual:
            raise CorpusError(f"payload hash mismatch: {item['path']}")
    without_hash = {
        key: value for key, value in manifest.items() if key != "dataset_sha256"
    }
    if manifest["dataset_sha256"] != _sha256_bytes(_canonical(without_hash)):
        raise CorpusError("dataset_sha256 mismatch")
    old, old_payloads = _base_manifest(manifest_path, base_ref)
    if old is None:
        if base_ref and base_ref != "0" * 40 and not initial_release:
            raise CorpusError("initial corpus must use dataset_version 1.0.0")
    else:
        old_version = _semver(old.get("dataset_version"), "base dataset_version")
        current_content = _canonical(without_hash)
        old_without_hash = {
            key: value for key, value in old.items() if key != "dataset_sha256"
        }
        changed = current_content != _canonical(old_without_hash)
        changed = changed or any(
            old_payloads.get(item["path"])
            != _path(manifest_path.parent, item["path"]).read_bytes()
            for item in payload_items
        )
        if changed and dataset_version <= old_version:
            raise CorpusError("edited corpus requires an advanced dataset_version")
        if not changed and dataset_version != old_version:
            raise CorpusError(
                "unchanged corpus has a historically mismatched dataset_version"
            )
    return Corpus(manifest, legacy, annual, fixtures)


def load_rows(manifest_path: Path = _DEFAULT_MANIFEST) -> list[dict[str, Any]]:
    return validate(manifest_path).rows


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def render(
    manifest_path: Path = _DEFAULT_MANIFEST,
    output_path: Path = Path(".graph/golden-review.html"),
) -> Path:
    corpus = validate(manifest_path)
    annual_count = len(corpus.annual_rows)
    legacy_count = len(corpus.legacy_rows)
    fixture_count = len(corpus.fixtures)
    runtime_count = len(corpus.rows)
    fixture_by_case = {}
    for declaration in corpus.manifest["fixtures"]:
        for case_id in declaration["case_ids"]:
            fixture_by_case[case_id] = corpus.fixtures[declaration["id"]]
    cards: list[str] = []
    for row in corpus.annual_rows:
        fixture = fixture_by_case.get(row["id"])
        conversation = list(row.get("conversation", [row["prompt"]]))
        if row.get("follow_up") and row["follow_up"] not in conversation:
            conversation.append(row["follow_up"])
        conversation_html = "".join(f"<li>{_esc(turn)}</li>" for turn in conversation)
        expected_behavior = (
            "No tool call or fixture output is allowed. Apply the deterministic "
            "no-tool contract and the required/prohibited evaluator assertion."
            if fixture is None
            else "The evaluator requires the declared typed annual tool call and "
            "the fixture's result kind; amounts and status must stay bound to the "
            "recorded payload."
        )
        fixture_text = (
            "No fixture: deterministic no-tool/evaluator contract only; no model "
            "output or fabricated result is shown."
            if fixture is None
            else "Recorded fixture evidence only; byte-pinned historical evidence; "
            "not a model run.\n"
            + json.dumps(
                {
                    "fixture_id": fixture["fixture_id"],
                    "result_kind": fixture["result_kind"],
                    "request": fixture["request"],
                    "source": fixture["source"],
                    "payload": fixture["payload"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        cards.append(
            f'<article class="case-card" data-case-id="{_esc(row["id"])}" data-scenario="{_esc(row["scenario_family"])}" data-outcome="{_esc(row["outcome"])}">'
            f'<h2>{_esc(row["id"])}</h2><p class="tags">{_esc(row["scenario_family"])} · {_esc(row["outcome"])}</p>'
            f"<h3>Prompt and conversation</h3><p>{_esc(row['prompt'])}</p><ol>{conversation_html}</ol>"
            f"<h3>Expected required/prohibited behavior</h3><p>{_esc(row['expected_assertion'])}</p>"
            f"<h3>Deterministic evaluator behavior</h3><p>{_esc(expected_behavior)}</p>"
            f"<h3>Recorded fixture details</h3><pre>{_esc(fixture_text)}</pre></article>"
        )
    capture_html = "".join(
        f"<li><strong>{_esc(item.get('capture_id'))}</strong>: {_esc(item.get('result'))}; "
        f"{_esc(item.get('corpus_use'))}. This is pinned provenance context only, "
        "not a model run or fixture unless the case card explicitly identifies it "
        "as recorded fixture evidence.</li>"
        for item in corpus.manifest["capture_history"]
    )
    file_hashes = "".join(
        f"<li><code>{_esc(item['path'])}</code>: <code>{_esc(item['sha256'])}</code></li>"
        for item in corpus.manifest["payloads"]
    )
    html_text = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Annual affordability golden review</title>
<style>body{{font:16px system-ui,sans-serif;line-height:1.5;margin:0;background:#f4f7fb;color:#18202a}}main{{max-width:1100px;margin:auto;padding:2rem}}.notice{{padding:1rem;border-left:6px solid #a33;background:#fff3cd}}.controls{{display:flex;gap:1rem;flex-wrap:wrap;margin:1.5rem 0}}label{{font-weight:700}}input,select{{font:inherit;padding:.45rem;border:1px solid #667;border-radius:.3rem}}.case-card{{background:white;border:1px solid #ccd6e0;border-radius:.5rem;padding:1rem;margin:1rem 0;box-shadow:0 2px 6px #0001}}h2{{margin:.1rem 0;font-size:1.2rem}}h3{{font-size:1rem;margin-bottom:.2rem}}.tags{{color:#52677c}}pre{{white-space:pre-wrap;overflow:auto;background:#eef2f6;padding:.75rem;border-radius:.3rem}}table{{border-collapse:collapse;background:#fff}}th,td{{border:1px solid #bbc7d3;padding:.5rem;text-align:left}}.sr-only{{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}}</style></head>
<body><main><h1>Annual affordability golden review</h1><p class="notice" role="alert"><strong>Pending human approval:</strong> these are recorded fixture regression artifacts, not authenticated release proof. No live model preview was run for this fixture-only review. Candidate/pass^3 execution is deferred to #362/#363; this page is not pass^3 evidence and is not unbiased evidence.</p>
<p>Dataset {_esc(corpus.manifest["dataset_version"])} · {annual_count} annual cases · {fixture_count} sanitized typed fixtures · {runtime_count} runtime cases including {legacy_count} legacy current-price rows.</p>
<p><strong>Boundary:</strong> the pre-existing live evaluator and Batch utility are separate manual workflows. Golden validation, rendering, and CI never invoke them; their historical reports are not approval evidence for this corpus.</p>
<p>Structured expectations and fixture integrity are authoritative. Prose graders are bounded regression heuristics, not proof of natural-language correctness; broader grading belongs to #360.</p>
<section aria-labelledby="controls-title"><h2 id="controls-title">Search and filters</h2><div class="controls"><label for="search">Search cases</label><input id="search" type="search" placeholder="case, prompt, assertion" autocomplete="off"><label for="scenario">Scenario</label><select id="scenario"><option value="">All scenarios</option>{"".join(f'<option value="{_esc(value)}">{_esc(value)}</option>' for value in sorted({row["scenario_family"] for row in corpus.annual_rows}))}</select><label for="outcome">Outcome</label><select id="outcome"><option value="">All outcomes</option>{"".join(f'<option value="{_esc(value)}">{_esc(value)}</option>' for value in sorted({row["outcome"] for row in corpus.annual_rows}))}</select></div><p id="case-count" aria-live="polite">Showing {annual_count} of {annual_count} cases</p></section>
<section aria-labelledby="coverage-title"><h2 id="coverage-title">Coverage matrix</h2><table><caption class="sr-only">Annual affordability corpus coverage</caption><thead><tr><th scope="col">Metric</th><th scope="col">Count</th></tr></thead><tbody><tr><th scope="row">Legacy current-price</th><td>{legacy_count}</td></tr><tr><th scope="row">Golden annual-affordability</th><td>{annual_count}</td></tr><tr><th scope="row">Runtime total</th><td>{runtime_count}</td></tr><tr><th scope="row">Typed fixtures</th><td>{fixture_count}</td></tr></tbody></table></section>
<section aria-labelledby="integrity-title"><h2 id="integrity-title">Corpus integrity</h2><p>Canonical dataset SHA-256: <code>{_esc(corpus.manifest["dataset_sha256"])}</code></p><ul>{file_hashes}</ul></section>
<section aria-labelledby="capture-title"><h2 id="capture-title">Pinned capture provenance context</h2><ul>{capture_html}</ul></section><section aria-labelledby="cases-title"><h2 id="cases-title">Case cards</h2>{"".join(cards)}</section></main>
<script>const cards=[...document.querySelectorAll('.case-card')],search=document.querySelector('#search'),scenario=document.querySelector('#scenario'),outcome=document.querySelector('#outcome'),count=document.querySelector('#case-count');function filter(){{const q=search.value.toLowerCase(),s=scenario.value,o=outcome.value;let n=0;for(const card of cards){{const visible=(!q||card.textContent.toLowerCase().includes(q))&&(!s||card.dataset.scenario===s)&&(!o||card.dataset.outcome===o);card.hidden=!visible;if(visible)n++}}count.textContent=`Showing ${{n}} of ${{cards.length}} cases`}}for(const control of [search,scenario,outcome])control.addEventListener('input',filter);for(const control of [scenario,outcome])control.addEventListener('change',filter);</script></body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or render the offline fixture-only golden corpus; "
            "never invokes the live evaluator or Batch workflow."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    validate_parser.add_argument("--base-ref")
    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    render_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate":
        corpus = validate(args.manifest, args.base_ref)
        print(
            f"validated {len(corpus.legacy_rows)} legacy + {len(corpus.annual_rows)} golden = {len(corpus.rows)} unique cases; {len(corpus.fixtures)} fixtures"
        )
    elif args.command == "render":
        print(render(args.manifest, args.output))


if __name__ == "__main__":
    main()
