# pyright: basic
"""Trusted host boundary for one disposable fixture worker container."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval.container_worker import (
    _contains_credential,
    encode_input,
    failure_record,
    strict_json,
)
from eval.fixture_runner import FixtureRunPacket, RateCard, write_raw_artifact

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_FILES = (
    "v2/eval/runtime-requirements.txt",
    "v2/agent/__init__.py",
    "v2/agent/toll_agent.py",
    "v2/agent_tools/current_price_domain.py",
    "v2/agent_tools/get_annual_toll_ballpark.py",
    "v2/agent_tools/get_current_toll_price.py",
    "v2/agent_tools/validate_toll_route.py",
    "v2/agent-sops/nova-toll-pricing-assistant.sop.md",
    "v2/eval/fixture_runner.py",
    "v2/eval/container_worker.py",
    "v2/eval/Dockerfile",
)
_CONTEXT_FILES = tuple(relative.removeprefix("v2/") for relative in _BUILD_FILES)
_RUN_FLAGS = (
    "docker",
    "run",
    "--rm",
    "-i",
    "--network=bridge",
    "--read-only",
    "--user=10001:10001",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m",
    "--log-driver=none",
)


@dataclass(frozen=True)
class ContainerEvidence:
    image: str
    image_id: str | None
    source_digest: str


@dataclass(frozen=True)
class ContainerTrial:
    record: dict[str, Any]
    evidence: ContainerEvidence


def _docker_environment() -> dict[str, str]:
    """Keep AWS, database, packet, and credential environment out of Docker."""
    path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return {"PATH": path}


def _validated_sources(root: Path, files: tuple[str, ...]) -> tuple[Path, ...]:
    root = root.resolve()
    sources: list[Path] = []
    for relative in files:
        source = root / relative
        try:
            resolved = source.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ValueError("container build input is unavailable") from None
        if not resolved.is_relative_to(root):
            raise ValueError("container build input escapes root")
        current = source
        while current != root:
            if current.is_symlink():
                raise ValueError("container build input cannot be a symlink")
            current = current.parent
        try:
            mode = resolved.stat().st_mode
        except OSError:
            raise ValueError("container build input is unavailable") from None
        if not stat.S_ISREG(mode):
            raise ValueError("container build input must be a regular file")
        sources.append(source)
    return tuple(sources)


def _digest_files(root: Path, files: tuple[str, ...]) -> str:
    sources = _validated_sources(root, files)
    digest = hashlib.sha256()
    for relative, path in zip(_CONTEXT_FILES, sources, strict=True):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def source_digest(root: Path = _REPO_ROOT) -> str:
    """Hash the exact files copied into the worker image."""
    return _digest_files(root, _BUILD_FILES)


def _image_id(image: str) -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format={{.Id}}", image],
        check=False,
        capture_output=True,
        text=True,
        env=_docker_environment(),
    )
    value = result.stdout.strip()
    if result.returncode or not _IMAGE_ID.fullmatch(value):
        raise RuntimeError("container image identity unavailable")
    return value


def build_image(
    image: str,
    *,
    root: Path = _REPO_ROOT,
) -> ContainerEvidence:
    """Build and identify the explicitly allowlisted worker image."""
    if not image or any(character.isspace() for character in image):
        raise ValueError("invalid image name")
    root = root.resolve()
    sources = _validated_sources(root, _BUILD_FILES)
    with tempfile.TemporaryDirectory(prefix="tollchat-build-") as context_name:
        context = Path(context_name)
        for relative, source_path in zip(_BUILD_FILES, sources, strict=True):
            target = context / relative.removeprefix("v2/")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
        source = _digest_files(context, _CONTEXT_FILES)
        result = subprocess.run(
            ["docker", "build", "--file", "eval/Dockerfile", "--tag", image, "."],
            check=False,
            capture_output=True,
            cwd=context,
            env=_docker_environment(),
        )
    if result.returncode:
        raise RuntimeError("container image build failed")
    return ContainerEvidence(
        image=image, image_id=_image_id(image), source_digest=source
    )


def _valid_record(
    value: object,
    packet: FixtureRunPacket,
    trial_id: str,
    credential: str,
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("worker returned no record")
    record = value
    allowed = {
        "trial_id",
        "case_id",
        "output",
        "stdout",
        "exit_code",
        "failure_class",
        "error",
    }
    required = allowed - {"error"}
    if not required <= set(record) or not set(record) <= allowed:
        raise ValueError("worker returned an invalid record")
    if record["trial_id"] != trial_id or record["case_id"] != packet.case_id:
        raise ValueError("worker record identity disagrees")
    if type(record["output"]) is not dict or not isinstance(record["stdout"], str):
        raise ValueError("worker record payload is invalid")
    if type(record["exit_code"]) is not int or record["exit_code"] not in (0, 1):
        raise ValueError("worker record status is invalid")
    if type(record["failure_class"]) is not str or record["failure_class"] not in {
        "none",
        "infra_dependency",
    }:
        raise ValueError("worker record status is invalid")
    if _contains_credential(record, credential):
        raise ValueError("worker reflected credential")
    return record


def _parse_stdout(
    stdout: bytes,
    packet: FixtureRunPacket,
    trial_id: str,
    credential: str,
) -> dict[str, Any]:
    lines = stdout.splitlines()
    if len(lines) != 1 or not lines[0].strip():
        raise ValueError("worker stdout must contain one JSON record")
    return _valid_record(strict_json(lines[0]), packet, trial_id, credential)


def _mark_infrastructure_failure(record: dict[str, Any]) -> dict[str, Any]:
    record = dict(record)
    output = record.get("output")
    if type(output) is dict:
        output = dict(output)
        output["error"] = "container_exit_failure"
        record["output"] = output
    record["failure_class"] = "infra_dependency"
    record["exit_code"] = 1
    record["error"] = "container_exit_failure"
    return record


def _safe_failure_id(value: object, credential: object) -> str:
    if not isinstance(value, str) or not value:
        return "unknown"
    if (
        isinstance(credential, str)
        and credential
        and _contains_credential(value, credential)
    ):
        return "unknown"
    return value


def _execution_evidence(evidence: ContainerEvidence, credential: str) -> dict[str, Any]:
    value = {
        "image": evidence.image,
        "image_id": evidence.image_id,
        "source_digest": evidence.source_digest,
    }
    if _contains_credential(value, credential):
        return {"image": "unknown", "image_id": None, "source_digest": "0" * 64}
    return value


def run_container_trial(
    packet: FixtureRunPacket,
    *,
    key: str,
    rate_card: RateCard,
    trial_id: str,
    artifact_root: Path,
    evidence: ContainerEvidence,
) -> ContainerTrial:
    """Run exactly once and retain the checked record after the container exits."""
    safe_case_id = _safe_failure_id(packet.case_id, key)
    safe_trial_id = _safe_failure_id(trial_id, key)
    try:
        if evidence.image_id is None or not _IMAGE_ID.fullmatch(evidence.image_id):
            raise ValueError("container image identity is required")
        if source_digest() != evidence.source_digest:
            raise ValueError("container build source changed")
        if _image_id(evidence.image) != evidence.image_id:
            raise ValueError("container image identity changed")
        payload = encode_input(packet, rate_card, trial_id, key)
        result = subprocess.run(
            [*_RUN_FLAGS, evidence.image_id],
            input=payload,
            check=False,
            capture_output=True,
            env=_docker_environment(),
        )
        try:
            record = _parse_stdout(result.stdout, packet, trial_id, key)
            if result.returncode != record["exit_code"]:
                record = _mark_infrastructure_failure(record)
        except Exception:
            record = failure_record(safe_case_id, safe_trial_id)
    except Exception:
        record = failure_record(safe_case_id, safe_trial_id)
    record = dict(record)
    output = record.get("output")
    if type(output) is dict:
        output = dict(output)
        output["container_execution"] = _execution_evidence(evidence, key)
        record["output"] = output
    write_raw_artifact(artifact_root, record)
    return ContainerTrial(record=record, evidence=evidence)


__all__ = [
    "ContainerEvidence",
    "ContainerTrial",
    "build_image",
    "run_container_trial",
    "source_digest",
]
