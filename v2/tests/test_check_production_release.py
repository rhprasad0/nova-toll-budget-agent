# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
import hashlib
import importlib.util
import json
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest


def _module(name: str):
    path = Path(__file__).parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _module("check_production_release.py")
gate = _module("validate_production_plan.py")


def test_stable_tag_rejects_prerelease_suffixes() -> None:
    assert release.TAG.fullmatch("v1.2.3")
    assert not release.TAG.fullmatch("v1.2.3-rc.1")


def test_saved_plan_rejects_valid_looking_wrong_bindings() -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    admission: dict[str, Any] = {
        "release_id": 7,
        "tag": "v1.2.3",
        "candidate": "a" * 40,
        "listener_run": 11,
        "listener_attempt": 1,
        "development_run": 12,
        "development_attempt": 1,
        "development_deployment": 13,
        "evidence_artifact": {"id": 14, "digest": "sha256:" + "b" * 64},
        "bundle_id": 15,
        "bundle_digest": "sha256:" + "c" * 64,
        "schema_versions": {"pricing": "1.3.0", "oracle": "1.14.0"},
        "consumer_run": 16,
        "consumer_attempt": 1,
        "claim_id": 17,
    }
    saved = {
        **admission,
        "schema_version": 1,
        "evidence_digest": admission["evidence_artifact"]["digest"],
        "planner_run": 16,
        "planner_attempt": 1,
        "plan_counts": {},
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state": {
            "lineage": "11111111-1111-1111-1111-111111111111",
            "serial": 1,
            "version_id": "state",
        },
        "saved_plan": {
            "bucket": release.PLAN_BUCKET,
            "key": "plans/release-7-v1.2.3/16/release.tfplan",
            "version_id": "plan",
            "checksum": "A" * 43 + "=",
            "kms_key_arn": release.PLAN_KMS_KEY,
        },
    }
    assert release.validate_saved_plan(saved, admission, now=now) == saved
    for field, value in (("key", "plans/release-8-v1.2.3/16/release.tfplan"),):
        altered = json.loads(json.dumps(saved))
        altered["saved_plan"][field] = value
        with pytest.raises(release.AdmissionError):
            release.validate_saved_plan(altered, admission, now=now)
    expired = json.loads(json.dumps(saved))
    expired["expires_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(release.AdmissionError):
        release.validate_saved_plan(expired, admission, now=now)


def test_claim_rejects_prior_release_or_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = {
        "release_id": 7,
        "tag": "v1.2.3",
        "candidate": "a" * 40,
        "listener_run": 1,
        "listener_attempt": 1,
        "consumer_run": 2,
        "consumer_attempt": 1,
    }
    monkeypatch.setattr(
        release,
        "api",
        lambda *_args, **_kwargs: [{"payload": {"release_id": 8, "tag": "v1.2.3"}}],
    )
    with pytest.raises(release.AdmissionError, match="replay"):
        release.claim(admission)


def test_claim_paginates_before_one_validated_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = {
        "release_id": 7,
        "tag": "v1.2.3",
        "candidate": "a" * 40,
        "listener_run": 1,
        "listener_attempt": 1,
        "consumer_run": 2,
        "consumer_attempt": 1,
    }
    calls: list[str] = []

    def api(method: str, path: str, payload: object = None) -> object:
        calls.append(path)
        if method == "GET":
            return [{}] * 100 if path.endswith("page=1") else []
        assert isinstance(payload, dict)
        assert payload == {
            "ref": "a" * 40,
            "environment": release.PRODUCTION_ENVIRONMENT,
            "task": "production-release-plan",
            "auto_merge": False,
            "required_contexts": [],
            "payload": {
                "release_id": 7,
                "tag": "v1.2.3",
                "candidate": "a" * 40,
                "listener_run": 1,
                "listener_attempt": 1,
                "consumer_run": 2,
                "consumer_attempt": 1,
            },
        }
        return {
            "id": 9,
            "sha": "a" * 40,
            "environment": release.PRODUCTION_ENVIRONMENT,
            "task": "production-release-plan",
            "payload": payload["payload"],
        }

    monkeypatch.setattr(release, "api", api)
    assert release.claim(admission)["claim_id"] == 9
    assert calls[:2] == [
        "deployments?environment=production-release&per_page=100&page=1",
        "deployments?environment=production-release&per_page=100&page=2",
    ]


@pytest.mark.parametrize(
    "field,value",
    [("head_branch", "main"), ("head_repository", {"full_name": "evil/fork"})],
)
def test_listener_event_rejects_wrong_tag_ref_or_head_repository(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    run = {
        "repository": {"full_name": release.REPOSITORY},
        "path": release.LISTENER_WORKFLOW + "@main",
        "event": "release",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
        "head_branch": "v1.2.3",
        "head_repository": {"full_name": release.REPOSITORY},
    }
    run[field] = value
    monkeypatch.setattr(release, "_run", lambda _run: run)
    monkeypatch.setattr(release, "_artifacts", lambda *_args: {"id": 1})
    monkeypatch.setattr(
        release,
        "_single_json",
        lambda *_args: {
            "action": "published",
            "repository": {"full_name": release.REPOSITORY},
            "release": {"tag_name": "v1.2.3"},
        },
    )
    with pytest.raises(release.AdmissionError, match="provenance"):
        release._listener_event(1)


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("missing", "ambiguous"),
        ("duplicate", "ambiguous"),
        ("malformed", "expired"),
        ("expired", "expired"),
        ("wrong-metadata", "provenance"),
    ],
)
def test_artifacts_reject_missing_ambiguous_expired_and_wrong_metadata(
    monkeypatch: pytest.MonkeyPatch, kind: str, message: str
) -> None:
    artifact = {
        "id": 9,
        "name": "evidence",
        "digest": "sha256:" + "a" * 64,
        "expired": False,
        "expires_at": "2999-01-01T00:00:00Z",
        "workflow_run": {"id": 7},
    }
    values: list[object] = [artifact]
    if kind == "missing":
        values = []
    elif kind == "duplicate":
        values = [artifact, dict(artifact, id=10)]
    elif kind == "malformed":
        artifact["expires_at"] = "not-a-timestamp"
    elif kind == "expired":
        artifact["expires_at"] = "2000-01-01T00:00:00Z"
    elif kind == "wrong-metadata":
        artifact["workflow_run"] = {"id": 8}

    monkeypatch.setattr(
        release,
        "api",
        lambda *_args, **_kwargs: {"artifacts": values},
    )
    with pytest.raises(release.AdmissionError, match=message):
        release._artifacts(7, "evidence")


