#!/usr/bin/env python3
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
"""Fail-closed admission and replay claim for a production release plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

REPOSITORY = "rhprasad0/nova-toll-budget-agent"
LISTENER_WORKFLOW = ".github/workflows/v2-production-release.yml"
DEVELOPMENT_WORKFLOW = ".github/workflows/v2-development-delivery.yml"
PRODUCTION_ENVIRONMENT = "production-release"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
MAX_BUNDLE_MEMBER_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+\Z")
PLAN_BUCKET = "nova-toll-tfstate-920534282028"
PLAN_KMS_KEY = (
    "arn:aws:kms:us-east-1:920534282028:key/8fc1450b-0b5c-4afe-8c0a-cb150aab5da7"
)
PLAN_MAX_AGE = timedelta(hours=24)


class AdmissionError(ValueError):
    """A sanitized, fail-closed release admission error."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AdmissionError("malformed")
        value[key] = item
    return value


def _load(raw: bytes) -> object:
    if len(raw) > MAX_JSON_BYTES:
        raise AdmissionError("oversized")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeDecodeError, json.JSONDecodeError, AdmissionError) as error:
        raise AdmissionError("malformed") from error


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdmissionError("malformed")
    return cast(dict[str, Any], value)


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise AdmissionError("malformed")
    text = str(value)
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise AdmissionError("malformed")
    return int(text)


def _sha(value: object) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise AdmissionError("malformed")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise AdmissionError("malformed")
    return value


def _version(value: object) -> str:
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise AdmissionError("malformed")
    return value


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> object:
    command = ["gh", "api", "--method", method, f"repos/{REPOSITORY}/{path}"]
    if payload is not None:
        command.extend(["--input", "-"])
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AdmissionError("api") from error
    if result.returncode or len(result.stdout.encode()) > 4 * 1024 * 1024:
        raise AdmissionError("api")
    try:
        return json.loads(result.stdout, object_pairs_hook=_object)
    except (TypeError, json.JSONDecodeError, AdmissionError) as error:
        raise AdmissionError("malformed") from error


def download(artifact_id: int, destination: Path) -> None:
    try:
        with destination.open("xb") as output:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "--method",
                    "GET",
                    f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip",
                ],
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise AdmissionError("download") from error
    if result.returncode or not destination.is_file() or destination.is_symlink():
        raise AdmissionError("download")
    if destination.stat().st_size > MAX_ARCHIVE_BYTES:
        raise AdmissionError("oversized")


def _run(run_id: int) -> dict[str, Any]:
    return _mapping(api("GET", f"actions/runs/{run_id}"))


def _workflow(run: dict[str, Any], path: str, event: str, attempt: int | None) -> None:
    repository = _mapping(run.get("repository"))
    if (
        repository.get("full_name") != REPOSITORY
        or run.get("path", "").split("@", 1)[0] != path
        or run.get("event") != event
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or (attempt is not None and _positive(run.get("run_attempt")) != attempt)
    ):
        raise AdmissionError("provenance")


