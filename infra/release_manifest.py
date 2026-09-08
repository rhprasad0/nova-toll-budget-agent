"""Verify the reviewed development release manifest without exposing its data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

try:
    from .delivery_plan_validator import validate_plan
except ImportError:  # Direct script execution.
    from delivery_plan_validator import validate_plan


MANIFEST_KEYS = {
    "schema_version",
    "provider_identity",
    "deployment_inputs",
    "packages",
    "mutations",
    "permissions",
}
PROVIDER_IDENTITY = {
    "provider": "hashicorp/aws",
    "provider_version": "6.60.0",
    "terraform_version": "1.15.8",
    "lockfile": "v2/infra/.terraform.lock.hcl",
    "lock_identity": "V2-AWS60",
}
PACKAGES = ("agentcore.zip", "chat-proxy.zip", "loader.zip", "publisher.zip")
EXACT_INPUTS = {
    ".github/workflows/v2-development-delivery.yml",
    ".github/workflows/v2-development-plan.yml",
    "infra/account-contract.json",
    "infra/.terraform.lock.hcl",
    "infra/backend.development.hcl",
    "infra/delivery_plan_validator.py",
    "infra/lambda-stub/handler.py",
    "infra/release_manifest.py",
    "v2/agent-sops/nova-toll-pricing-assistant.sop.md",
    "v2/agent/__init__.py",
    "v2/agent/agentcore_entrypoint.py",
    "v2/agent/dev_chat.html",
    "v2/agent/faq.html",
    "v2/agent/privacy.txt",
    "v2/agent/public-api-gate.js",
    "v2/agent/public-report-routes.js",
    "v2/agent/public_chat.mjs",
    "v2/agent/terms.txt",
    "v2/agent/toll_agent.py",
    "v2/analytics/agent_registry.ndjson",
    "v2/infra/.terraform.lock.hcl",
    "v2/infra/backend.development.hcl",
    "v2/infra/development.tfvars",
    "v2/infra/lambda-stub/handler.py",
    "v2/lambdas/chat_proxy/handler.mjs",
    "v2/lambdas/chat_proxy/package-lock.json",
    "v2/lambdas/chat_proxy/package.json",
    "v2/lambdas/loader/_bounds.py",
    "v2/lambdas/loader/handler.py",
    "v2/lambdas/loader/parse_csv.py",
    "v2/lambdas/loader/parse_xml.py",
    "v2/lambdas/publisher/handler.py",
    "v2/pyproject.toml",
    "v2/scripts/build_agentcore_zips.sh",
    "v2/scripts/build_loader_zip.sh",
    "v2/scripts/build_publisher_zip.sh",
    "v2/scripts/loader-requirements.in",
    "v2/scripts/loader-requirements.txt",
    "v2/scripts/publisher-requirements.in",
    "v2/scripts/publisher-requirements.txt",
    "v2/uv.lock",
}
INPUT_PREFIXES = ("v2/agent/assets/", "v2/agent_tools/")
BUNDLE_MARKER = "v2/scripts/build_release_bundle.sh"
BUNDLE_FIXED_INPUTS = {
    BUNDLE_MARKER,
    "v2/scripts/verify_release_bundle.py",
    "v2/db/application-schemas.json",
    "v2/db/migration-baselines.json",
    "v2/db/schema.sql",
    "v2/db/analysis.sql",
    "v2/db/roles.sql",
    "v2/db/oracle/schema.sql",
    "v2/db/oracle/data.sql",
}
BUNDLE_OPTIONAL_INPUTS = {
    "v2/scripts/check_development_admission.py",
    "v2/scripts/check_development_release.py",
    "v2/scripts/development_deployment_status.py",
    "v2/scripts/run_development_migrations.py",
    "v2/scripts/run_development_migrations_workflow.sh",
    ".github/workflows/v2-development-migrations.yml",
}
BUNDLE_INPUT_PREFIXES = ("v2/db/migrations/",)
FIXED_BACKENDS = {
    "infra/backend.development.hcl": """bucket       = "nova-toll-tfstate-903859731897"
