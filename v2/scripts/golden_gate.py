"""Trusted golden evidence admission and development-only immutable storage.

This module uses the standard library so production revalidation needs no eval
SDK or model credential. A decision is accepted only from a completed protected
workflow with the exact currently reviewed evaluator code and configuration.
"""

from __future__ import annotations

import hashlib
import json
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
POLICY = ROOT / "v2/eval/results/golden/policy-2.0.0.json"
MAX_BYTES = 32 * 1024 * 1024
CODE = (
    WORKFLOW,
    ".github/workflows/v2-golden-read.yml",
    ".github/workflows/v2-golden-baseline.yml",
    ".github/workflows/v2-production-plan.yml",
    ".github/workflows/v2-production-migrations.yml",
    "v2/scripts/check_production_release.py",
    "v2/scripts/verify_release_bundle.py",
    "v2/scripts/development_deployment_status.py",
    "v2/scripts/golden_gate.py",
    "v2/scripts/golden_release.py",
    "v2/eval/artifact_agent.py",
    "v2/eval/artifact_worker.py",
    "v2/eval/golden_run.py",
    "v2/eval/golden_actor_check.py",
    "v2/eval/golden.py",
    "v2/eval/golden_baseline.py",
    "v2/eval/golden/manifest.json",
    "v2/eval/golden/calibration-reference.json",
    "v2/eval/simulated.py",
    "v2/agent/toll_agent.py",  # Evaluator cache adapter and credential loader.
    "v2/eval/run_evaluation.py",
    "v2/uv.lock",
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
    manifest = read(ROOT / "v2/eval/golden/manifest.json")
    require(
        digest(manifest["hashes"]) == manifest["corpus_sha256"],
        "active corpus manifest changed",
    )
    for name, expected in obj(manifest["hashes"]).items():
        path = ROOT / name if name.startswith("v2/") else ROOT / "v2/eval/golden" / name
        require(
            path.resolve().is_relative_to(ROOT.resolve())
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
            "active corpus files changed",
        )
    return digest(
        {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE}
    )


def policy() -> dict[str, Any]:
    value = read(POLICY)
    approval, limits = obj(value["approval"]), obj(value["policy"])
    require(
        approval.get("status") == "approved"
        and approval.get("evidence_sha256") == digest(limits)
        and bool(approval.get("reviewer"))
        and bool(approval.get("evidence")),
        "active policy awaits exact human approval",
    )
    return limits


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


def trusted_run(run_id: int, *, completed: bool) -> dict[str, Any]:
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
            value.get("status") == "completed" and value.get("conclusion") == "success",
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


def recent_production() -> dict[str, Any]:
    deployments = release.api(
        "GET", "deployments?environment=production-release&per_page=100"
    )
    require(isinstance(deployments, list), "production history unavailable")
    for record in cast(list[dict[str, Any]], deployments):
        statuses = release.api(
            "GET", f"deployments/{record['id']}/statuses?per_page=100"
        )
        if any(
            s.get("state") == "success" for s in cast(list[dict[str, Any]], statuses)
        ):
            return record
    raise ValueError("no successful production deployment")


def production_reference() -> tuple[dict[str, Any], str]:
    body, metadata = get_object("baseline/current.json")
    pointer = obj(json.loads(body))
    require(
        pointer.get("production") is not None, "approved production baseline is unset"
    )
    require(
        pointer["production"]["claim_id"] == recent_production()["id"],
        "baseline does not match deployed production",
    )
    evidence = obj(json.loads(fetch(pointer["approval"])))
    approved = receipt(evidence["evaluation_run_id"])
    require(
        approved["report_sha256"] == pointer["report_sha256"]
        and approved["archive"] == pointer["archive"]
        and digest(approved) == evidence["receipt_sha256"]
        and evidence["production"]["claim_id"] == pointer["production"]["claim_id"]
        and evidence["production"]["candidate"] == approved["candidate"]
        and evidence["production"].get("outcome") == "success",
        "baseline approval mismatch",
    )
    return pointer, metadata["ETag"]


def age(created: str, maximum_hours: int, now: datetime | None = None) -> None:
    value = datetime.fromisoformat(created)
    require(value.tzinfo is not None, "timestamp needs timezone")
    require(
        0
        <= ((now or datetime.now(UTC)) - value).total_seconds()
        <= maximum_hours * 3600,
        "expired evidence",
    )


def validate_receipt(
    value: dict[str, Any],
    admission: dict[str, Any],
    baseline: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    limits = policy()
    require(
        value.get("qualified") is True
        and value.get("errors") == []
        and value.get("purpose") == "candidate",
        "candidate did not qualify",
    )
    for key in (
        "candidate",
        "bundle_id",
        "bundle_digest",
        "development_run",
        "development_attempt",
        "development_deployment",
    ):
        require(
            value.get(key) == admission.get(key), "candidate/artifact identity mismatch"
        )
    require(
        value.get("policy_sha256") == digest(limits)
        and value.get("contract_sha256") == limits["contract_sha256"],
        "policy/contract mismatch",
    )
    require(
        value.get("baseline_sha256") == digest(baseline), "production baseline changed"
    )
    age(value["created_at"], limits["candidate_max_age_hours"], now)
    age(baseline["created_at"], limits["production_max_age_hours"], now)


def candidate_key(candidate: str, baseline: dict[str, Any]) -> str:
    experiment = digest(
        {
            "policy": digest(policy()),
            "baseline": digest(baseline),
            "code": code_digest(),
        }
    )
    return f"candidates/{candidate}/{experiment}.json"


def admit(admission: dict[str, Any]) -> dict[str, Any]:
    development_account()
    pointer, _ = production_reference()
    body, _ = get_object(candidate_key(admission["candidate"], pointer))
    index = obj(json.loads(body))
    value = receipt(index["run_id"])
    require(index["receipt_sha256"] == digest(value), "candidate index mismatch")
    validate_receipt(value, admission, pointer)
    fetch(value["archive"])
    binding = {
        "run_id": value["run_id"],
        "receipt_sha256": digest(value),
        "policy_sha256": value["policy_sha256"],
        "baseline_sha256": value["baseline_sha256"],
        "created_at": value["created_at"],
        "report_sha256": value["report_sha256"],
    }
    require(
        "golden" not in admission or admission["golden"] == binding,
        "previous golden admission changed",
    )
    admission["golden"] = binding
    return admission


def revalidate(admission: dict[str, Any]) -> None:
    binding = obj(admission.get("golden"))
    value = receipt(binding["run_id"])
    require(
        digest(value) == binding.get("receipt_sha256")
        and value.get("policy_sha256") == binding.get("policy_sha256")
        and value.get("baseline_sha256") == binding.get("baseline_sha256")
        and value.get("report_sha256") == binding.get("report_sha256"),
        "golden binding changed",
    )
    require(
        value.get("qualified") is True
        and value.get("errors") == []
        and value.get("purpose") == "candidate",
        "golden decision failed",
    )
    for key in (
        "candidate",
        "bundle_id",
        "bundle_digest",
        "development_run",
        "development_attempt",
        "development_deployment",
    ):
        require(value.get(key) == admission.get(key), "golden candidate mismatch")
    age(value["created_at"], policy()["candidate_max_age_hours"])


if __name__ == "__main__":
    try:
        value = admit(read(Path(sys.argv[1])))
        write(Path(sys.argv[2]), value)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        raise SystemExit("golden evidence: blocked") from None