def test_admission_accepts_a_current_full_development_rerun(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    candidate = "a" * 40
    event = tmp_path / "event.json"
    event.write_text('{"workflow_run":{"id":11}}')
    monkeypatch.setattr(
        release,
        "_listener_event",
        lambda _run: (
            {"id": 11, "head_sha": candidate},
            {"id": 7, "tag_name": "v1.2.3", "draft": False, "prerelease": False},
        ),
    )
    monkeypatch.setattr(release, "_release", lambda _value: (7, "v1.2.3", candidate))
    monkeypatch.setattr(
        release,
        "_run",
        lambda _run: {
            "repository": {"full_name": release.REPOSITORY},
            "path": ".github/workflows/v2-production-plan.yml@main",
            "event": "workflow_run",
            "run_attempt": 1,
            "status": "in_progress",
            "conclusion": None,
        },
    )
    evidence = {
        "deployment_id": 9,
        "artifact_id": 10,
        "artifact_digest": "sha256:" + "b" * 64,
    }
    monkeypatch.setattr(
        release,
        "_development",
        lambda _candidate: (
            {"id": 12, "run_attempt": 2},
            evidence,
            {"pricing": "1.3.0", "oracle": "1.14.0"},
        ),
    )
    monkeypatch.setattr(
        release, "_artifacts", lambda *_args: {"id": 13, "digest": "sha256:" + "c" * 64}
    )
    admitted = release.admit(event, 11, 14, 1)
    assert admitted["candidate"] == candidate
    assert admitted["development_attempt"] == 2


def test_development_checks_current_attempt_evidence_status_and_bundle_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    candidate = "a" * 40
    evidence = {
        "schema_version": 1,
        "repository": release.REPOSITORY,
        "environment": "development-release",
        "commit": candidate,
        "deployment_id": 9,
        "run_id": 12,
        "attempt": 2,
        "artifact_id": 10,
        "artifact_digest": "sha256:" + "b" * 64,
        "schema_versions": {
            "declared": {"pricing": "1.3.0", "oracle": "1.14.0"},
            "installed": {"pricing": "1.3.0", "oracle": "1.14.0"},
        },
        "readiness": "success",
    }
    archive = tmp_path / "evidence.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("development-release-evidence.json", json.dumps(evidence))
    artifact = {
        "id": 13,
        "name": "v2-development-evidence-12-2",
        "digest": "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest(),
        "expired": False,
        "expires_at": "2999-01-01T00:00:00Z",
        "workflow_run": {"id": 12},
    }
    bundle = {
        "id": 10,
        "name": "v2-development-release-" + candidate,
        "digest": evidence["artifact_digest"],
        "expired": False,
        "expires_at": "2999-01-01T00:00:00Z",
        "workflow_run": {"id": 12},
    }

    def download(_identifier: int, destination: Path) -> None:
        destination.write_bytes(archive.read_bytes())

    def api(_method: str, path: str, _payload: object = None) -> object:
        if path.startswith("actions/runs?event="):
            return {
                "workflow_runs": [
                    {
                        "id": 12,
                        "repository": {"full_name": release.REPOSITORY},
                        "path": release.DEVELOPMENT_WORKFLOW + "@main",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                        "head_branch": "main",
                        "head_sha": candidate,
                        "run_attempt": 2,
                    }
                ]
            }
        if path == "actions/runs/12":
            return {
                "id": 12,
                "repository": {"full_name": release.REPOSITORY},
                "path": release.DEVELOPMENT_WORKFLOW + "@main",
                "event": "push",
                "status": "completed",
                "conclusion": "success",
                "head_branch": "main",
                "head_sha": candidate,
                "run_attempt": 2,
            }
        if path.startswith("actions/runs/12/artifacts"):
            return {"artifacts": [artifact, bundle]}
        if path == "deployments/9":
            return {
                "sha": candidate,
                "environment": "development-release",
                "task": "development-release",
                "payload": {"sha": candidate, "run_id": 12, "created_attempt": 2},
            }
        if path.startswith("deployments/9/statuses"):
            return [
                {
                    "state": "success",
                    "environment": "development-release",
                    "log_url": f"https://github.com/{release.REPOSITORY}/actions/runs/12/attempts/2",
                }
            ]
        raise AssertionError(path)

    monkeypatch.setattr(release, "api", api)
    monkeypatch.setattr(release, "download", download)
    run, actual, versions = release._development(candidate)
    assert run["run_attempt"] == 2
    assert actual == evidence
    assert versions == {"pricing": "1.3.0", "oracle": "1.14.0"}


def _revalidation_admission() -> dict[str, Any]:
    return {
        "release_id": 7,
        "tag": "v1.2.3",
        "candidate": "a" * 40,
        "listener_run": 11,
        "listener_attempt": 1,
        "development_run": 12,
        "development_attempt": 2,
        "development_deployment": 9,
        "evidence_artifact": {"id": 13, "digest": "sha256:" + "c" * 64},
        "bundle_id": 10,
        "bundle_digest": "sha256:" + "b" * 64,
        "schema_versions": {"pricing": "1.3.0", "oracle": "1.14.0"},
        "consumer_run": 14,
        "consumer_attempt": 1,
    }


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("artifact-id", "revalidation"),
        ("artifact-digest", "revalidation"),
        ("development-attempt", "revalidation"),
        ("development-status", "evidence"),
    ],
)
def test_revalidate_rejects_changed_evidence_or_current_development_failure_without_claim(
    monkeypatch: pytest.MonkeyPatch, kind: str, message: str
) -> None:
    admission = _revalidation_admission()
    candidate = admission["candidate"]
    assert isinstance(candidate, str)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        release,
        "_listener_event",
        lambda _run: ({"id": 11, "head_sha": candidate}, {"id": 7}),
    )
    monkeypatch.setattr(release, "_release", lambda _release: (7, "v1.2.3", candidate))

    def development(
        _candidate: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
        if kind == "development-status":
            raise release.AdmissionError("evidence")
        return (
            {"id": 12, "run_attempt": 3 if kind == "development-attempt" else 2},
            {
                "deployment_id": 9,
                "artifact_id": 10,
                "artifact_digest": "sha256:" + "b" * 64,
            },
            {"pricing": "1.3.0", "oracle": "1.14.0"},
        )

    def artifacts(_run: int, _name: str) -> dict[str, Any]:
        return {
            "id": 14 if kind == "artifact-id" else 13,
            "digest": "sha256:" + ("d" if kind == "artifact-digest" else "c") * 64,
        }

    def api(method: str, path: str, _payload: object = None) -> object:
        calls.append((method, path))
        assert method != "POST"
        raise AssertionError(path)

    monkeypatch.setattr(release, "_development", development)
    monkeypatch.setattr(release, "_artifacts", artifacts)
    monkeypatch.setattr(release, "api", api)
    with pytest.raises(release.AdmissionError, match=message):
        release.revalidate(admission)
    assert not calls


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("success", None),
        ("json-payload", None),
        ("consumer-attempt", "replay"),
        ("consumer-provenance", "replay"),
        ("claim-environment", "revalidation"),
        ("claim-task", "revalidation"),
        ("claim-sha", "revalidation"),
        ("claim-payload-id", "revalidation"),
        ("claim-payload-attempt", "revalidation"),
        ("claim-payload-candidate", "revalidation"),
    ],
)
def test_revalidate_binds_current_consumer_and_durable_claim(
    monkeypatch: pytest.MonkeyPatch, kind: str, message: str | None
) -> None:
    admission = _revalidation_admission()
    admission["claim_id"] = 15
    candidate = admission["candidate"]
    assert isinstance(candidate, str)
    required_claim = {
        "release_id": 7,
        "tag": "v1.2.3",
        "candidate": candidate,
        "listener_run": 11,
        "listener_attempt": 1,
        "consumer_run": 14,
        "consumer_attempt": 1,
    }
    consumer: dict[str, Any] = {
        "repository": {"full_name": release.REPOSITORY},
        "path": ".github/workflows/v2-production-plan.yml@refs/heads/main",
        "event": "workflow_run",
        "run_attempt": 1,
        "status": "in_progress",
        "conclusion": None,
    }
    claim: dict[str, Any] = {
        "environment": release.PRODUCTION_ENVIRONMENT,
        "task": "production-release-plan",
        "sha": candidate,
        "payload": required_claim,
    }
    if kind == "consumer-attempt":
        consumer["run_attempt"] = 2
    elif kind == "consumer-provenance":
        consumer["repository"] = {"full_name": "wrong/repository"}
    elif kind == "claim-environment":
        claim["environment"] = "wrong"
    elif kind == "claim-task":
        claim["task"] = "wrong"
    elif kind == "claim-sha":
        claim["sha"] = "b" * 40
    elif kind == "claim-payload-id":
        required_claim["consumer_run"] = 99
    elif kind == "claim-payload-attempt":
        required_claim["consumer_attempt"] = 2
    elif kind == "claim-payload-candidate":
        required_claim["candidate"] = "b" * 40
    if kind == "json-payload":
        claim["payload"] = json.dumps(required_claim)

    monkeypatch.setattr(
        release,
        "_listener_event",
        lambda _run: ({"id": 11, "head_sha": candidate}, {"id": 7}),
    )
    monkeypatch.setattr(release, "_release", lambda _release: (7, "v1.2.3", candidate))
    monkeypatch.setattr(
        release,
        "_development",
        lambda _candidate: (
            {"id": 12, "run_attempt": 2},
            {
                "deployment_id": 9,
                "artifact_id": 10,
                "artifact_digest": "sha256:" + "b" * 64,
            },
            {"pricing": "1.3.0", "oracle": "1.14.0"},
        ),
    )
    monkeypatch.setattr(
        release,
        "_artifacts",
        lambda _run, _name: {"id": 13, "digest": "sha256:" + "c" * 64},
    )
    monkeypatch.setattr(
        release,
        "api",
        lambda _method, path, _payload=None: (
            consumer
            if path == "actions/runs/14"
            else claim
            if path == "deployments/15"
            else (_ for _ in ()).throw(AssertionError(path))
        ),
    )
    if message is None:
        assert release.revalidate(admission) == admission
    else:
        with pytest.raises(release.AdmissionError, match=message):
            release.revalidate(admission)


