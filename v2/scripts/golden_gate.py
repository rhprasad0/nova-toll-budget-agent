"""Trusted golden evidence admission and development-only immutable storage.

The standard library and system OpenSSL verify external aggregate evidence;
no eval SDK or model credential is required. Decisions require a completed
protected workflow, exact importer identity, and actual human approval.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import check_production_release as release

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = "903859731897"
BUCKET = "nova-toll-golden-evidence-903859731897"
WORKFLOW = ".github/workflows/v2-golden-evaluation.yml"
POLICY = ROOT / "v2/eval/results/golden/policy-3.0.0.json"
PUBLIC_KEY = ROOT / "v2/eval/results/golden/evaluator-public.pem"
MAX_BYTES = 32 * 1024 * 1024
IDENTITY = (
    "candidate",
    "bundle_id",
    "bundle_digest",
    "development_run",
    "development_attempt",
    "development_deployment",
)
CODE = (
    WORKFLOW,
    ".github/workflows/v2-golden-read.yml",
    ".github/workflows/v2-production-plan.yml",
    ".github/workflows/v2-production-migrations.yml",
    "v2/scripts/run_production_migrations_workflow.sh",
    "v2/scripts/check_production_release.py",
    "v2/scripts/verify_release_bundle.py",
    "v2/scripts/development_deployment_status.py",
    "v2/scripts/golden_gate.py",
    "v2/scripts/golden_release.py",
)


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def obj(value: object) -> dict[str, Any]:
    require(isinstance(value, dict), "expected object")
    return cast(dict[str, Any], value)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def read(path: Path) -> dict[str, Any]:
    return obj(json.loads(path.read_bytes()))


def write(path: Path, value: object) -> None:
    path.write_bytes(canonical(value) + b"\n")


def code_digest() -> str:
    policy()  # No local corpus, historical policy, or unset signer can activate this gate.
    return digest(
        {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE}
    )


def policy() -> dict[str, Any]:
    value = read(POLICY)
    approval, limits = obj(value["approval"]), obj(value["policy"])
    require(
        limits.get("version") == "3.0.0"
        and limits.get("evaluation_scope") == "private-held-out"
        and limits.get("cases") == 100
        and limits.get("trials") == 3
        and limits.get("successes_min") == 240
        and limits.get("candidate_max_age_hours") == 24
        and limits.get("run_cost_max_usd") == 5
        and limits.get("authorized_cost_max_usd") == 25,
        "unsupported private qualification policy",
    )
    require(
        approval.get("status") == "approved"
        and approval.get("evidence_sha256") == digest(limits)
        and bool(approval.get("reviewer"))
        and bool(approval.get("evidence")),
        "active policy awaits exact human approval",
    )
    for name in (
        "holdout_sha256",
        "evaluator_sha256",
        "calibration_sha256",
        "public_key_sha256",
    ):
        require(is_hash(limits.get(name)), "private evaluator activation is incomplete")
    require(
        PUBLIC_KEY.is_file()
        and hashlib.sha256(PUBLIC_KEY.read_bytes()).hexdigest()
        == limits["public_key_sha256"],
        "trusted evaluator public key is unavailable or changed",
    )
    timestamp(approval.get("approved_at"))
    return limits


def is_hash(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def timestamp(value: object) -> datetime:
    require(isinstance(value, str) and len(value) <= 40, "invalid timestamp")
    result = datetime.fromisoformat(cast(str, value))
    require(result.tzinfo is not None, "timestamp needs timezone")
    return result


def fields(value: object, names: str) -> dict[str, Any]:
    result = obj(value)
    require(set(result) == set(names.split()), "unexpected or missing aggregate fields")
    return result


def number(value: object, maximum: float, *, integer: bool = False) -> float:
    require(
        type(value) in ({int} if integer else {int, float})
        and 0 <= cast(float, value) <= maximum
        and math.isfinite(cast(float, value)),
        "invalid aggregate number",
    )
    return cast(float, value)


def strict_json(body: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    require(len(body) <= 16384, "aggregate summary too large")
    return obj(json.loads(body, object_pairs_hook=unique))


def verify_summary(packet: bytes) -> dict[str, Any]:
    """Authenticate exact bytes before interpreting the aggregate-only schema."""
    limits = policy()
    envelope = fields(strict_json(packet), "summary_base64 signature_base64")
    try:
        body = base64.b64decode(envelope["summary_base64"], validate=True)
        signature = base64.b64decode(envelope["signature_base64"], validate=True)
    except (binascii.Error, TypeError, ValueError) as exc:
        raise ValueError("invalid signed envelope") from exc
    require(len(signature) == 64, "invalid Ed25519 signature")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "summary").write_bytes(body)
        (root / "signature").write_bytes(signature)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-rawin",
                "-pubin",
                "-inkey",
                str(PUBLIC_KEY),
                "-in",
                str(root / "summary"),
                "-sigfile",
                str(root / "signature"),
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
    require(result.returncode == 0, "invalid evaluator signature")
    summary = strict_json(body)
    validate_summary(summary, limits)
    return summary


def validate_summary(summary: dict[str, Any], limits: dict[str, Any]) -> None:
    fields(
        summary,
        "schema_version evaluation_scope candidate bundle_id bundle_digest "
        "development_run development_attempt development_deployment policy_sha256 "
        "holdout_sha256 evaluator_sha256 calibration_sha256 cases trials "
        "holdout_attempts cumulative_cost_usd unknown_usage private_review_complete "
        "attempts",
    )
    require(
        type(summary["schema_version"]) is int and summary["schema_version"] == 1,
        "unsupported summary schema",
    )
    require(
        summary["evaluation_scope"] == "private-held-out",
        "development evidence cannot qualify",
    )
    require(
        isinstance(summary["candidate"], str)
        and re.fullmatch(r"[0-9a-f]{40}", summary["candidate"]) is not None,
        "invalid candidate commit",
    )
    require(
        isinstance(summary["bundle_digest"], str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", summary["bundle_digest"]) is not None,
        "invalid bundle digest",
    )
    for key in IDENTITY[1:]:
        if key != "bundle_digest":
            require(
                number(summary[key], 2**53 - 1, integer=True) > 0,
                "invalid artifact identity",
            )
    require(summary["policy_sha256"] == digest(limits), "summary policy mismatch")
    for key in (
        "holdout_sha256",
        "evaluator_sha256",
        "calibration_sha256",
        "cases",
        "trials",
    ):
        require(
            type(summary[key]) is type(limits[key]) and summary[key] == limits[key],
            "summary contract mismatch",
        )
    require(
        type(summary["unknown_usage"]) is bool
        and type(summary["private_review_complete"]) is bool,
        "invalid review attestation",
    )
    attempts = summary["attempts"]
    require(
        isinstance(attempts, list) and 1 <= len(cast(list[object], attempts)) <= 2,
        "one original and one replacement only",
    )
    attempts = cast(list[dict[str, Any]], attempts)
    total_cost = 0.0
    previous_end = timestamp(read(POLICY)["approval"]["approved_at"])
    for index, raw in enumerate(cast(list[object], attempts)):
        trial = fields(
            raw,
            "started_at completed_at replacement_reason passed failed inconclusive "
            "unmeasured case_pass_counts success_interval latency_p50_seconds "
            "latency_p95_seconds agent_cost_usd total_cost_usd",
        )
        started, ended = (
            timestamp(trial["started_at"]),
            timestamp(trial["completed_at"]),
        )
        require(
            previous_end <= started <= ended <= datetime.now(UTC),
            "invalid execution chronology",
        )
        previous_end = ended
        reason = trial["replacement_reason"]
        require(
            (index == 0 and reason == "none")
            or (index == 1 and reason in ("infrastructure", "actor_validity")),
            "quality-only retries are forbidden",
        )
        if index:
            prior = attempts[0]
            require(
                prior["unmeasured"] > 0
                if reason == "infrastructure"
                else prior["inconclusive"] > 0,
                "replacement lacks an invalid or incomplete original",
            )
        for key in ("passed", "failed", "inconclusive", "unmeasured"):
            number(trial[key], 300, integer=True)
        require(
            sum(trial[k] for k in ("passed", "failed", "inconclusive", "unmeasured"))
            == 300,
            "trial counts must total 300",
        )
        histogram = trial["case_pass_counts"]
        require(
            isinstance(histogram, list) and len(cast(list[object], histogram)) == 4,
            "invalid consistency counts",
        )
        histogram = cast(list[int], histogram)
        for count in histogram:
            number(count, 100, integer=True)
        require(
            sum(histogram) == 100
            and sum(i * n for i, n in enumerate(histogram)) == trial["passed"],
            "inconsistent pass counts",
        )
        interval = fields(trial["success_interval"], "method lower upper")
        require(
            interval["method"] == "case-bootstrap-95",
            "uncertainty must resample whole cases",
        )
        number(interval["lower"], 1)
        number(interval["upper"], 1)
        require(
            interval["lower"] <= trial["passed"] / 300 <= interval["upper"],
            "invalid uncertainty interval",
        )
        for key in ("latency_p50_seconds", "latency_p95_seconds"):
            if trial[key] is not None:
                number(trial[key], 86400)
        require(
            (
                trial["latency_p50_seconds"] is None
                and trial["latency_p95_seconds"] is None
            )
            or (
                trial["latency_p50_seconds"] is not None
                and trial["latency_p95_seconds"] is not None
                and trial["latency_p50_seconds"] <= trial["latency_p95_seconds"]
            ),
            "invalid latency percentiles",
        )
        number(trial["agent_cost_usd"], 1_000_000)
        number(trial["total_cost_usd"], 1_000_000)
        require(
            trial["agent_cost_usd"] <= trial["total_cost_usd"],
            "inconsistent evaluation cost",
        )
        total_cost += trial["total_cost_usd"]
    require(
        number(summary["holdout_attempts"], 2**53 - 1, integer=True) >= len(attempts),
        "missing cumulative holdout attempts",
    )
    require(
        number(summary["cumulative_cost_usd"], 1_000_000) >= total_cost,
        "inconsistent cumulative spending",
    )


def decision(summary: dict[str, Any]) -> dict[str, Any]:
    limits = policy()
    validate_summary(summary, limits)
    current = summary["attempts"][-1]
    errors: list[str] = []
    if current["inconclusive"] or current["unmeasured"]:
        errors.append(
            "inconclusive: all 300 trials need valid simulations and judgments"
        )
    if current["passed"] < limits["successes_min"]:
        errors.append("fewer than 240 successful trials")
    if summary["unknown_usage"] or not summary["private_review_complete"]:
        errors.append(
            "usage reconciliation or independent evidence review is incomplete"
        )
    if current["latency_p50_seconds"] is None:
        errors.append("latency measurements are missing")
    if (
        any(
            a["total_cost_usd"] > limits["run_cost_max_usd"]
            for a in summary["attempts"]
        )
        or summary["cumulative_cost_usd"] > limits["authorized_cost_max_usd"]
    ):
        errors.append("approved spending limit exceeded")
    try:
        age(current["completed_at"], limits["candidate_max_age_hours"])
    except ValueError:
        errors.append("expired candidate evidence")
    return {"qualified": not errors, "errors": errors}


def aws(*args: str) -> dict[str, Any]:
    result = subprocess.run(
        ["aws", *args, "--region", "us-east-1", "--output", "json"],
        capture_output=True,
        timeout=120,
        check=False,
    )
    require(result.returncode == 0, "development evidence storage unavailable")
    return obj(json.loads(result.stdout or b"{}"))


def development_account() -> None:
    require(
        aws("sts", "get-caller-identity").get("Account") == ACCOUNT,
        "development account required",
    )


def get_object(key: str, version: str | None = None) -> tuple[bytes, dict[str, Any]]:
    require(
        bool(re.fullmatch(r"[a-zA-Z0-9/_.-]+", key)) and ".." not in key,
        "invalid storage key",
    )
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "object"
        args = [
            "s3api",
            "get-object",
            "--bucket",
            BUCKET,
            "--key",
            key,
            "--expected-bucket-owner",
            ACCOUNT,
        ]
        if version:
            args += ["--version-id", version]
        metadata = aws(*args, str(path))
        require(
            path.stat().st_size <= MAX_BYTES and bool(metadata.get("VersionId")),
            "invalid evidence object",
        )
        return path.read_bytes(), metadata


def put_object(key: str, body: bytes, etag: str | None = None) -> dict[str, Any]:
    require(len(body) <= MAX_BYTES, "evidence too large")
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "object"
        path.write_bytes(body)
        condition = ["--if-match", etag] if etag else ["--if-none-match", "*"]
        result = aws(
            "s3api",
            "put-object",
            "--bucket",
            BUCKET,
            "--key",
            key,
            "--body",
            str(path),
            "--expected-bucket-owner",
            ACCOUNT,
            "--server-side-encryption",
            "AES256",
            *condition,
        )
    require(bool(result.get("VersionId")), "versioned evidence required")
    return {
        "key": key,
        "version_id": result["VersionId"],
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def fetch(reference: dict[str, Any]) -> bytes:
    require(
        set(reference) == {"key", "version_id", "sha256"}
        and bool(reference["version_id"]),
        "unversioned evidence",
    )
    body, _ = get_object(reference["key"], reference["version_id"])
    require(
        hashlib.sha256(body).hexdigest() == reference["sha256"],
        "evidence hash mismatch",
    )
    return body


def immutable(key: str, body: bytes) -> dict[str, Any]:
    """Retry identical publication without replacing an existing object."""
    try:
        return put_object(key, body)
    except ValueError:
        existing, metadata = get_object(key)
        require(existing == body, "immutable evidence collision")
        return {
            "key": key,
            "version_id": metadata["VersionId"],
            "sha256": hashlib.sha256(body).hexdigest(),
        }


def protection(environment: str, *, review: bool = True) -> dict[str, Any]:
    value = obj(release.api("GET", f"environments/{environment}"))
    require(
        value.get("can_admins_bypass") is False, "environment bypass must be disabled"
    )
    rules = value.get("protection_rules", [])
    if review:
        require(
            any(
                r.get("type") == "required_reviewers" and r.get("reviewers")
                for r in rules
            ),
            "required reviewer missing",
        )
    branches = obj(
        release.api("GET", f"environments/{environment}/deployment-branch-policies")
    )
    require(
        [(b.get("name"), b.get("type")) for b in branches.get("branch_policies", [])]
        == [("main", "branch")],
        "environment must allow only main",
    )
    return value


def human_approval(run_id: int, environment: str) -> dict[str, Any]:
    settings = protection(environment)
    approved = release.api("GET", f"actions/runs/{run_id}/approvals")
    require(isinstance(approved, list), "missing environment review")
    matches = [
        obj(a)
        for a in cast(list[object], approved)
        if obj(a).get("state") == "approved"
        and any(e.get("id") == settings["id"] for e in obj(a).get("environments", []))
    ]
    require(
        len(matches) == 1 and bool(matches[0].get("user", {}).get("login")),
        "ambiguous or missing human approval",
    )
    allowed = {
        r["reviewer"]["login"]
        for rule in settings["protection_rules"]
        if rule.get("type") == "required_reviewers"
        for r in rule["reviewers"]
        if r.get("type") == "User"
    }
    require(matches[0]["user"]["login"] in allowed, "reviewer not authorized")
    return matches[0]


def trusted_run(
    run_id: int, *, completed: bool, successful: bool = True
) -> dict[str, Any]:
    value = obj(release.api("GET", f"actions/runs/{run_id}"))
    require(
        value.get("repository", {}).get("full_name") == release.REPOSITORY
        and value.get("head_repository", {}).get("full_name") == release.REPOSITORY
        and value.get("path", "").split("@")[0] == WORKFLOW
        and value.get("head_branch") == "main"
        and value.get("event") == "workflow_dispatch"
        and value.get("run_attempt") == 1,
        "untrusted or replayed evaluation workflow",
    )
    if completed:
        require(
            value.get("status") == "completed"
            and (not successful or value.get("conclusion") == "success"),
            "evaluation did not complete successfully",
        )
    else:
        require(value.get("status") == "in_progress", "evaluation is not active")
    return value


def receipt(run_id: int) -> dict[str, Any]:
    producer = trusted_run(run_id, completed=True)
    artifact = release._artifacts(run_id, f"golden-decision-{run_id}-1")
    result = release._single_json(artifact, "receipt.json")  # pyright: ignore[reportPrivateUsage]
    require(
        result.get("run_id") == run_id
        and result.get("attempt") == 1
        and result.get("trusted_sha") == producer["head_sha"]
        and result.get("evaluation_code_sha256") == code_digest(),
        "evaluation code/provenance mismatch",
    )
    require(
        result.get("review") == human_approval(run_id, "golden-review"),
        "human approval mismatch",
    )
    require(result.get("policy_sha256") == digest(policy()), "active policy changed")
    return result


def age(created: str, maximum_hours: int, now: datetime | None = None) -> None:
    value = datetime.fromisoformat(created)
    require(value.tzinfo is not None, "timestamp needs timezone")
    require(
        0
        <= ((now or datetime.now(UTC)) - value).total_seconds()
        <= maximum_hours * 3600,
        "expired evidence",
    )


def validate_receipt(value: dict[str, Any], admission: dict[str, Any]) -> None:
    require(
        value.get("schema_version") == 2 and value.get("purpose") == "candidate",
        "historical receipt cannot qualify",
    )
    require(
        value.get("qualified") is True and value.get("errors") == [],
        "candidate did not qualify",
    )
    for key in IDENTITY:
        require(
            value.get(key) == admission.get(key), "candidate/artifact identity mismatch"
        )
    # Later production stages have GitHub access, not development AWS credentials.
    # Carry the signed bytes in the authenticated receipt so verification stays local.
    packet = canonical(obj(value.get("signed_summary")))
    require(
        hashlib.sha256(packet).hexdigest() == obj(value.get("archive")).get("sha256"),
        "signed archive binding changed",
    )
    summary = verify_summary(packet)
    require(decision(summary)["qualified"], "signed evidence did not qualify")
    require(
        all(summary[key] == value[key] for key in IDENTITY),
        "signed artifact identity mismatch",
    )
    require(
        value.get("report_sha256") == digest(summary)
        and value.get("policy_sha256") == digest(policy())
        and value.get("holdout_sha256") == summary["holdout_sha256"]
        and value.get("created_at") == summary["attempts"][-1]["completed_at"],
        "signed evidence binding changed",
    )


def candidate_key(candidate: str) -> str:
    return f"candidates/private/{candidate}/{digest(policy())}.json"


def binding(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt_sha256": digest(value),
        **{
            key: value[key]
            for key in (
                "run_id",
                "policy_sha256",
                "holdout_sha256",
                "created_at",
                "report_sha256",
            )
        },
    }


def admit(admission: dict[str, Any]) -> dict[str, Any]:
    code_digest()
    development_account()
    body, _ = get_object(candidate_key(admission["candidate"]))
    index = fields(strict_json(body), "run_id receipt_sha256 report_sha256")
    value = receipt(index["run_id"])
    require(
        index["receipt_sha256"] == digest(value)
        and index["report_sha256"] == value["report_sha256"],
        "candidate index mismatch",
    )
    validate_receipt(value, admission)
    fetch(obj(value.get("archive")))  # Durable storage is checked under the read role.
    result = binding(value)
    require(
        "golden" not in admission or admission["golden"] == result,
        "previous golden admission changed",
    )
    admission["golden"] = result
    return admission


def revalidate(admission: dict[str, Any]) -> None:
    code_digest()
    expected = obj(admission.get("golden"))
    value = receipt(expected["run_id"])
    require(binding(value) == expected, "golden binding changed")
    validate_receipt(value, admission)


if __name__ == "__main__":
    try:
        write(Path(sys.argv[2]), admit(read(Path(sys.argv[1]))))
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        raise SystemExit("golden evidence: blocked") from None