def _artifacts(run_id: int, name: str) -> dict[str, Any]:
    found: list[dict[str, Any]] = []
    page = 1
    while True:
        response = _mapping(
            api("GET", f"actions/runs/{run_id}/artifacts?per_page=100&page={page}")
        )
        values = response.get("artifacts")
        if not isinstance(values, list):
            raise AdmissionError("malformed")
        for value in values:
            artifact = _mapping(value)
            if artifact.get("name") == name:
                found.append(artifact)
        if len(values) < 100:
            break
        page += 1
        if page > 1000:
            raise AdmissionError("ambiguous")
    if len(found) != 1:
        raise AdmissionError("ambiguous")
    artifact = found[0]
    expires = artifact.get("expires_at")
    if artifact.get("expired") is not False or not isinstance(expires, str):
        raise AdmissionError("expired")
    try:
        expires_at = datetime.strptime(expires, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError as error:
        raise AdmissionError("expired") from error
    if expires_at <= datetime.now(UTC):
        raise AdmissionError("expired")
    workflow_run = _mapping(artifact.get("workflow_run"))
    if _positive(workflow_run.get("id")) != run_id:
        raise AdmissionError("provenance")
    _positive(artifact.get("id"))
    _digest(artifact.get("digest"))
    return artifact


def _single_json(artifact: dict[str, Any], name: str) -> dict[str, Any]:
    artifact_id = _positive(artifact.get("id"))
    with tempfile.TemporaryDirectory(prefix="production-release-") as temporary:
        archive = Path(temporary) / "artifact.zip"
        download(artifact_id, archive)
        digest = (
            "sha256:" + hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
        )
        if digest != _digest(artifact.get("digest")):
            raise AdmissionError("digest")
        try:
            with zipfile.ZipFile(archive) as zipped:
                infos = zipped.infolist()
                if (
                    len(infos) != 1
                    or infos[0].filename != name
                    or infos[0].is_dir()
                    or infos[0].file_size > MAX_JSON_BYTES
                ):
                    raise AdmissionError("malformed")
                return _mapping(_load(zipped.read(infos[0])))
        except zipfile.BadZipFile as error:
            raise AdmissionError("malformed") from error


def _listener_event(listener_run: int) -> tuple[dict[str, Any], dict[str, Any]]:
    run = _run(listener_run)
    _workflow(run, LISTENER_WORKFLOW, "release", 1)
    artifact = _artifacts(listener_run, f"v2-production-release-{listener_run}-1")
    event = _single_json(artifact, "release-event.json")
    if set(event) != {"action", "repository", "release"}:
        raise AdmissionError("malformed")
    release = _mapping(event.get("release"))
    if (
        event.get("action") != "published"
        or _mapping(event.get("repository")).get("full_name") != REPOSITORY
    ):
        raise AdmissionError("provenance")
    tag = release.get("tag_name")
    if (
        not isinstance(tag, str)
        or run.get("head_branch") != tag
        or _mapping(run.get("head_repository")).get("full_name") != REPOSITORY
    ):
        raise AdmissionError("provenance")
    return run, release


def _peel_tag(tag: str) -> str:
    ref = _mapping(api("GET", f"git/ref/tags/{tag}"))
    object_value = _mapping(ref.get("object"))
    kind = object_value.get("type")
    sha = _sha(object_value.get("sha"))
    if kind == "commit":
        return sha
    if kind != "tag":
        raise AdmissionError("provenance")
    tag_object = _mapping(api("GET", f"git/tags/{sha}"))
    target = _mapping(tag_object.get("object"))
    if target.get("type") != "commit":
        raise AdmissionError("provenance")
    return _sha(target.get("sha"))


def _release(release: dict[str, Any]) -> tuple[int, str, str]:
    release_id = _positive(release.get("id"))
    tag = release.get("tag_name")
    if (
        not isinstance(tag, str)
        or not TAG.fullmatch(tag)
        or release.get("draft") is not False
        or release.get("prerelease") is not False
    ):
        raise AdmissionError("release")
    current = _mapping(api("GET", f"releases/{release_id}"))
    if (
        _positive(current.get("id")) != release_id
        or current.get("tag_name") != tag
        or current.get("draft") is not False
        or current.get("prerelease") is not False
        or current.get("published_at") is None
    ):
        raise AdmissionError("release")
    return release_id, tag, _peel_tag(tag)


def _development(
    candidate: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    response = _mapping(
        api(
            "GET",
            f"actions/runs?event=push&branch=main&head_sha={candidate}&per_page=100",
        )
    )
    values = response.get("workflow_runs")
    if not isinstance(values, list):
        raise AdmissionError("malformed")
    runs = [_mapping(value) for value in values]
    matches = [
        run
        for run in runs
        if run.get("path", "").split("@", 1)[0] == DEVELOPMENT_WORKFLOW
    ]
    if len(matches) != 1:
        raise AdmissionError("ambiguous")
    run = matches[0]
    _workflow(run, DEVELOPMENT_WORKFLOW, "push", None)
    if run.get("head_branch") != "main" or _sha(run.get("head_sha")) != candidate:
        raise AdmissionError("provenance")
    run_id, attempt = _positive(run.get("id")), _positive(run.get("run_attempt"))
    current = _run(run_id)
    _workflow(current, DEVELOPMENT_WORKFLOW, "push", attempt)
    if (
        current.get("head_branch") != "main"
        or _sha(current.get("head_sha")) != candidate
    ):
        raise AdmissionError("provenance")
    evidence_artifact = _artifacts(
        run_id, f"v2-development-evidence-{run_id}-{attempt}"
    )
    evidence = _single_json(evidence_artifact, "development-release-evidence.json")
    expected = {
        "schema_version",
        "repository",
        "environment",
        "commit",
        "deployment_id",
        "run_id",
        "attempt",
        "artifact_id",
        "artifact_digest",
        "schema_versions",
        "readiness",
    }
    if (
        set(evidence) != expected
        or evidence.get("schema_version") != 1
        or evidence.get("repository") != REPOSITORY
        or evidence.get("environment") != "development-release"
        or _sha(evidence.get("commit")) != candidate
        or _positive(evidence.get("run_id")) != run_id
        or _positive(evidence.get("attempt")) != attempt
        or evidence.get("readiness") != "success"
    ):
        raise AdmissionError("evidence")
    schemas = _mapping(evidence.get("schema_versions"))
    declared, installed = (
        _mapping(schemas.get("declared")),
        _mapping(schemas.get("installed")),
    )
    if (
        set(schemas) != {"declared", "installed"}
        or set(declared) != {"pricing", "oracle"}
        or declared != installed
    ):
        raise AdmissionError("schema")
    versions = {key: _version(value) for key, value in declared.items()}
    deployment = _mapping(
        api("GET", f"deployments/{_positive(evidence.get('deployment_id'))}")
    )
    payload = deployment.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload, object_pairs_hook=_object)
        except (json.JSONDecodeError, AdmissionError) as error:
            raise AdmissionError("evidence") from error
    payload = _mapping(payload)
    if (
        deployment.get("sha") != candidate
        or deployment.get("environment") != "development-release"
        or deployment.get("task") != "development-release"
        or payload.get("sha") != candidate
        or _positive(payload.get("run_id")) != run_id
        or not 1 <= _positive(payload.get("created_attempt")) <= attempt
    ):
        raise AdmissionError("evidence")
    statuses = api(
        "GET",
        f"deployments/{_positive(evidence.get('deployment_id'))}/statuses?per_page=100",
    )
    if not isinstance(statuses, list) or not statuses:
        raise AdmissionError("evidence")
    latest = _mapping(statuses[0])
    if (
        latest.get("state") != "success"
        or latest.get("environment") != "development-release"
        or latest.get("log_url")
        != f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}"
    ):
        raise AdmissionError("evidence")
    bundle_id, bundle_digest = (
        _positive(evidence.get("artifact_id")),
        _digest(evidence.get("artifact_digest")),
    )
    bundle = _artifacts(run_id, f"v2-development-release-{candidate}")
    if (
        _positive(bundle.get("id")) != bundle_id
        or _digest(bundle.get("digest")) != bundle_digest
    ):
        raise AdmissionError("evidence")
    return run, evidence, {"pricing": versions["pricing"], "oracle": versions["oracle"]}