def test_claim_rejects_failed_prior_claim_without_creating_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def api(method: str, path: str, _payload: object = None) -> object:
        calls.append(f"{method} {path}")
        if method == "GET":
            return [{"payload": {"release_id": 7}, "statuses_url": "failed"}]
        raise AssertionError("claim must not be recreated")

    monkeypatch.setattr(release, "api", api)
    with pytest.raises(release.AdmissionError, match="replay"):
        release.claim(_revalidation_admission())
    assert calls == [
        "GET deployments?environment=production-release&per_page=100&page=1"
    ]


def test_claim_does_not_retry_an_unknown_create_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def api(method: str, path: str, _payload: object = None) -> object:
        calls.append(method)
        if method == "GET":
            return []
        raise release.AdmissionError("api")

    monkeypatch.setattr(release, "api", api)
    with pytest.raises(release.AdmissionError, match="api"):
        release.claim(_revalidation_admission())
    assert calls == ["GET", "POST"]


def _plan(address: str, actions: list[str]) -> dict[str, Any]:
    return {
        "resource_changes": [
            {
                "address": address,
                "mode": "managed",
                "provider_name": "registry.terraform.io/hashicorp/aws",
                "change": {"actions": actions, "after_unknown": {}},
            }
        ],
        "resource_drift": [],
        "output_changes": {},
    }


