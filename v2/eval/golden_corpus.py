# pyright: basic
# ruff: noqa: ANN401
"""Offline annual-affordability corpus validation and review rendering."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import subprocess
import sys
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

_V2_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _V2_ROOT.parent
sys.path.insert(0, str(_V2_ROOT))
from agent_tools.current_price_domain import (  # noqa: E402, I001
    _OperationError as _CurrentOperationError,
    _OUTPUT_ADAPTER as _CURRENT_OUTPUT_ADAPTER,
    _CurrentPriceResponse,
    _PricingRequest,
)
from agent_tools.get_annual_toll_ballpark import (  # noqa: E402
    _OperationError as _AnnualOperationError,
    _OUTPUT_ADAPTER as _ANNUAL_OUTPUT_ADAPTER,
    _BallparkRequest,
)

_DEFAULT_MANIFEST = Path(__file__).with_name("golden") / "manifest-v2.json"
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
_V2_MANIFEST_KEYS = {
    "corpus",
    "format_version",
    "dataset_version",
    "source_manifests",
    "membership",
    "membership_sha256",
    "case_metadata",
    "case_shards",
    "fixtures",
    "payloads",
    "dataset_sha256",
}
_V2_RELEASE_KEYS = _V2_MANIFEST_KEYS | {
    "allocation",
    "render_date",
    "direction_coverage",
}
_V2_PRIVATE_MANIFEST_KEYS = _V2_MANIFEST_KEYS | {
    "public_dataset_sha256",
    "public_membership_sha256",
}
_V2_ROW_KEYS = {"id", "prompt", "conversation", "script"}
_V2_METADATA_KEYS = {
    "id",
    "suite",
    "primary_category",
    "tags",
    "grouping",
    "provenance",
    "expected_assertion",
}
_V2_RELEASE_METADATA_KEYS = _V2_METADATA_KEYS | {
    "split",
    "scenario_key",
    "template_key",
    "route_key",
}
_V2_METADATA_OPTIONAL_KEYS = {
    "script",
    "expected_call",
    "expected_calls",
    "expected_clarification",
    "expected_missing_fields",
    "expected_route_status",
    "expected_component_count",
    "allow_pricing_unavailable",
    "allowed_route_statuses",
    "response_checks",
}
_V2_REVIEW_STATUSES = {"human_reviewed", "synthetic_unreviewed"}
_V2_CATEGORIES = ("topology", "current", "annual", "multiturn", "fault", "abuse")
_V2_RELEASE_ALLOCATION = {
    "topology": 100,
    "current": 45,
    "annual": 35,
    "multiturn": 30,
    "fault": 20,
    "abuse": 20,
}
_V2_SOURCE_KEYS = {
    "id",
    "source_manifest",
    "source_dataset_sha256",
    "source_case_id",
    "source_case_sha256",
}
_V2_NEW_MEMBER_KEYS = {"id", "shard", "row_sha256"}
_V2_SHARD_KEYS = {"path", "count"}
_V2_FIXTURE_SOURCE_KEYS = {
    "id",
    "tool",
    "tool_contract_version",
    "source_manifest",
    "source_fixture_id",
    "source_fixture_sha256",
}
_V2_FIXTURE_FILE_KEYS = {
    "fixture_id",
    "tool",
    "tool_contract_version",
    "evidence_type",
    "evaluated_at",
    "provenance",
    "source",
    "request",
    "result",
    "error",
}
_V2_PAYLOAD_KEYS = {"path", "sha256"}
_V2_TOOLS = {
    "get_current_toll_price": (
        _PricingRequest,
        _CURRENT_OUTPUT_ADAPTER,
        _CurrentOperationError,
        "current",
    ),
    "get_annual_toll_ballpark": (
        _BallparkRequest,
        _ANNUAL_OUTPUT_ADAPTER,
        _AnnualOperationError,
        "annual",
    ),
}
_V2_TOOL_CONTRACT_VERSIONS = {
    "get_current_toll_price": "1.5.0",
    "get_annual_toll_ballpark": "3.0.0",
}
_V2_ALLOWED_TYPED_URL_HOSTS = {
    "www.dullesgreenway.com",
    "www.dullestollroad.com",
    "www.vdot.virginia.gov",
}
_V2_CAPTURE_EVIDENCE = {
    "historical_replay",
    "retained_production_capture",
    "live_read_only_capture",
}
_V2_SYNTHETIC_EVIDENCE = {
    "synthetic",
    "synthetic_fault",
    "synthetic_adversarial",
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
    ordered_rows: list[dict[str, Any]] | None = None
    manifest_path: Path | None = None
    fixture_paths: dict[str, Path] = dataclass_field(default_factory=dict)
    fixture_raw_bytes: dict[str, bytes] = dataclass_field(default_factory=dict)
    fixture_tools: dict[str, str] = dataclass_field(default_factory=dict)
    fixture_declarations: dict[str, dict[str, Any]] = dataclass_field(
        default_factory=dict
    )

    @property
    def rows(self) -> list[dict[str, Any]]:
        return (
            [*self.legacy_rows, *self.annual_rows]
            if self.ordered_rows is None
            else self.ordered_rows
        )

    def fixture_evidence(self, fixture_id: str) -> dict[str, Any]:
        """Return one validated fixture and its exact source bytes.

        Callers receive a copy of parsed JSON but the original bytes are read
        from the path recorded while validating this corpus.  This keeps source
        references and local fixtures on one trusted lookup boundary.
        """
        if fixture_id not in self.fixtures or fixture_id not in self.fixture_paths:
            raise CorpusError(f"fixture is not resolved: {fixture_id}")
        path = self.fixture_paths[fixture_id]
        try:
            raw = self.fixture_raw_bytes[fixture_id]
            if path.read_bytes() != raw:
                raise CorpusError(
                    f"fixture bytes changed after validation: {fixture_id}"
                )
        except OSError as error:
            raise CorpusError(f"fixture bytes are unavailable: {fixture_id}") from error
        try:
            fixture = _strict_loads(raw.decode("utf-8"), str(path))
        except (UnicodeDecodeError, CorpusError) as error:
            raise CorpusError(f"fixture bytes are invalid: {fixture_id}") from error
        if not isinstance(fixture, dict):
            raise CorpusError(f"fixture bytes are not an object: {fixture_id}")
        outcome = fixture.get("result", fixture.get("payload"))
        error = fixture.get("error")
        if (outcome is None) == (error is None):
            raise CorpusError(f"fixture outcome is ambiguous: {fixture_id}")
        return {
            "id": fixture_id,
            "tool": self.fixture_tools[fixture_id],
            "request": json.loads(json.dumps(fixture["request"])),
            "result_kind": fixture.get("result_kind"),
            "evidence_type": fixture.get("evidence_type")
            or fixture.get("source", {}).get("evidence_type"),
            "evaluated_at": fixture.get("evaluated_at")
            or fixture.get("source", {}).get("captured_at"),
            "provenance": fixture.get("provenance") or fixture.get("source"),
            "result": json.loads(json.dumps(outcome)) if outcome is not None else None,
            "error": json.loads(json.dumps(error)) if error is not None else None,
            "raw_bytes": raw,
            "raw_sha256": _sha256_bytes(raw),
            "path": path,
            "declaration": json.loads(
                json.dumps(self.fixture_declarations[fixture_id])
            ),
        }


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


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CorpusError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> Any:
    raise CorpusError(f"non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise CorpusError(f"non-finite JSON number: {value}")
    return number


def _strict_loads(text: str, label: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except CorpusError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CorpusError(f"invalid JSON: {label}: {error}") from error


def _strict_json(path: Path) -> Any:
    try:
        return _strict_loads(path.read_text(encoding="utf-8"), str(path))
    except OSError as error:
        raise CorpusError(f"cannot read JSON: {path}: {error}") from error


def _strict_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise CorpusError(f"cannot read JSONL: {path}: {error}") from error
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise CorpusError(f"blank JSONL line {path}:{line_number}")
        value = _strict_loads(line, f"{path}:{line_number}")
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


def _canonical_value(value: Any) -> bytes:
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


def _v2_path(root: Path, value: Any) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or Path(value).is_absolute()
        or Path(value).as_posix() != value
        or any(part in {"", ".", ".."} for part in Path(value).parts)
    ):
        raise CorpusError(f"v2 path is not normalized relative POSIX: {value!r}")
    candidate = (root / value).resolve()
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        raise CorpusError(f"v2 path escapes corpus: {value!r}")
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
        typed = _ANNUAL_OUTPUT_ADAPTER.validate_json(
            json.dumps(payload, ensure_ascii=False)
        )
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


def _validate_v1_manifest(
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
    fixture_declarations = {
        item["id"]: dict(item) for item in cast(list[dict[str, Any]], fixtures_declared)
    }
    fixture_raw_bytes = {
        fixture_id: fixture_paths[fixture_id].read_bytes() for fixture_id in fixtures
    }
    return Corpus(
        manifest,
        legacy,
        annual,
        fixtures,
        manifest_path=manifest_path,
        fixture_paths=fixture_paths,
        fixture_raw_bytes=fixture_raw_bytes,
        fixture_tools={
            fixture_id: "get_annual_toll_ballpark" for fixture_id in fixtures
        },
        fixture_declarations=fixture_declarations,
    )


def _v2_metadata(
    item: Any,
    label: str,
    *,
    release: bool = False,
    require_review_status: bool = False,
) -> dict[str, Any]:
    required_keys = _V2_RELEASE_METADATA_KEYS if release else _V2_METADATA_KEYS
    if require_review_status:
        required_keys = required_keys | {"review_status"}
    if (
        not isinstance(item, dict)
        or not set(item) >= required_keys
        or set(item) - (required_keys | _V2_METADATA_OPTIONAL_KEYS)
    ):
        raise CorpusError(f"{label} metadata keys are invalid")
    if not isinstance(item.get("id"), str) or not _ID.fullmatch(item["id"]):
        raise CorpusError(f"{label} metadata ID is invalid")
    if item.get("suite") not in {"current", "annual"}:
        raise CorpusError(f"{label} metadata suite is invalid")
    if item.get("primary_category") not in {
        "topology",
        "current",
        "annual",
        "multiturn",
        "fault",
        "abuse",
    }:
        raise CorpusError(f"{label} metadata category is invalid")
    if require_review_status and item.get("review_status") not in _V2_REVIEW_STATUSES:
        raise CorpusError(f"{label} metadata review_status is invalid")
    if release:
        if item.get("split") not in {"public", "private"}:
            raise CorpusError(f"{label} metadata split is invalid")
        for field in ("scenario_key", "template_key", "route_key"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 1024:
                raise CorpusError(f"{label} metadata {field} is invalid")
    if (
        not isinstance(item.get("tags"), list)
        or not item["tags"]
        or len(item["tags"]) != len(set(item["tags"]))
        or not all(isinstance(tag, str) and tag.strip() for tag in item["tags"])
    ):
        raise CorpusError(f"{label} metadata tags are invalid")
    for field in ("grouping", "provenance"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise CorpusError(f"{label} metadata {field} is invalid")
    assertion = item.get("expected_assertion")
    if (
        not isinstance(assertion, str)
        or not assertion.strip()
        or "Required:" not in assertion
        or "Prohibited:" not in assertion
    ):
        raise CorpusError(f"{label} metadata expected_assertion is invalid")
    suite_tool = (
        "get_current_toll_price"
        if item["suite"] == "current"
        else "get_annual_toll_ballpark"
    )
    if "expected_call" in item:
        _v2_validate_request(suite_tool, item["expected_call"], label)
    if "expected_calls" in item:
        calls = item["expected_calls"]
        if not isinstance(calls, list) or not calls:
            raise CorpusError(f"{label} metadata expected_calls is invalid")
        for call in calls:
            _v2_validate_request(suite_tool, call, label)
    for field in ("expected_clarification", "expected_missing_fields"):
        if field in item and (
            not isinstance(item[field], list)
            or not item[field]
            or not all(
                isinstance(value, str) and value.strip() for value in item[field]
            )
        ):
            raise CorpusError(f"{label} metadata {field} is invalid")
    if "expected_component_count" in item and (
        type(item["expected_component_count"]) is not int
        or item["expected_component_count"] < 0
    ):
        raise CorpusError(f"{label} metadata expected_component_count is invalid")
    if (
        "allow_pricing_unavailable" in item
        and type(item["allow_pricing_unavailable"]) is not bool
    ):
        raise CorpusError(f"{label} metadata allow_pricing_unavailable is invalid")
    if "allowed_route_statuses" in item and (
        not isinstance(item["allowed_route_statuses"], list)
        or not item["allowed_route_statuses"]
        or not all(
            isinstance(value, str) and value.strip()
            for value in item["allowed_route_statuses"]
        )
    ):
        raise CorpusError(f"{label} metadata allowed_route_statuses is invalid")
    checks = item.get("response_checks")
    if checks is not None:
        if not isinstance(checks, list) or not checks or len(checks) > 32:
            raise CorpusError(f"{label} metadata response_checks is invalid")
        turns: set[int] = set()
        for check in checks:
            if not isinstance(check, dict) or set(check) != {
                "turn",
                "required",
                "forbidden",
            }:
                raise CorpusError(f"{label} response check shape is invalid")
            turn = check["turn"]
            if type(turn) is not int or turn < 0 or turn in turns:
                raise CorpusError(f"{label} response check turn is invalid")
            turns.add(turn)
            for field in ("required", "forbidden"):
                patterns = check[field]
                if (
                    not isinstance(patterns, list)
                    or (field == "required" and not patterns)
                    or len(patterns) > 16
                    or not all(
                        isinstance(pattern, str) and pattern for pattern in patterns
                    )
                ):
                    raise CorpusError(f"{label} response check patterns are invalid")
                for pattern in patterns:
                    if len(pattern) > 200:
                        raise CorpusError(f"{label} response check regex is invalid")
                    try:
                        re.compile(pattern, re.IGNORECASE)
                    except re.error as error:
                        raise CorpusError(
                            f"{label} response check regex is invalid"
                        ) from error
    return item


def _v2_case_row(row: Any, label: str) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != _V2_ROW_KEYS:
        raise CorpusError(f"{label} has unknown or missing case keys")
    if not isinstance(row.get("id"), str) or not _ID.fullmatch(row["id"]):
        raise CorpusError(f"{label} has an unstable case ID")
    conversation = row.get("conversation")
    if (
        not isinstance(row.get("prompt"), str)
        or not row["prompt"].strip()
        or not isinstance(conversation, list)
        or not conversation
        or not all(isinstance(turn, str) and turn.strip() for turn in conversation)
        or conversation[0] != row["prompt"]
    ):
        raise CorpusError(f"{label} has an invalid prompt/conversation")
    if not isinstance(row.get("script"), list):
        raise CorpusError(f"{label} script is not a list")
    return row


def _v2_normalize_content(value: Any) -> Any:
    if isinstance(value, str):
        return (
            re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()
        )
    if isinstance(value, list):
        return [_v2_normalize_content(item) for item in value]
    if isinstance(value, dict):
        return {key: _v2_normalize_content(nested) for key, nested in value.items()}
    return value


def _v2_content_key(
    row: dict[str, Any], fixtures: dict[str, dict[str, Any]] | None = None
) -> bytes:
    script: list[dict[str, Any]] = []
    evidence: list[Any] = []
    for step in row.get("script", []):
        script.append(
            {key: value for key, value in step.items() if key != "fixture_id"}
        )
        if fixtures is not None:
            fixture = fixtures[step["fixture_id"]]
            evidence.append(
                fixture.get("result", fixture.get("payload", fixture.get("error")))
            )
    return _canonical(
        _v2_normalize_content(
            {
                "prompt": row["prompt"],
                "conversation": row["conversation"],
                "script": script,
                "evidence": evidence,
            }
        )
    )


def _v2_route_key(row: dict[str, Any], metadata: dict[str, Any]) -> str:
    """Derive stable route identity from the ordered authored script."""
    parts: list[str] = []
    for step in row.get("script", []):
        request = step["request"]
        if step["tool"] == "get_current_toll_price":
            route = f"{request['origin_point_id']}->{request['destination_point_id']}"
        else:
            route = ";".join(
                f"{direction}:{request[direction]['origin_point_id']}"
                f"->{request[direction]['destination_point_id']}"
                for direction in ("outbound", "return")
            )
        parts.append(f"{step['turn']}:{step['tool']}:{route}")
    identity = "|".join(parts) if parts else "no-tool-call"
    tags = metadata.get("tags", [])
    qualifiers = sorted(
        tag
        for tag in tags
        if isinstance(tag, str)
        and (tag.startswith("direction-") or tag.startswith("state-"))
    )
    return _sha256_bytes(
        (identity + ("#" + "#".join(qualifiers) if qualifiers else "")).encode()
    )


def _v2_canonical_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(
        re.sub(r"\s+", " ", str(row.get(field, "")).strip().casefold())
        for field in ("scenario_key", "template_key", "route_key")
    )  # type: ignore[return-value]


def _v2_validate_response_checks(
    metadata: dict[str, Any], conversation_length: int, label: str
) -> None:
    checks = metadata.get("response_checks")
    if checks is None:
        return
    for check in checks:
        if check["turn"] >= conversation_length:
            raise CorpusError(f"{label} response check turn is outside conversation")


def _v2_validate_request(tool: str, value: Any, label: str) -> dict[str, Any]:
    contract = _V2_TOOLS.get(tool)
    if contract is None:
        raise CorpusError(f"{label} uses an unknown tool")
    request_model = contract[0]
    if not isinstance(value, dict):
        raise CorpusError(f"{label} request is not an object")
    try:
        request_model.model_validate(value)
    except Exception as error:
        raise CorpusError(f"{label} request violates {tool} input contract") from error
    return value


def _v2_sanitize_fixture(value: Any, label: str, key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            lowered = child_key.casefold()
            normalized = re.sub(r"[^a-z0-9]", "", lowered)
            if (
                normalized
                in {"token", "authorization", "privatekey", "accesskey", "auth"}
                or normalized.endswith("token")
                or "apikey" in normalized
                or "accesskey" in normalized
                or "credential" in normalized
                or "password" in normalized
                or "secret" in normalized
                or normalized in {"usertext"}
            ):
                raise CorpusError(f"{label} contains a prohibited field: {child_key}")
            child_path = f"{key}.{child_key}" if key else child_key
            _v2_sanitize_fixture(child, label, child_path)
        return
    if isinstance(value, list):
        for child in value:
            _v2_sanitize_fixture(child, label, key)
        return
    if not isinstance(value, str):
        return
    if re.search(r"https?://", value, re.IGNORECASE):
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            raise CorpusError(f"{label} contains an unapproved URL") from None
        if (
            key != "result.components.published_schedule.source_url"
            or parsed.scheme != "https"
            or parsed.hostname not in _V2_ALLOWED_TYPED_URL_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
        ):
            raise CorpusError(f"{label} contains an unapproved URL")
    if "arn:aws:" in value.casefold():
        raise CorpusError(f"{label} contains a prohibited cloud identity")
    if re.search(
        r"(?:password|secret|token|credential|user[_ ]?text|access[_ ]?token)\s*[:=]",
        value,
        re.IGNORECASE,
    ):
        raise CorpusError(f"{label} contains prohibited secret or user data")


def _adapt_current_nullable_wire(result: Any, label: str) -> dict[str, Any]:
    """Validate the unchanged serializer's two proven nullable omissions.

    The application emits these nullable fields with ``exclude_none=True``.
    Adapt only those exact nested keys for model validation; callers retain the
    original result and source bytes for evidence and grading.
    """
    if not isinstance(result, dict):
        raise CorpusError(f"{label} current result is not an object")
    adapted = deepcopy(result)
    components = adapted.get("components")
    if not isinstance(components, list):
        return adapted
    for component in components:
        if not isinstance(component, dict):
            continue
        movement = component.get("recent_movement")
        if isinstance(movement, dict) and "net_change_percent" not in movement:
            try:
                samples = movement.get("samples", [])
                denominator = samples[0].get("price_usd") if samples else None
                zero_denominator = (
                    denominator is not None and Decimal(str(denominator)) == 0
                )
            except (
                AttributeError,
                IndexError,
                TypeError,
                ValueError,
                InvalidOperation,
            ):
                zero_denominator = False
            if zero_denominator:
                movement["net_change_percent"] = None
        comparison = component.get("prior_week_comparison")
        if isinstance(comparison, dict) and "current_delta_percent" not in comparison:
            try:
                zero_denominator = Decimal(str(comparison.get("median_usd"))) == 0
            except (TypeError, ValueError, InvalidOperation):
                zero_denominator = False
            if zero_denominator:
                comparison["current_delta_percent"] = None
    return adapted


def _v2_fixture_result_binding(
    fixture: dict[str, Any], request: dict[str, Any], tool: str, label: str
) -> None:
    result = fixture.get("result", fixture.get("payload"))
    if not isinstance(result, dict):
        return
    evaluated_at = fixture.get("evaluated_at")
    if evaluated_at is None and isinstance(fixture.get("source"), dict):
        evaluated_at = fixture["source"].get("captured_at")
    expected_timestamp = _normalized_capture_timestamp(evaluated_at, label)
    result_timestamp = result.get("evaluated_at")
    if (
        result_timestamp is not None
        and _normalized_capture_timestamp(result_timestamp, f"{label} result")
        != expected_timestamp
    ):
        raise CorpusError(f"{label} result evaluated_at disagrees with evidence")
    if tool == "get_current_toll_price":
        adapted_result = _adapt_current_nullable_wire(result, label)
        typed = _CURRENT_OUTPUT_ADAPTER.validate_json(
            json.dumps(adapted_result, ensure_ascii=False)
        )
        origin = result.get("origin_point_id")
        destination = result.get("destination_point_id")
        point_ids = result.get("point_ids")
        if isinstance(point_ids, list) and point_ids:
            origin, destination = point_ids[0], point_ids[-1]
        reason = result.get("reason")
        details = reason.get("details") if isinstance(reason, dict) else None
        if isinstance(details, dict):
            origin = details.get("origin_point_id", origin)
            destination = details.get("destination_point_id", destination)
            if result.get("status") == "invalid_origin":
                origin = details.get("point_id", origin)
            elif result.get("status") == "invalid_destination":
                destination = details.get("point_id", destination)
        if origin is not None and origin != request["origin_point_id"]:
            raise CorpusError(f"{label} result origin disagrees with request")
        if destination is not None and destination != request["destination_point_id"]:
            raise CorpusError(f"{label} result destination disagrees with request")
        if isinstance(typed, _CurrentPriceResponse):
            if adapted_result.get("pricing_profile") != request["pricing_profile"]:
                raise CorpusError(f"{label} result profile disagrees with request")
            if result_timestamp is None:
                raise CorpusError(f"{label} current result has no evaluated_at")
        return
    for field in ("weekdays", "planned_annual_commute_days"):
        if field in result and result[field] != request[field]:
            raise CorpusError(f"{label} result request fields disagree")
    income = result.get("income")
    if isinstance(income, dict) and (
        income.get("gross_annual_usd") != request["gross_annual_income_usd"]
    ):
        raise CorpusError(f"{label} result income disagrees with request")
    for direction in ("outbound", "return"):
        route = result.get(direction)
        if isinstance(route, dict):
            expected_route = request[direction]
            if any(
                route.get(field) != expected_route[field]
                for field in ("origin_point_id", "destination_point_id")
            ):
                raise CorpusError(f"{label} result route disagrees with request")


def _v2_validate_fixture_file(
    fixture: Any, path: Path, fixture_id: str, tool: str, label: str
) -> dict[str, Any]:
    if not isinstance(fixture, dict):
        raise CorpusError(f"{label} is not an object")
    base_keys = _V2_FIXTURE_FILE_KEYS - {"result", "error"}
    if set(fixture) not in (
        base_keys | {"result"},
        base_keys | {"error"},
    ):
        raise CorpusError(f"{label} has unknown or missing fixture keys")
    if fixture.get("fixture_id") != fixture_id or fixture.get("tool") != tool:
        raise CorpusError(f"{label} fixture identity disagrees with declaration")
    if fixture.get("tool_contract_version") != _V2_TOOL_CONTRACT_VERSIONS[tool]:
        raise CorpusError(f"{label} tool contract version is invalid")
    evidence_type = fixture.get("evidence_type")
    if evidence_type not in (_V2_SYNTHETIC_EVIDENCE | _V2_CAPTURE_EVIDENCE):
        raise CorpusError(f"{label} evidence type is invalid")
    evaluated_at = fixture.get("evaluated_at")
    _normalized_capture_timestamp(evaluated_at, label)
    provenance = fixture.get("provenance")
    if not isinstance(provenance, str) or not provenance.strip():
        raise CorpusError(f"{label} provenance is invalid")
    source = fixture.get("source")
    if evidence_type in _V2_CAPTURE_EVIDENCE:
        if (
            not isinstance(source, dict)
            or set(source) != {"id", "sha256"}
            or not isinstance(source["id"], str)
            or not _ID.fullmatch(source["id"])
            or not isinstance(source["sha256"], str)
            or not _SHA256.fullmatch(source["sha256"])
        ):
            raise CorpusError(f"{label} capture source identity is invalid")
    elif source is not None:
        raise CorpusError(f"{label} synthetic evidence cannot claim a source")
    request = _v2_validate_request(tool, fixture.get("request"), label)
    _v2_sanitize_fixture(fixture, label)
    contract = _V2_TOOLS[tool]
    try:
        if "result" in fixture:
            if not isinstance(fixture["result"], dict):
                raise ValueError("typed result is not an object")
            result = fixture["result"]
            if tool == "get_current_toll_price":
                result = _adapt_current_nullable_wire(result, label)
            contract[1].validate_json(json.dumps(result, ensure_ascii=False))
        else:
            if not isinstance(fixture["error"], dict):
                raise ValueError("typed error is not an object")
            contract[2].model_validate(fixture["error"])
    except Exception as error:
        raise CorpusError(
            f"{label} typed {('result' if 'result' in fixture else 'error')} is invalid"
        ) from error
    _v2_fixture_result_binding(fixture, request, tool, label)
    return fixture


def _v2_source_fixture_path(source_path: Path, fixture_id: str) -> Path:
    manifest = _json(source_path)
    for item in manifest.get("fixtures", []):
        if isinstance(item, dict) and item.get("id") == fixture_id:
            return _path(source_path.parent, item.get("path"))
    raise CorpusError(f"source fixture is undeclared: {fixture_id}")


def _v2_validate_manifest(
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    private: bool = False,
    public_ids: set[str] | None = None,
    public_canonical_keys: set[tuple[str, str, str]] | None = None,
    public_content_keys: set[bytes] | None = None,
) -> Corpus:
    try:
        dataset_version = _semver(manifest.get("dataset_version"), "dataset_version")
    except CorpusError:
        raise
    release = dataset_version >= (2, 1, 0)
    expected_keys = (
        _V2_PRIVATE_MANIFEST_KEYS
        if private
        else (_V2_RELEASE_KEYS if release else _V2_MANIFEST_KEYS)
    )
    if private and release:
        expected_keys = _V2_PRIVATE_MANIFEST_KEYS | {
            "allocation",
            "render_date",
            "direction_coverage",
        }
    if set(manifest) != expected_keys:
        raise CorpusError("v2 manifest has unknown or missing top-level keys")
    if manifest.get("corpus") != "annual-affordability":
        raise CorpusError("v2 manifest corpus name is invalid")
    if manifest.get("format_version") != "2.0.0":
        _semver(manifest.get("format_version"), "format_version")
        raise CorpusError("v2 manifest format_version must be 2.0.0")
    if dataset_version < (2, 0, 0) or (2, 0, 0) < dataset_version < (2, 1, 0):
        raise CorpusError("v2 manifest dataset_version must be 2.0.0 or at least 2.1.0")
    if release:
        if manifest.get("render_date") != "2026-09-05":
            raise CorpusError("v2 release render_date must be 2026-09-05")
        allocation = manifest.get("allocation")
        if not isinstance(allocation, dict) or set(allocation) != {
            *(_V2_CATEGORIES),
            "total",
        }:
            raise CorpusError("v2 release allocation is malformed")
        if any(
            type(allocation[key]) is not int or allocation[key] < 0
            for key in allocation
        ):
            raise CorpusError("v2 release allocation values are malformed")
        if allocation["total"] != sum(
            allocation[category] for category in _V2_CATEGORIES
        ):
            raise CorpusError("v2 release allocation total does not reconcile")
        if not private:
            expected_allocation = {
                **_V2_RELEASE_ALLOCATION,
                "total": sum(_V2_RELEASE_ALLOCATION.values()),
            }
            if allocation != expected_allocation:
                raise CorpusError(
                    "v2 release allocation does not match the approved release"
                )
        direction_coverage = manifest.get("direction_coverage")
        if not isinstance(direction_coverage, dict) or set(direction_coverage) != {
            "inventory_rows",
            "sampled_rows",
            "gaps",
        }:
            raise CorpusError("v2 direction coverage is malformed")
        if (
            type(direction_coverage.get("inventory_rows")) is not int
            or type(direction_coverage.get("sampled_rows")) is not int
            or direction_coverage["inventory_rows"] <= 0
            or direction_coverage["sampled_rows"] <= 0
            or not isinstance(direction_coverage.get("gaps"), list)
            or not direction_coverage["gaps"]
            or not all(
                isinstance(gap, str) and gap.strip()
                for gap in direction_coverage["gaps"]
            )
        ):
            raise CorpusError("v2 direction coverage is malformed")
        if direction_coverage["sampled_rows"] != allocation["topology"]:
            raise CorpusError("v2 direction coverage sampled_rows disagrees")
    if private:
        for field in ("public_dataset_sha256", "public_membership_sha256"):
            if not isinstance(manifest.get(field), str) or not _SHA256.fullmatch(
                manifest[field]
            ):
                raise CorpusError(f"private manifest {field} is malformed")
    manifest_path = manifest_path.resolve()
    source_declarations = manifest.get("source_manifests")
    if not isinstance(source_declarations, list):
        raise CorpusError("v2 source_manifests must be a list")
    if private and source_declarations:
        raise CorpusError("private v2 manifests cannot read source manifests")
    sources: dict[str, tuple[Path, Corpus, str]] = {}
    for item in source_declarations:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "format_version",
            "dataset_version",
            "dataset_sha256",
        }:
            raise CorpusError("v2 source manifest declaration is malformed")
        source_path = _v2_path(manifest_path.parent, item["path"])
        if source_path == manifest_path or str(source_path) in sources:
            raise CorpusError(
                "v2 source manifest paths must be unique and nonrecursive"
            )
        if (
            item["format_version"] != "1.0.0"
            or item["dataset_version"] != "1.0.0"
            or not isinstance(item["dataset_sha256"], str)
            or not _SHA256.fullmatch(item["dataset_sha256"])
        ):
            raise CorpusError("v2 source manifest must pin a v1 dataset")
        source_manifest = _json(source_path)
        if (
            not isinstance(source_manifest, dict)
            or source_manifest.get("format_version") != item["format_version"]
            or source_manifest.get("dataset_version") != item["dataset_version"]
        ):
            raise CorpusError("v2 source manifest version disagrees with declaration")
        try:
            source_corpus = _validate_v1_manifest(source_path)
        except CorpusError as error:
            raise CorpusError(
                f"invalid v2 source manifest {source_path}: {error}"
            ) from error
        if source_corpus.manifest.get("dataset_sha256") != item["dataset_sha256"]:
            raise CorpusError("v2 source manifest dataset hash mismatch")
        sources[str(source_path)] = (source_path, source_corpus, item["dataset_sha256"])
    if not private and not sources:
        raise CorpusError("public v2 manifest must declare a v1 source manifest")
    pinned_source_rows: dict[str, dict[str, Any]] = {}
    for _source_path, source_corpus, _source_hash in sources.values():
        for source_row in [*source_corpus.legacy_rows, *source_corpus.annual_rows]:
            source_id = source_row["id"]
            if source_id in pinned_source_rows:
                raise CorpusError(
                    f"v2 pinned source case is declared more than once: {source_id}"
                )
            pinned_source_rows[source_id] = source_row

    shards = manifest.get("case_shards")
    if not isinstance(shards, list) or (not shards and not private):
        raise CorpusError("v2 case_shards must be a nonempty list")
    shard_rows: dict[str, dict[str, Any]] = {}
    shard_owners: dict[str, str] = {}
    shard_paths: dict[str, Path] = {}
    for item in shards:
        if not isinstance(item, dict) or set(item) != _V2_SHARD_KEYS:
            raise CorpusError("v2 case shard declaration is malformed")
        path = _v2_path(manifest_path.parent, item.get("path"))
        path_key = item["path"]
        if path_key in shard_paths or path.suffix != ".jsonl":
            raise CorpusError("v2 case shard paths must be unique JSONL files")
        if type(item.get("count")) is not int:
            raise CorpusError("v2 case shard count is not an integer")
        rows = _strict_jsonl(path)
        if item["count"] != len(rows):
            raise CorpusError("v2 case shard count does not reconcile")
        shard_paths[path_key] = path
        for index, row in enumerate(rows, 1):
            row = _v2_case_row(row, f"v2 case {path_key}:{index}")
            if row["id"] in shard_rows:
                raise CorpusError("v2 case IDs are not unique across shards")
            shard_rows[row["id"]] = row
            shard_owners[row["id"]] = path_key

    metadata_items = manifest.get("case_metadata")
    if not isinstance(metadata_items, list):
        raise CorpusError("v2 case_metadata must be a list")
    metadata: dict[str, dict[str, Any]] = {}
    for item in metadata_items:
        value = _v2_metadata(
            item,
            "v2",
            release=release,
            require_review_status=dataset_version >= (2, 3, 0),
        )
        if value["id"] in metadata:
            raise CorpusError("v2 metadata IDs are not unique")
        metadata[value["id"]] = value

    membership = manifest.get("membership")
    if not isinstance(membership, list) or not membership:
        raise CorpusError("v2 membership must be a nonempty ordered list")
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for index, item in enumerate(membership, 1):
        if not isinstance(item, dict):
            raise CorpusError(f"v2 membership item {index} is malformed")
        if set(item) == _V2_SOURCE_KEYS:
            case_id = item["id"]
            if not isinstance(case_id, str) or case_id != item["source_case_id"]:
                raise CorpusError("v2 source membership ID is invalid")
            source_path = _v2_path(manifest_path.parent, item["source_manifest"])
            source = sources.get(str(source_path))
            if source is None or item["source_dataset_sha256"] != source[2]:
                raise CorpusError("v2 membership references an undeclared source")
            source_rows = [*source[1].legacy_rows, *source[1].annual_rows]
            source_row = next(
                (row for row in source_rows if row.get("id") == case_id), None
            )
            if source_row is None:
                raise CorpusError(f"v2 source case is undeclared: {case_id}")
            if (
                not isinstance(item["source_case_sha256"], str)
                or not _SHA256.fullmatch(item["source_case_sha256"])
                or item["source_case_sha256"] != _sha256_bytes(_canonical(source_row))
            ):
                raise CorpusError(f"v2 source case hash mismatch: {case_id}")
            row = dict(source_row)
        elif set(item) == _V2_NEW_MEMBER_KEYS:
            case_id = item["id"]
            if not isinstance(case_id, str) or item["shard"] not in shard_paths:
                raise CorpusError("v2 shard membership is invalid")
            if shard_owners.get(case_id) != item["shard"]:
                raise CorpusError(f"v2 membership shard does not own case: {case_id}")
            row = shard_rows.get(case_id)
            if (
                row is None
                or not isinstance(item["row_sha256"], str)
                or not _SHA256.fullmatch(item["row_sha256"])
                or item["row_sha256"] != _sha256_bytes(_canonical(row))
            ):
                raise CorpusError(f"v2 selected row hash mismatch: {case_id}")
            row = dict(row)
            source_row = pinned_source_rows.get(case_id)
            if source_row is not None:
                inherited = {
                    key: deepcopy(value)
                    for key, value in source_row.items()
                    if key
                    not in {"id", "prompt", "conversation", "follow_up", "script"}
                }
                inherited.update(row)
                row = inherited
        else:
            raise CorpusError(f"v2 membership item {index} has unknown keys")
        if case_id in selected_ids:
            raise CorpusError("v2 membership contains duplicate case IDs")
        selected_ids.add(case_id)
        selected.append(row)
    if private and public_ids and selected_ids & public_ids:
        raise CorpusError("private v2 membership overlaps public case IDs")
    if set(metadata) != selected_ids:
        raise CorpusError("v2 metadata must have exactly one entry per selected case")

    fixture_declaration_items = manifest.get("fixtures")
    if not isinstance(fixture_declaration_items, list):
        raise CorpusError("v2 fixtures must be a list")
    fixtures: dict[str, dict[str, Any]] = {}
    fixture_tools: dict[str, str] = {}
    fixture_paths_by_id: dict[str, Path] = {}
    fixture_raw_bytes: dict[str, bytes] = {}
    fixture_declarations: dict[str, dict[str, Any]] = {}
    fixture_paths: set[str] = set()
    for item in fixture_declaration_items:
        if not isinstance(item, dict):
            raise CorpusError("v2 fixture declaration is malformed")
        if set(item) == _V2_FIXTURE_SOURCE_KEYS:
            fixture_id = item["id"]
            if not isinstance(fixture_id, str) or not _ID.fullmatch(fixture_id):
                raise CorpusError("v2 fixture ID is invalid")
            source_path = _v2_path(manifest_path.parent, item["source_manifest"])
            source = sources.get(str(source_path))
            if (
                source is None
                or item["tool"] not in _V2_TOOLS
                or item["tool_contract_version"]
                != _V2_TOOL_CONTRACT_VERSIONS[item["tool"]]
            ):
                raise CorpusError("v2 source fixture reference is invalid")
            source_fixture_id = item["source_fixture_id"]
            fixture = source[1].fixtures.get(source_fixture_id)
            if fixture is None or item["tool"] != "get_annual_toll_ballpark":
                raise CorpusError("v2 source fixture tool is invalid")
            source_fixture_path = _v2_source_fixture_path(
                source_path, source_fixture_id
            )
            source_fixture_raw = source[1].fixture_raw_bytes[source_fixture_id]
            expected_hash = item["source_fixture_sha256"]
            if not isinstance(expected_hash, str) or not _SHA256.fullmatch(
                expected_hash
            ):
                raise CorpusError("v2 source fixture hash is malformed")
            if expected_hash != _sha256_bytes(source_fixture_raw):
                raise CorpusError("v2 source fixture hash mismatch")
            if fixture_id in fixtures:
                raise CorpusError("v2 fixture IDs are not unique")
            fixtures[fixture_id] = fixture
            fixture_tools[fixture_id] = item["tool"]
            fixture_paths_by_id[fixture_id] = source_fixture_path
            fixture_raw_bytes[fixture_id] = source_fixture_raw
            fixture_declarations[fixture_id] = dict(item)
        elif set(item) == {"id", "tool", "path", "tool_contract_version"}:
            fixture_id = item["id"]
            tool = item["tool"]
            if (
                not isinstance(fixture_id, str)
                or not _ID.fullmatch(fixture_id)
                or tool not in _V2_TOOLS
                or item["tool_contract_version"] != _V2_TOOL_CONTRACT_VERSIONS[tool]
            ):
                raise CorpusError("v2 fixture declaration is invalid")
            path = _v2_path(manifest_path.parent, item["path"])
            if item["path"] in fixture_paths or fixture_id in fixtures:
                raise CorpusError("v2 fixture IDs or paths are not unique")
            fixture_paths.add(item["path"])
            try:
                raw = path.read_bytes()
                parsed = _strict_loads(raw.decode("utf-8"), str(path))
            except OSError as error:
                raise CorpusError(f"cannot read JSON: {path}: {error}") from error
            except UnicodeError as error:
                raise CorpusError(f"cannot decode JSON: {path}: {error}") from error
            fixture = _v2_validate_fixture_file(
                parsed, path, fixture_id, tool, f"v2 fixture {fixture_id}"
            )
            fixtures[fixture_id] = fixture
            fixture_tools[fixture_id] = tool
            fixture_paths_by_id[fixture_id] = path
            fixture_raw_bytes[fixture_id] = raw
            fixture_declarations[fixture_id] = dict(item)
        else:
            raise CorpusError("v2 fixture declaration has unknown keys")

    rows: list[dict[str, Any]] = []
    selected_contents: set[bytes] = set()
    for row in selected:
        item = dict(row)
        overlay = metadata[item["id"]]
        source_suite = item.get("suite")
        if source_suite is not None:
            item["source_suite"] = source_suite
        for source_key in (
            "annual_behavior",
            "expected_call",
            "expected_calls",
            "expected_clarification",
            "expected_missing_fields",
            "expected_route_status",
            "expected_component_count",
            "allow_pricing_unavailable",
            "expected_reasons",
            "expected_availability",
            "expected_required_i95_directions",
        ):
            if source_key in item:
                item[f"source_{source_key}"] = deepcopy(item[source_key])
        if (
            item.get("suite") in {"current", "annual"}
            and item["suite"] != overlay["suite"]
        ):
            raise CorpusError(f"v2 metadata suite disagrees with case {item['id']}")
        item.update(overlay)
        if "conversation" not in item:
            item["conversation"] = [item["prompt"]]
        if item.get("follow_up") and item["follow_up"] not in item["conversation"]:
            item["conversation"] = list(item["conversation"])
            item["conversation"].append(item["follow_up"])
        if item.get("fixture_id") is not None and item["fixture_id"] not in fixtures:
            raise CorpusError(f"v2 case {item['id']} references an undeclared fixture")
        if (
            "script" not in item
            and isinstance(item.get("expected_call"), dict)
            and isinstance(item.get("fixture_id"), str)
        ):
            item["script"] = [
                {
                    "turn": (
                        len(item["conversation"]) - 1
                        if item.get("expected_clarification")
                        or item.get("annual_behavior")
                        in {
                            "annual_day_estimate",
                            "income_clarification",
                            "schedule_correction",
                        }
                        else 0
                    ),
                    "tool": (
                        "get_current_toll_price"
                        if item["suite"] == "current"
                        else "get_annual_toll_ballpark"
                    ),
                    "request": item["expected_call"],
                    "fixture_id": item["fixture_id"],
                }
            ]
        if "script" not in item or not isinstance(item["script"], list):
            raise CorpusError(f"v2 case {item['id']} requires an ordered script")
        _v2_validate_response_checks(
            item, len(item["conversation"]), f"v2 case {item['id']}"
        )
        script = item["script"]
        if not script and (
            isinstance(item.get("expected_call"), dict)
            or isinstance(item.get("expected_calls"), list)
            or item.get("fixture_id") is not None
        ):
            raise CorpusError(f"v2 case {item['id']} has call metadata but no script")
        for step_index, step in enumerate(script, 1):
            label = f"v2 case {item['id']} script step {step_index}"
            if not isinstance(step, dict) or set(step) != {
                "turn",
                "tool",
                "request",
                "fixture_id",
            }:
                raise CorpusError(f"{label} has unknown or missing keys")
            if type(step["turn"]) is not int or not 0 <= step["turn"] < len(
                item["conversation"]
            ):
                raise CorpusError(f"{label} has an invalid conversation turn")
            tool = step["tool"]
            if tool not in _V2_TOOLS:
                raise CorpusError(f"{label} uses an unknown tool")
            request = _v2_validate_request(tool, step["request"], label)
            fixture_id = step["fixture_id"]
            if not isinstance(fixture_id, str) or fixture_id not in fixtures:
                raise CorpusError(f"{label} references an undeclared fixture")
            if fixture_tools[fixture_id] != tool:
                raise CorpusError(f"{label} fixture tool does not match request tool")
            fixture = fixtures[fixture_id]
            if "request" in fixture and fixture["request"] != request:
                raise CorpusError(f"{label} request disagrees with fixture")
            if "result" in fixture:
                try:
                    _V2_TOOLS[tool][1].validate_json(
                        json.dumps(
                            _adapt_current_nullable_wire(fixture["result"], label)
                            if tool == "get_current_toll_price"
                            else fixture["result"],
                            ensure_ascii=False,
                        )
                    )
                except Exception as error:
                    raise CorpusError(f"{label} fixture result is invalid") from error
            elif "payload" in fixture:
                try:
                    _V2_TOOLS[tool][1].validate_json(
                        json.dumps(fixture["payload"], ensure_ascii=False)
                    )
                except Exception as error:
                    raise CorpusError(
                        f"{label} source fixture result is invalid"
                    ) from error
            else:
                try:
                    _V2_TOOLS[tool][2].model_validate(fixture["error"])
                except Exception as error:
                    raise CorpusError(f"{label} fixture error is invalid") from error
            _v2_fixture_result_binding(fixture, request, tool, label)
        content = _v2_content_key(item, fixtures)
        if content in selected_contents:
            raise CorpusError("v2 membership contains duplicate case content")
        selected_contents.add(content)
        if release and item["route_key"] != _v2_route_key(item, item):
            raise CorpusError(
                f"v2 case {item['id']} route identity disagrees with script"
            )
        rows.append(item)
    if release:
        actual_allocation = {
            category: sum(1 for row in rows if row.get("primary_category") == category)
            for category in _V2_CATEGORIES
        }
        if actual_allocation != {
            category: manifest["allocation"][category] for category in _V2_CATEGORIES
        }:
            raise CorpusError(
                "v2 selected rows do not match the declared category allocation"
            )
        if sum(actual_allocation.values()) != manifest["allocation"]["total"]:
            raise CorpusError("v2 selected rows do not match allocation total")
        if private and any(row.get("split") != "private" for row in rows):
            raise CorpusError("private v2 rows must use the private split")
        if not private and any(row.get("split") != "public" for row in rows):
            raise CorpusError("public v2 rows must use the public split")
        canonical_keys = [_v2_canonical_identity(row) for row in rows]
        if public_canonical_keys and set(canonical_keys) & public_canonical_keys:
            raise CorpusError("private v2 canonical identity overlaps public corpus")
    if private and public_content_keys:
        content_keys = [_v2_content_key(row, fixtures) for row in rows]
        if set(content_keys) & public_content_keys:
            raise CorpusError("private v2 content overlaps public corpus")
    used_fixture_ids = {
        step["fixture_id"] for row in rows for step in row.get("script", [])
    }
    if set(fixtures) != used_fixture_ids:
        raise CorpusError("v2 fixtures must be referenced by the ordered scripts")

    expected_payload_paths = sorted([*shard_paths, *fixture_paths])
    payloads = manifest.get("payloads")
    if (
        not isinstance(payloads, list)
        or [item.get("path") for item in payloads if isinstance(item, dict)]
        != expected_payload_paths
    ):
        raise CorpusError("v2 payload paths do not enumerate declared local files")
    for item in payloads:
        if (
            not isinstance(item, dict)
            or set(item) != _V2_PAYLOAD_KEYS
            or not isinstance(item["sha256"], str)
            or not _SHA256.fullmatch(item["sha256"])
        ):
            raise CorpusError("v2 payload declaration is malformed")
        path = _v2_path(manifest_path.parent, item["path"])
        try:
            actual = _sha256_bytes(path.read_bytes())
        except OSError as error:
            raise CorpusError(f"v2 payload is unavailable: {path}") from error
        if actual != item["sha256"]:
            raise CorpusError(f"v2 payload hash mismatch: {item['path']}")
    membership_hash = _sha256_bytes(_canonical_value(membership))
    if manifest.get("membership_sha256") != membership_hash:
        raise CorpusError("v2 membership_sha256 mismatch")
    without_hash = {
        key: value for key, value in manifest.items() if key != "dataset_sha256"
    }
    if manifest.get("dataset_sha256") != _sha256_bytes(_canonical_value(without_hash)):
        raise CorpusError("v2 dataset_sha256 mismatch")
    if private and public_ids is None:
        raise CorpusError("private validation requires a supplied public corpus")
    legacy = [row for row in rows if row.get("suite") == "current"]
    annual = [row for row in rows if row.get("suite") == "annual"]
    return Corpus(
        manifest,
        legacy,
        annual,
        fixtures,
        rows,
        manifest_path=manifest_path,
        fixture_paths=fixture_paths_by_id,
        fixture_raw_bytes=fixture_raw_bytes,
        fixture_tools=fixture_tools,
        fixture_declarations=fixture_declarations,
    )


def validate(
    manifest_path: Path = _DEFAULT_MANIFEST, base_ref: str | None = None
) -> Corpus:
    manifest_path = manifest_path.resolve()
    manifest = _json(manifest_path)
    if not isinstance(manifest, dict):
        raise CorpusError("manifest is not an object")
    if manifest.get("format_version") == "2.0.0":
        strict_manifest = _strict_json(manifest_path)
        if not isinstance(strict_manifest, dict):
            raise CorpusError("v2 manifest is not an object")
        corpus = _v2_validate_manifest(manifest_path, strict_manifest)
        if base_ref is not None:
            old_manifest, _old_payloads = _base_manifest(manifest_path, base_ref)
            if (
                old_manifest is not None
                and old_manifest.get("format_version") == "2.0.0"
            ):
                old_version = _semver(
                    old_manifest.get("dataset_version"), "base dataset_version"
                )
                current_version = _semver(
                    strict_manifest.get("dataset_version"), "dataset_version"
                )
                excluded = {"dataset_version", "dataset_sha256"}
                changed = {
                    key: value
                    for key, value in strict_manifest.items()
                    if key not in excluded
                } != {
                    key: value
                    for key, value in old_manifest.items()
                    if key not in excluded
                }
                if changed and current_version <= old_version:
                    raise CorpusError(
                        "edited v2 corpus requires an advanced dataset_version"
                    )
                if not changed and current_version != old_version:
                    raise CorpusError(
                        "unchanged v2 corpus has a gratuitously advanced dataset_version"
                    )
        return corpus
    return _validate_v1_manifest(manifest_path, base_ref)


def validate_private_manifest(
    manifest_path: Path, public_corpus: Corpus | Path
) -> Corpus:
    """Validate trusted-parent private rows against the supplied public corpus."""
    public = (
        public_corpus if isinstance(public_corpus, Corpus) else validate(public_corpus)
    )
    path = manifest_path.resolve()
    manifest = _strict_json(path)
    if not isinstance(manifest, dict):
        raise CorpusError("private manifest is not an object")
    public_membership_hash = public.manifest.get("membership_sha256")
    if not isinstance(public_membership_hash, str):
        public_membership_hash = _sha256_bytes(
            _canonical_value([row["id"] for row in public.rows])
        )
    if manifest.get("public_dataset_sha256") != public.manifest.get("dataset_sha256"):
        raise CorpusError("private manifest public dataset identity mismatch")
    if manifest.get("public_membership_sha256") != public_membership_hash:
        raise CorpusError("private manifest public membership identity mismatch")
    return _v2_validate_manifest(
        path,
        manifest,
        private=True,
        public_ids={row["id"] for row in public.rows},
        public_canonical_keys={
            _v2_canonical_identity(row)
            for row in public.rows
            if {"scenario_key", "template_key", "route_key"}.issubset(row)
        },
        public_content_keys={
            _v2_content_key(row, public.fixtures) for row in public.rows
        },
    )


validate_private = validate_private_manifest


def load_rows(manifest_path: Path = _DEFAULT_MANIFEST) -> list[dict[str, Any]]:
    return validate(manifest_path).rows


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _v2_selection_rows(
    corpus: Corpus, selection_file: Path | None
) -> list[dict[str, Any]]:
    if selection_file is None:
        return list(corpus.rows)
    path = Path(selection_file)
    if not path.is_file() or path.is_symlink():
        raise CorpusError("selection file must be a regular file")
    selection = _strict_json(path)
    if not isinstance(selection, dict):
        raise CorpusError("selection file must contain an object")
    by_id = {row["id"]: row for row in corpus.rows}
    try:
        # Keep the fixed pilot IDs/order in the existing baseline contract. The
        # import stays lazy because baseline imports Corpus from this module.
        from eval.baseline import validate_selection

        validated = validate_selection(selection, corpus)
    except (KeyError, TypeError, ValueError) as error:
        raise CorpusError(
            f"selection file is not the approved pilot: {error}"
        ) from error
    if validated["phase"] != "pilot":
        raise CorpusError("selection file must describe the approved pilot")
    return [by_id[case_id] for case_id in validated["cases"]]


def _render_v2(
    corpus: Corpus, output_path: Path, selection_file: Path | None = None
) -> Path:
    rows = _v2_selection_rows(corpus, selection_file)
    cards: list[str] = []
    category_labels = {
        "topology": "Road connections",
        "current": "Current toll",
        "annual": "Yearly toll budget",
        "multiturn": "Follow-up questions",
        "fault": "Pricing failures",
        "abuse": "Unsafe requests",
    }
    for number, row in enumerate(rows, 1):
        turns = "".join(f"<li>{_esc(turn)}</li>" for turn in row["conversation"])
        cards.append(
            f'<article class="case-card"><h2>Case {number}</h2>'
            f'<p class="category">{_esc(category_labels[row["primary_category"]])}</p>'
            f"<h3>Conversation</h3><ol>{turns}</ol>"
            f"<h3>Expected behavior</h3><p>{_esc(row['expected_assertion'])}</p></article>"
        )
    html_text = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Toll case review</title>
<style>body{{font:16px system-ui,sans-serif;line-height:1.5;margin:0;background:#f4f7fb;color:#18202a}}main{{max-width:900px;margin:auto;padding:2rem}}.case-card{{background:white;border:1px solid #ccd6e0;border-radius:.5rem;padding:1rem;margin:1rem 0}}.category{{color:#52677c;font-weight:600}}h2{{margin:.1rem 0}}</style></head>
<body><main><h1>Public case review</h1><p>{len(rows)} cases for human review.</p>{"".join(cards)}</main></body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    return output_path


def render(
    manifest_path: Path = _DEFAULT_MANIFEST,
    output_path: Path = Path(".graph/golden-review.html"),
    selection_file: Path | None = None,
) -> Path:
    corpus = validate(manifest_path)
    if corpus.manifest.get("format_version") == "2.0.0":
        return _render_v2(corpus, output_path, selection_file)
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
        cards.append(
            f'<article class="case-card" data-case-id="{_esc(row["id"])}" data-scenario="{_esc(row["scenario_family"])}" data-outcome="{_esc(row["outcome"])}">'
            f'<h2>{_esc(row["id"])}</h2><p class="tags">{_esc(row["scenario_family"])} · {_esc(row["outcome"])}</p>'
            f"<h3>Prompt and conversation</h3><p>{_esc(row['prompt'])}</p><ol>{conversation_html}</ol>"
            f"<h3>Expected required/prohibited behavior</h3><p>{_esc(row['expected_assertion'])}</p>"
            f"<h3>Deterministic evaluator behavior</h3><p>{_esc(expected_behavior)}</p>"
            "</article>"
        )
    capture_html = "".join(
        f"<li><strong>{_esc(item.get('capture_id'))}</strong>: {_esc(item.get('result'))}; "
        f"{_esc(item.get('corpus_use'))}. This is pinned provenance context only, "
        "not a model run. Fixture payloads are stored in the corpus files.</li>"
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
    render_parser.add_argument("--selection-file", type=Path)
    args = parser.parse_args()
    if args.command == "validate":
        corpus = validate(args.manifest, args.base_ref)
        print(
            f"validated {len(corpus.legacy_rows)} legacy + {len(corpus.annual_rows)} golden = {len(corpus.rows)} unique cases; {len(corpus.fixtures)} fixtures"
        )
    elif args.command == "render":
        print(render(args.manifest, args.output, args.selection_file))


if __name__ == "__main__":
    main()