def admit(
    event_file: Path, listener_run: int, consumer_run: int, consumer_attempt: int
) -> dict[str, Any]:
    listener, release = _listener_event(listener_run)
    event = _mapping(_load(event_file.read_bytes()))
    workflow_run = _mapping(event.get("workflow_run"))
    if _positive(workflow_run.get("id")) != listener_run:
        raise AdmissionError("provenance")
    release_id, tag, candidate = _release(release)
    if _sha(listener.get("head_sha")) != candidate:
        raise AdmissionError("provenance")
    consumer = _run(consumer_run)
    _consumer(consumer, consumer_attempt)
    development, evidence, versions = _development(candidate)
    return {
        "release_id": release_id,
        "tag": tag,
        "candidate": candidate,
        "listener_run": listener_run,
        "listener_attempt": 1,
        "development_run": _positive(development.get("id")),
        "development_attempt": _positive(development.get("run_attempt")),
        "development_deployment": _positive(evidence.get("deployment_id")),
        "evidence_artifact": _artifacts(
            _positive(development.get("id")),
            f"v2-development-evidence-{_positive(development.get('id'))}-{_positive(development.get('run_attempt'))}",
        ),
        "bundle_id": _positive(evidence.get("artifact_id")),
        "bundle_digest": _digest(evidence.get("artifact_digest")),
        "schema_versions": versions,
        "consumer_run": consumer_run,
        "consumer_attempt": consumer_attempt,
    }