def test_plan_gate_allows_only_the_two_stateless_replacements(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_api_gateway_deployment" "tollchat" {}\nresource "aws_bedrock_guardrail_version" "tollchat" {}\nresource "aws_s3_bucket" "site" {}\ndata "aws_caller_identity" "current" {}\n'
    )
    assert (
        gate.validate(
            _plan("aws_api_gateway_deployment.tollchat", ["create", "delete"]), tmp_path
        )["replace"]
        == 1
    )
    with pytest.raises(gate.PlanError, match="persistent"):
        gate.validate(_plan("aws_s3_bucket.site", ["delete", "create"]), tmp_path)


def test_plan_gate_admits_real_format_data_addresses(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_s3_bucket" "site" {}\n'
        'data "aws_iam_policy_document" "timed_checks_lambda" {}\n'
    )
    plan = _plan("data.aws_iam_policy_document.timed_checks_lambda", ["read"])
    plan["resource_changes"][0]["mode"] = "data"
    assert gate.validate(plan, tmp_path)["read"] == 1


def test_plan_gate_requires_api_order_and_guardrail_skip_destroy(
    tmp_path: Path,
) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_api_gateway_deployment" "tollchat" {}\n'
        'resource "aws_bedrock_guardrail_version" "tollchat" {}\n'
        'data "aws_caller_identity" "current" {}\n'
    )
    with pytest.raises(gate.PlanError, match="replacement"):
        gate.validate(
            _plan("aws_api_gateway_deployment.tollchat", ["delete", "create"]), tmp_path
        )
    guardrail = _plan("aws_bedrock_guardrail_version.tollchat", ["delete", "create"])
    guardrail["resource_changes"][0]["change"]["after"] = {"skip_destroy": True}
    assert gate.validate(guardrail, tmp_path)["replace"] == 1
    guardrail["resource_changes"][0]["change"]["after"] = {"skip_destroy": False}
    with pytest.raises(gate.PlanError, match="replacement"):
        gate.validate(guardrail, tmp_path)


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("unknown-managed", "managed"),
        ("provider", "provider"),
        ("data-action", "data"),
        ("moved", "moved"),
        ("drift", "shape"),
        ("output", "output"),
        ("delete", "action"),
        ("unknown-shape", "unknown-shape"),
        ("persistent", "persistent"),
        ("replacement", "replacement"),
    ],
)
def test_plan_gate_rejects_the_complete_negative_boundary_matrix(
    tmp_path: Path, kind: str, message: str
) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_api_gateway_deployment" "tollchat" {}\n'
        'resource "aws_bedrock_guardrail_version" "tollchat" {}\n'
        'resource "aws_s3_bucket" "site" {}\n'
        'resource "aws_lambda_function" "worker" {}\n'
        'data "aws_caller_identity" "current" {}\n'
    )
    plan = _plan("aws_api_gateway_deployment.tollchat", ["no-op"])
    item = plan["resource_changes"][0]
    change = item["change"]
    if kind == "unknown-managed":
        item["address"] = "aws_s3_bucket.unknown"
    elif kind == "provider":
        item["provider_name"] = "registry.terraform.io/hashicorp/google"
    elif kind == "data-action":
        item.update(address="aws_caller_identity.current", mode="data")
        change["actions"] = ["create"]
    elif kind == "moved":
        item["previous_address"] = "aws_api_gateway_deployment.old"
    elif kind == "drift":
        plan["resource_drift"] = [{}]
    elif kind == "output":
        plan["output_changes"] = {"secret": {"actions": ["create"]}}
    elif kind == "delete":
        change["actions"] = ["delete"]
    elif kind == "unknown-shape":
        change["after_unknown"] = {"id": "unknown"}
    elif kind == "persistent":
        item["address"] = "aws_s3_bucket.site"
        change["actions"] = ["delete"]
    else:
        item["address"] = "aws_lambda_function.worker"
        change["actions"] = ["create", "delete"]
    with pytest.raises(gate.PlanError, match=message):
        gate.validate(plan, tmp_path)


def test_private_stage_stops_a_multi_command_bundle_function_at_first_failure(
    tmp_path: Path,
) -> None:
    helper = Path(__file__).parents[1] / "scripts" / "run_private_stage.sh"
    marker = tmp_path / "copied"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; verify_bundle() { false || return; touch "$2"; }; run_private_stage artifact-download "$3" "$4" verify_bundle',
            "bash",
            str(helper),
            str(marker),
            str(tmp_path / "out"),
            str(tmp_path / "err"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not marker.exists()
    assert result.stderr.count("stage=artifact-download status=fail") == 1