key          = "nova-toll/development/terraform.tfstate"
region       = "us-east-1"
use_lockfile = true
encrypt      = true
kms_key_id   = "alias/nova-toll-tfstate"
""",
    "v2/infra/backend.development.hcl": """bucket       = "nova-toll-tfstate-903859731897"
key          = "nova-toll/v2/development/terraform.tfstate"
region       = "us-east-1"
use_lockfile = true
encrypt      = true
kms_key_id   = "alias/nova-toll-tfstate"
""",
}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")


class Invalid(Exception):
    pass


def _reject(reason: str) -> NoReturn:
    raise Invalid(reason)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject("duplicate_json_key")
        result[key] = value
    return result


def _load(path: Path, reason: str) -> Any:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            _reject(reason)
        with path.open(encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_pairs)
    except Invalid:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        _reject(reason)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_file(path: Path, reason: str) -> str:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            _reject(reason)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Invalid:
        raise
    except OSError:
        _reject(reason)


def _valid_relative(path: str) -> bool:
    pure = PurePosixPath(path)
    return (
        bool(path)
        and not pure.is_absolute()
        and ".." not in pure.parts
        and str(pure) == path
    )


def _selected(path: str, bundle_enabled: bool = False) -> bool:
    selected = (
        path in EXACT_INPUTS
        or any(path.startswith(prefix) for prefix in INPUT_PREFIXES)
        or (path.startswith("infra/") and path.endswith(".tf"))
        or (path.startswith("v2/infra/") and path.endswith(".tf"))
    )
    if selected or not bundle_enabled:
        return selected
    return path in BUNDLE_FIXED_INPUTS | BUNDLE_OPTIONAL_INPUTS or any(
        path.startswith(prefix) and path.endswith(".sql")
        for prefix in BUNDLE_INPUT_PREFIXES
    )


def _tracked_inputs(repo_root: Path) -> list[str]:
    try:
        output = subprocess.run(
            ["git", "-C", os.fspath(repo_root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        ).stdout
        tracked = [path.decode("utf-8") for path in output.split(b"\0") if path]
    except (OSError, UnicodeError, subprocess.CalledProcessError):
        _reject("inventory_unavailable")
    bundle_enabled = BUNDLE_MARKER in tracked
    if bundle_enabled and not BUNDLE_FIXED_INPUTS.issubset(tracked):
        _reject("inventory_incomplete")
    paths = sorted(path for path in tracked if _selected(path, bundle_enabled))
    if not paths or set(EXACT_INPUTS) - set(paths):
        _reject("inventory_incomplete")
    return paths


def _validate_manifest(value: Any) -> tuple[dict[str, str], dict[str, str]]:
    if (
        not isinstance(value, dict)
        or set(value) != MANIFEST_KEYS
        or value.get("schema_version") != 1
    ):
        _reject("manifest_schema_invalid")
    if value.get("provider_identity") != PROVIDER_IDENTITY:
        _reject("provider_identity_mismatch")
    inputs, packages = value.get("deployment_inputs"), value.get("packages")
    if not isinstance(inputs, dict) or not isinstance(packages, dict):
        _reject("manifest_schema_invalid")
    if list(inputs) != sorted(inputs) or any(
        not _valid_relative(path) for path in inputs
    ):
        _reject("inventory_invalid")
    if set(packages) != set(PACKAGES) or list(packages) != list(PACKAGES):
        _reject("package_inventory_invalid")
    if any(
        not isinstance(digest, str) or not HEX64.fullmatch(digest)
        for digest in (*inputs.values(), *packages.values())
    ):
        _reject("digest_invalid")
    if any(
        inputs.get(path) != _digest_bytes(content.encode())
        for path, content in FIXED_BACKENDS.items()
    ):
        _reject("backend_identity_mismatch")
    if not isinstance(value.get("mutations"), list) or not isinstance(
        value.get("permissions"), list
    ):
        _reject("manifest_schema_invalid")
    contract_result = validate_plan(
        {
            "terraform_version": PROVIDER_IDENTITY["terraform_version"],
            "resource_changes": [],
        },
        value,
        PROVIDER_IDENTITY,
    )
    if contract_result.get("status") != "accepted":
        _reject("mutation_contract_invalid")
    return inputs, packages


def _verify_inputs(repo_root: Path, expected: dict[str, str]) -> None:
    actual_paths = _tracked_inputs(repo_root)
    if actual_paths != list(expected):
        _reject("inventory_mismatch")
    for relative, digest in expected.items():
        if _digest_file(repo_root / relative, "input_unreadable") != digest:
            _reject("input_digest_mismatch")


def _read_checksums(path: Path) -> dict[str, str]:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            _reject("checksums_invalid")
        lines = path.read_text(encoding="ascii").splitlines()
    except Invalid:
        raise
    except (OSError, UnicodeError):
        _reject("checksums_invalid")
    result: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9.-]+)", line)
        if not match or match.group(2) in result:
            _reject("checksums_invalid")
        result[match.group(2)] = match.group(1)
    if tuple(sorted(result)) != PACKAGES:
        _reject("checksums_invalid")
    return result


def _verify_packages(
    package_dir: Path, checksums_path: Path, expected: dict[str, str]
) -> None:
    try:
        if package_dir.is_symlink() or not package_dir.is_dir():
            _reject("package_inventory_invalid")
        names = tuple(sorted(path.name for path in package_dir.glob("*.zip")))
    except OSError:
        _reject("package_inventory_invalid")
    if names != PACKAGES or _read_checksums(checksums_path) != expected:
        _reject("package_inventory_invalid")
    for name, digest in expected.items():
        if _digest_file(package_dir / name, "package_unreadable") != digest:
            _reject("package_digest_mismatch")


def _evidence(
    manifest: Any,
    inputs: dict[str, str],
    packages: dict[str, str],
    candidate_sha: str,
    run_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "candidate_sha": candidate_sha,
        "run_id": run_id,
        "manifest_fingerprint": _digest_bytes(_canonical(manifest)),
        "deployment_inputs_fingerprint": _digest_bytes(_canonical(inputs)),
        "packages_fingerprint": _digest_bytes(_canonical(packages)),
    }


def verify(args: argparse.Namespace) -> dict[str, Any]:
    if not SHA40.fullmatch(args.candidate_sha) or not args.run_id.isdigit():
        _reject("runtime_binding_invalid")
    manifest = _load(args.manifest, "manifest_unreadable")
    inputs, packages = _validate_manifest(manifest)
    _verify_packages(args.package_dir, args.checksums, packages)
    expected_evidence = _evidence(
        manifest, inputs, packages, args.candidate_sha, args.run_id
    )
    if args.repo_root is not None:
        _verify_inputs(args.repo_root, inputs)
        if args.evidence is not None:
            _reject("evidence_mode_invalid")
        try:
            descriptor = os.open(
                args.write_evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    expected_evidence, handle, sort_keys=True, separators=(",", ":")
                )
                handle.write("\n")
        except OSError:
            _reject("evidence_unwritable")
    else:
        if args.evidence is None or args.write_evidence is not None:
            _reject("evidence_mode_invalid")
        evidence = _load(args.evidence, "evidence_unreadable")
        if evidence != expected_evidence:
            _reject("evidence_mismatch")
    return {
        "status": "accepted",
        "reason_code": "ok",
        "manifest_fingerprint": expected_evidence["manifest_fingerprint"],
        "deployment_inputs_fingerprint": expected_evidence[
            "deployment_inputs_fingerprint"
        ],
        "packages_fingerprint": expected_evidence["packages_fingerprint"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--checksums", type=Path, required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--write-evidence", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(args)
    except Invalid as error:
        result = {"status": "rejected", "reason_code": str(error)}
    except Exception:
        result = {"status": "rejected", "reason_code": "malformed_input"}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