def _consumer(consumer: dict[str, Any], attempt: int) -> None:
    repository = _mapping(consumer.get("repository"))
    if (
        repository.get("full_name") != REPOSITORY
        or consumer.get("path", "").split("@", 1)[0]
        != ".github/workflows/v2-production-plan.yml"
        or consumer.get("event") != "workflow_run"
        or _positive(consumer.get("run_attempt")) != attempt
        or consumer.get("status") not in {"queued", "in_progress"}
        or consumer.get("conclusion") is not None
        or attempt != 1
    ):
        raise AdmissionError("replay")


def claim(admission: dict[str, Any]) -> dict[str, Any]:
    release_id, tag, candidate = (
        _positive(admission.get("release_id")),
        admission.get("tag"),
        _sha(admission.get("candidate")),
    )
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise AdmissionError("malformed")
    page = 1
    while True:
        values = api(
            "GET",
            f"deployments?environment={PRODUCTION_ENVIRONMENT}&per_page=100&page={page}",
        )
        if not isinstance(values, list):
            raise AdmissionError("malformed")
        for value in values:
            deployment = _mapping(value)
            payload = deployment.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload, object_pairs_hook=_object)
                except (json.JSONDecodeError, AdmissionError) as error:
                    raise AdmissionError("malformed") from error
            if isinstance(payload, dict) and (
                payload.get("release_id") == release_id or payload.get("tag") == tag
            ):
                raise AdmissionError("replay")
        if len(values) < 100:
            break
        page += 1
        if page > 1000:
            raise AdmissionError("ambiguous")
    payload = {
        "release_id": release_id,
        "tag": tag,
        "candidate": candidate,
        "listener_run": _positive(admission.get("listener_run")),
        "listener_attempt": _positive(admission.get("listener_attempt")),
        "consumer_run": _positive(admission.get("consumer_run")),
        "consumer_attempt": _positive(admission.get("consumer_attempt")),
    }
    created = _mapping(
        api(
            "POST",
            "deployments",
            {
                "ref": candidate,
                "environment": PRODUCTION_ENVIRONMENT,
                "task": "production-release-plan",
                "auto_merge": False,
                "required_contexts": [],
                "payload": payload,
            },
        )
    )
    created_payload = created.get("payload")
    if isinstance(created_payload, str):
        try:
            created_payload = json.loads(created_payload, object_pairs_hook=_object)
        except (json.JSONDecodeError, AdmissionError) as error:
            raise AdmissionError("claim") from error
    if (
        _sha(created.get("sha")) != candidate
        or created.get("environment") != PRODUCTION_ENVIRONMENT
        or created.get("task") != "production-release-plan"
        or _mapping(created_payload) != payload
    ):
        raise AdmissionError("claim")
    admission["claim_id"] = _positive(created.get("id"))
    return admission


