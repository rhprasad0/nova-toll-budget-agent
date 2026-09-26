"""Recovery remains bound to its original claim after GitHub artifacts expire."""

import hashlib
import json
from pathlib import Path
from typing import Any, NoReturn

import pytest

from scripts import check_production_release as archive


@pytest.mark.parametrize("moved", [False, True])
def test_recovery_claim_needs_no_github_artifact(
    monkeypatch: pytest.MonkeyPatch, moved: bool
) -> None:
    release = archive
    sha = "a" * 40
    payload = {
        "release_id": 7,
        "tag": "v1.2.3",
        "candidate": sha,
        "listener_run": 11,
        "listener_attempt": 1,
        "consumer_run": 14,
        "consumer_attempt": 1,
    }
    repository = {"full_name": release.REPOSITORY}
    published = {
        "id": 7,
        "tag_name": "v1.2.3",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-09-01T00:00:00Z",
    }
    responses = {
        "deployments/99": {
            "sha": sha,
            "environment": "production-release",
            "task": "production-release-plan",
            "payload": payload,
        },
        "actions/runs/11": {
            "id": 11,
            "head_sha": sha,
            "head_branch": "v1.2.3",
            "repository": repository,
            "head_repository": repository,
            "path": release.LISTENER_WORKFLOW,
            "event": "release",
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
        },
        "actions/runs/14": {
            "repository": repository,
            "path": ".github/workflows/v2-production-plan.yml",
            "event": "workflow_run",
            "head_branch": "main",
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "failure",
        },
        "releases/7": published,
        "git/ref/tags/v1.2.3": {
            "object": {"type": "commit", "sha": "b" * 40 if moved else sha}
        },
    }

    def api(method: str, path: str) -> object:
        assert method == "GET"
        assert path in responses, "recovery attempted to read an expiring artifact"
        return responses[path]

    monkeypatch.setattr(release, "api", api)
    if moved:
        with pytest.raises(release.AdmissionError):
            release.recovery_admission(
                "99", "original-record", "d" * 64, claim_only=True
            )
    else:
        result = release.recovery_admission(
            "99", "original-record", "d" * 64, claim_only=True
        )
        assert result["candidate"] == sha and result["original_claim"] == payload


@pytest.mark.parametrize(
    "tamper", [None, "claim", "bundle", "record", "version", "oversized"]
)
def test_save_restore_uses_versioned_original_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str | None
) -> None:
    bundle = tmp_path / "input.zip"
    bundle.write_bytes(b"original verified GitHub archive")
    original = {
        "release_id": 7,
        "tag": "v1.2.3",
        "candidate": "a" * 40,
        "listener_run": 11,
        "listener_attempt": 1,
        "consumer_run": 14,
        "consumer_attempt": 1,
    }
    admission: dict[str, Any] = {
        **original,
        "claim_id": 99,
        "bundle_id": 42,
        "bundle_digest": "sha256:" + hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "schema_versions": {"pricing": "1.4.0", "oracle": "1.15.1"},
    }
    claim = {
        "claim_id": 99,
        "candidate": "a" * 40,
        "record_version": "original-record",
        "expected_state_sha256": "d" * 64,
        "original_claim": original,
    }
    stored: dict[str, bytes] = {}

    def upload(
        path: Path, _bucket: str, key: str, _type: str, _cache: str
    ) -> dict[str, str]:
        assert key not in stored
        stored[key] = path.read_bytes()
        return {"VersionId": "pinned-version"}

    def aws(*args: str) -> dict[str, Any]:
        assert args[0] == "s3api"
        key = args[args.index("--key") + 1]
        assert args[args.index("--expected-bucket-owner") + 1] == "920534282028"
        if "--version-id" in args:
            assert args[args.index("--version-id") + 1] == "pinned-version"
        if args[1] == "get-object":
            assert "--version-id" in args
            Path(args[-1]).write_bytes(stored[key])
        return {"VersionId": "pinned-version", "ContentLength": len(stored[key])}

    def load(
        _directory: Path, release: str, identifier: str, version: str
    ) -> dict[str, Any]:
        assert (release, identifier, version) == ("a" * 40, "99", "original-record")
        return {
            "bundle": {
                "id": "42",
                "digest": "wrong" if tamper == "record" else admission["bundle_digest"],
            }
        }

    monkeypatch.setattr(archive.delivery, "account", "920534282028")
    monkeypatch.setattr(
        archive.delivery, "artifact_bucket", "nova-toll-agentcore-920534282028"
    )
    monkeypatch.setattr(archive.delivery, "upload", upload)
    monkeypatch.setattr(archive.delivery, "aws", aws)
    monkeypatch.setattr(archive.delivery, "load_recovery", load)

    # A modern archived release must never require any GitHub artifact.
    def unavailable(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("GitHub artifact access after archival")

    monkeypatch.setattr(archive, "download", unavailable)
    monkeypatch.setattr(archive, "recovery_admission", unavailable)
    archive.save_recovery_archive(admission, bundle, tmp_path)
    key = archive.recovery_archive_prefix(admission)
    manifest = json.loads(stored[key + "archive.json"])
    if tamper == "claim":
        manifest["admission"]["consumer_run"] = 100
    if tamper == "version":
        manifest["version_id"] = "null"
    if tamper == "bundle":
        stored[key + "bundle.zip"] = b"substituted bundle"
    stored[key + "archive.json"] = json.dumps(manifest).encode()
    if tamper == "oversized":
        stored[key + "archive.json"] = b"x" * (archive.MAX_JSON_BYTES + 1)
    if tamper:
        with pytest.raises(ValueError):
            archive.restore_recovery_archive(claim, tmp_path)
    else:
        restored = archive.restore_recovery_archive(claim, tmp_path)
        assert restored["bundle_digest"] == admission["bundle_digest"]
        assert (tmp_path / "release.zip").read_bytes() == bundle.read_bytes()


def test_missing_archive_requires_legacy_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim = {
        "claim_id": 99,
        "candidate": "a" * 40,
        "record_version": "original-record",
        "expected_state_sha256": "d" * 64,
    }

    def context(*_args: object) -> dict[str, Any]:
        return {"bundle": {}}

    monkeypatch.setattr(archive.delivery, "load_recovery", context)

    def missing(*_args: str) -> NoReturn:
        raise archive.delivery.checks.CheckFailure("cli")

    def expired(*_args: str) -> NoReturn:
        raise archive.AdmissionError("expired")

    monkeypatch.setattr(archive.delivery, "aws", missing)
    monkeypatch.setattr(archive, "recovery_admission", expired)
    with pytest.raises(archive.AdmissionError, match="expired"):
        archive.restore_recovery_archive(claim, tmp_path)