def revalidate(admission: dict[str, Any]) -> dict[str, Any]:
    """Repeat mutable GitHub checks immediately before production OIDC."""
    listener, release = _listener_event(_positive(admission.get("listener_run")))
    release_id, tag, candidate = _release(release)
    if _sha(listener.get("head_sha")) != candidate:
        raise AdmissionError("provenance")
    if admission.get("listener_attempt") != 1:
        raise AdmissionError("revalidation")
    development, evidence, versions = _development(candidate)
    development_run = _positive(development.get("id"))
    development_attempt = _positive(development.get("run_attempt"))
    evidence_artifact = _artifacts(
        development_run,
        f"v2-development-evidence-{development_run}-{development_attempt}",
    )
    recorded_artifact = _mapping(admission.get("evidence_artifact"))
    if _positive(recorded_artifact.get("id")) != _positive(
        evidence_artifact.get("id")
    ) or _digest(recorded_artifact.get("digest")) != _digest(
        evidence_artifact.get("digest")
    ):
        raise AdmissionError("revalidation")
    expected = {
        "release_id": release_id,
        "tag": tag,
        "candidate": candidate,
        "listener_run": _positive(listener.get("id")),
        "listener_attempt": 1,
        "development_run": development_run,
        "development_attempt": development_attempt,
        "development_deployment": _positive(evidence.get("deployment_id")),
        "bundle_id": _positive(evidence.get("artifact_id")),
        "bundle_digest": _digest(evidence.get("artifact_digest")),
        "schema_versions": versions,
    }
    for key, value in expected.items():
        if admission.get(key) != value:
            raise AdmissionError("revalidation")
    _consumer(
        _run(_positive(admission.get("consumer_run"))),
        _positive(admission.get("consumer_attempt")),
    )
    claim = _mapping(api("GET", f"deployments/{_positive(admission.get('claim_id'))}"))
    claim_payload = claim.get("payload")
    if isinstance(claim_payload, str):
        try:
            claim_payload = json.loads(claim_payload, object_pairs_hook=_object)
        except (json.JSONDecodeError, AdmissionError) as error:
            raise AdmissionError("revalidation") from error
    required_claim = {
        "release_id": release_id,
        "tag": tag,
        "candidate": candidate,
        "listener_run": _positive(admission.get("listener_run")),
        "listener_attempt": 1,
        "consumer_run": _positive(admission.get("consumer_run")),
        "consumer_attempt": _positive(admission.get("consumer_attempt")),
    }
    if (
        claim.get("environment") != PRODUCTION_ENVIRONMENT
        or claim.get("task") != "production-release-plan"
        or _sha(claim.get("sha")) != candidate
        or _mapping(claim_payload) != required_claim
    ):
        raise AdmissionError("revalidation")
    return admission


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise AdmissionError("malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AdmissionError("malformed") from error
    if parsed.tzinfo is None:
        raise AdmissionError("malformed")
    return parsed.astimezone(UTC)


def validate_saved_plan(
    saved: dict[str, Any], admission: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Accept only the bounded plan description passed between protected jobs."""
    expected = {
        "schema_version",
        "release_id",
        "tag",
        "candidate",
        "bundle_id",
        "bundle_digest",
        "listener_run",
        "listener_attempt",
        "development_run",
        "development_attempt",
        "development_deployment",
        "evidence_artifact",
        "evidence_digest",
        "consumer_run",
        "consumer_attempt",
        "claim_id",
        "planner_run",
        "planner_attempt",
        "schema_versions",
        "plan_counts",
        "saved_plan",
        "state",
        "created_at",
        "expires_at",
    }
    if set(saved) != expected or saved.get("schema_version") != 1:
        raise AdmissionError("malformed")
    for key in expected - {
        "schema_version",
        "evidence_artifact",
        "planner_run",
        "planner_attempt",
        "plan_counts",
        "saved_plan",
        "state",
        "created_at",
        "expires_at",
        "evidence_digest",
    }:
        if saved.get(key) != admission.get(key):
            raise AdmissionError("binding")
    saved_artifact = _mapping(saved["evidence_artifact"])
    admission_artifact = _mapping(admission["evidence_artifact"])
    if (
        set(saved_artifact) != {"id", "digest"}
        or _positive(saved_artifact.get("id"))
        != _positive(admission_artifact.get("id"))
        or _digest(saved_artifact.get("digest"))
        != _digest(admission_artifact.get("digest"))
    ):
        raise AdmissionError("binding")
    _positive(saved.get("planner_run"))
    _positive(saved.get("planner_attempt"))
    if (
        _positive(saved["planner_run"]) != _positive(admission["consumer_run"])
        or _positive(saved["planner_attempt"])
        != _positive(admission["consumer_attempt"])
        or saved.get("evidence_digest")
        != _mapping(admission["evidence_artifact"]).get("digest")
    ):
        raise AdmissionError("binding")
    if not isinstance(saved["plan_counts"], dict):
        raise AdmissionError("malformed")
    plan, state = _mapping(saved["saved_plan"]), _mapping(saved["state"])
    if set(plan) != {"bucket", "key", "version_id", "checksum", "kms_key_arn"} or set(
        state
    ) != {"lineage", "serial", "version_id"}:
        raise AdmissionError("malformed")
    if (
        plan.get("bucket") != PLAN_BUCKET
        or plan.get("kms_key_arn") != PLAN_KMS_KEY
        or not isinstance(plan.get("key"), str)
        or not re.fullmatch(
            r"plans/release-[1-9][0-9]*-v[0-9]+(?:\.[0-9]+){2}/[1-9][0-9]*/release\.tfplan",
            plan["key"],
        )
        or not isinstance(plan.get("version_id"), str)
        or not plan["version_id"]
        or not isinstance(plan.get("checksum"), str)
        or not re.fullmatch(r"[A-Za-z0-9+/]{43}=", plan["checksum"])
        or not isinstance(state.get("lineage"), str)
        or not re.fullmatch(r"[0-9a-f-]{36}", state["lineage"])
        or _positive(state.get("serial")) < 0
        or not isinstance(state.get("version_id"), str)
        or not state["version_id"]
        or plan["key"]
        != f"plans/release-{_positive(saved['release_id'])}-{saved['tag']}/{_positive(saved['planner_run'])}/release.tfplan"
    ):
        raise AdmissionError("malformed")
    created, expires = _timestamp(saved["created_at"]), _timestamp(saved["expires_at"])
    now = datetime.now(UTC) if now is None else now
    if created > now or expires != created + PLAN_MAX_AGE or expires <= now:
        raise AdmissionError("expired")
    return saved


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    admission = commands.add_parser("admit")
    admission.add_argument("--event-file", type=Path, required=True)
    admission.add_argument("--listener-run", type=int, required=True)
    admission.add_argument("--consumer-run", type=int, required=True)
    admission.add_argument("--consumer-attempt", type=int, required=True)
    admission.add_argument("--output", type=Path, required=True)
    claim_command = commands.add_parser("claim")
    claim_command.add_argument("--admission", type=Path, required=True)
    claim_command.add_argument("--output", type=Path, required=True)
    revalidate_command = commands.add_parser("revalidate")
    revalidate_command.add_argument("--admission", type=Path, required=True)
    revalidate_command.add_argument("--output", type=Path, required=True)
    saved_plan = commands.add_parser("validate-saved-plan")
    saved_plan.add_argument("--admission", type=Path, required=True)
    saved_plan.add_argument("--saved-plan", type=Path, required=True)
    saved_plan.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "admit":
            result = admit(
                args.event_file,
                args.listener_run,
                args.consumer_run,
                args.consumer_attempt,
            )
        elif args.command == "claim":
            result = claim(_mapping(_load(args.admission.read_bytes())))
        elif args.command == "revalidate":
            result = revalidate(_mapping(_load(args.admission.read_bytes())))
        else:
            result = validate_saved_plan(
                _mapping(_load(args.saved_plan.read_bytes())),
                _mapping(_load(args.admission.read_bytes())),
            )
        args.output.write_text(
            json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except (AdmissionError, OSError, ValueError):
        print("production release admission: rejected", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
