from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from botocore.session import get_session  # pyright: ignore[reportUnknownVariableType]
from botocore.validate import (  # pyright: ignore[reportUnknownVariableType]
    ParamValidationError,
    validate_parameters,  # pyright: ignore[reportUnknownVariableType]
)

V2_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = V2_ROOT / "scripts" / "retire_legacy_development_buckets.py"
SPEC = importlib.util.spec_from_file_location("legacy_bucket_retirement", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def _record(
    bucket: str,
    key: str,
    *,
    version_id: str = "null",
    marker: bool = False,
    http_metadata: bool = False,
) -> Any:
    return module.ObjectRecord(
        bucket=bucket,
        key=key,
        version_id=version_id,
        delete_marker=marker,
        is_latest=None,
        etag=None if marker else '"etag"',
        size=None if marker else 4,
        last_modified="2026-09-05T00:00:00+00:00",
        metadata=() if marker else (("content-type", "application/octet-stream"),),
        tags=() if marker else (("environment", "legacy"),),
        sha256=None if marker else hashlib.sha256(b"data").hexdigest(),
        content_type="text/html" if http_metadata else None,
        content_encoding="gzip" if http_metadata else None,
        cache_control="max-age=60" if http_metadata else None,
        content_disposition="inline" if http_metadata else None,
        expires="2026-09-06T00:00:00+00:00" if http_metadata else None,
        website_redirect_location="/redirected" if http_metadata else None,
    )


def _snapshot(extra: list[Any] | None = None) -> dict[str, Any]:
    records = [
        _record(bucket, key)
        for bucket, keys in module.MANAGED_OLD_OBJECTS.items()
        for key in keys
    ]
    records.extend(
        (
            _record(module.SITE_BUCKET, "unmanaged/a"),
            _record(module.MEASUREMENT_BUCKET, "unmanaged/b"),
            _record(
                module.SHARED_ARTIFACT_BUCKET, module.SHARED_KEYS[0], version_id="v1"
            ),
            _record(
                module.SHARED_ARTIFACT_BUCKET, module.SHARED_KEYS[1], version_id="v2"
            ),
        )
    )
    records.extend(extra or [])
    return {
        "manifest": "legacy-bucket-inventory-v1",
        "account_id": module.PRODUCTION_ACCOUNT,
        "region": module.PRODUCTION_REGION,
        "captured_at": "2026-09-05T00:00:00+00:00",
        "buckets": {},
        "shared_bucket": {},
        "objects": [record.as_dict() for record in records],
    }


def _records(extra: list[Any] | None = None) -> list[Any]:
    snapshot = _snapshot(extra)
    return [module._record_from_dict(raw) for raw in snapshot["objects"]]


def test_allowlist_has_exact_bucket_and_managed_boundaries() -> None:
    assert module.OLD_BUCKETS == (module.SITE_BUCKET, module.MEASUREMENT_BUCKET)
    assert module.SHARED_ARTIFACT_BUCKET not in module.OLD_BUCKETS
    assert sum(map(len, module.MANAGED_OLD_OBJECTS.values())) == 23
    assert set(module.SHARED_KEYS) == {
        "runtime/v2/agentcore-dev.zip",
        "lambda/v2/chat-proxy-dev.zip",
    }
    assert "nova-toll-tfstate-903859731897" not in module.OLD_BUCKETS


@pytest.mark.parametrize(
    "ambient_name",
    ("AWS_ENDPOINT_URL_LAMBDA", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"),
)
def test_rejects_every_unapproved_aws_environment_override(
    monkeypatch: pytest.MonkeyPatch, ambient_name: str
) -> None:
    monkeypatch.setenv(ambient_name, "/tmp/ambient-override")
    with pytest.raises(module.RetirementError, match="ambient AWS"):
        module._reject_ambient_credentials()


def test_guarded_response_drops_only_transport_metadata() -> None:
    class STS:
        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": module.PRODUCTION_ACCOUNT}

    class S3:
        def describe(self) -> dict[str, object]:
            return {"Value": "semantic", "ResponseMetadata": {"RequestId": "volatile"}}

    aws = module.GuardedAWS({"sts": STS(), "s3": S3()})
    assert aws.call("s3", "describe") == {"Value": "semantic"}


def test_rejects_suspended_bucket_versioning(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_s3(_aws: Any, operation: str, **_kwargs: object) -> dict[str, object]:
        if operation == "get_bucket_versioning":
            return {"Status": "Suspended"}
        raise AssertionError(operation)

    original = module._s3
    monkeypatch.setattr(module, "_s3", fake_s3)
    try:
        with pytest.raises(module.RetirementError, match="suspended"):
            module._bucket_configuration(object(), module.SITE_BUCKET)
    finally:
        monkeypatch.setattr(module, "_s3", original)


def test_rejects_malformed_inventory_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_s3(_aws: Any, operation: str, **_kwargs: object) -> dict[str, object]:
        if operation == "list_objects_v2":
            return {"Contents": [], "IsTruncated": "false"}
        raise AssertionError(operation)

    original = module._s3
    monkeypatch.setattr(module, "_s3", fake_s3)
    try:
        with pytest.raises(module.RetirementError, match="pagination flag"):
            module._list_old_bucket(object(), module.SITE_BUCKET)
    finally:
        monkeypatch.setattr(module, "_s3", original)


def test_rejects_malformed_shared_version_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_s3(_aws: Any, operation: str, **_kwargs: object) -> dict[str, object]:
        if operation == "list_object_versions":
            return {
                "Versions": [],
                "DeleteMarkers": [],
                "IsTruncated": None,
            }
        raise AssertionError(operation)

    original = module._s3
    monkeypatch.setattr(module, "_s3", fake_s3)
    try:
        with pytest.raises(module.RetirementError, match="pagination flag"):
            module._list_shared_key(object(), module.SHARED_KEYS[0])
    finally:
        monkeypatch.setattr(module, "_s3", original)


def test_stream_digest_reads_chunks_without_retaining_the_body() -> None:
    class ChunkedBody:
        def __init__(self) -> None:
            self.closed = False

        def iter_chunks(self, *, chunk_size: int):
            assert chunk_size == 1024 * 1024
            yield b"large-"
            yield b"object"

        def close(self) -> None:
            self.closed = True

    body = ChunkedBody()
    assert module._stream_digest(body) == hashlib.sha256(b"large-object").hexdigest()
    assert body.closed


def test_local_snapshot_record_contains_digests_without_metadata_or_tags() -> None:
    record = _record(module.SITE_BUCKET, "unmanaged/a", http_metadata=True)
    snapshot = record.snapshot_dict()
    assert "metadata" not in snapshot
    assert "tags" not in snapshot
    assert "content_type" not in snapshot
    assert "content_disposition" not in snapshot
    assert "expires" not in snapshot
    assert "website_redirect_location" not in snapshot
    assert snapshot["metadata_sha256"] == record.metadata_sha256
    assert snapshot["tags_sha256"] == record.tags_sha256
    assert snapshot["http_metadata_sha256"] == record.http_metadata_sha256


def test_local_snapshot_http_digest_detects_redirect_change() -> None:
    original_record = _record(module.SITE_BUCKET, "unmanaged/a", http_metadata=True)
    changed_record = replace(
        original_record, website_redirect_location="/private?token=changed"
    )
    original = {"objects": [original_record.snapshot_dict()]}
    changed = {"objects": [changed_record.snapshot_dict()]}
    with pytest.raises(module.RetirementError):
        module.assert_snapshot_stable(original, changed)


def test_delete_marker_is_manifest_identity_only_and_never_copied() -> None:
    marker = _record(
        module.SHARED_ARTIFACT_BUCKET,
        module.SHARED_KEYS[0],
        version_id="delete-marker-1",
        marker=True,
    )

    class NoCallClient:
        def call(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("delete markers must not call CopyObject")

    archived = module._archive_item(
        NoCallClient(), marker, "arn:aws:kms:us-east-1:920534282028:key/retained"
    )
    assert archived["archived_delete_marker"] is True
    assert archived["archive_key"] is None
    assert archived["archive_version_id"] is None
    assert archived["version_id"] == "delete-marker-1"


def test_archive_copy_preserves_source_identity_and_streamed_digest() -> None:
    record = _record(module.SITE_BUCKET, "unmanaged/a", http_metadata=True)
    assert record.expires is not None

    class FakeAWS:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def call(
            self, service: str, operation: str, **kwargs: object
        ) -> dict[str, object]:
            assert service == "s3"
            self.calls.append((operation, kwargs))
            if operation == "copy_object":
                return {"VersionId": "archive-v1"}
            if operation == "head_object":
                return {
                    "ETag": record.etag,
                    "ContentLength": record.size,
                    "Metadata": dict(record.metadata),
                    "ContentType": record.content_type,
                    "ContentEncoding": record.content_encoding,
                    "CacheControl": record.cache_control,
                    "ContentDisposition": record.content_disposition,
                    "Expires": datetime.fromisoformat(record.expires),
                    "WebsiteRedirectLocation": record.website_redirect_location,
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": "arn:aws:kms:us-east-1:920534282028:key/retained",
                }
            if operation == "get_object_tagging":
                return {
                    "TagSet": [
                        {"Key": key, "Value": value} for key, value in record.tags
                    ]
                }
            if operation == "get_object":
                return {"Body": io.BytesIO(b"data")}
            raise AssertionError(operation)

    fake = FakeAWS()
    result = module._archive_item(
        fake, record, "arn:aws:kms:us-east-1:920534282028:key/retained"
    )
    assert result["archive_version_id"] == "archive-v1"
    copy_call = next(
        kwargs for operation, kwargs in fake.calls if operation == "copy_object"
    )
    assert copy_call["ExpectedBucketOwner"] == module.PRODUCTION_ACCOUNT
    assert copy_call["ExpectedSourceBucketOwner"] == module.PRODUCTION_ACCOUNT
    assert copy_call["CopySourceIfMatch"] == record.etag
    assert copy_call["ContentType"] == record.content_type
    assert copy_call["ContentEncoding"] == record.content_encoding
    assert copy_call["CacheControl"] == record.cache_control
    assert copy_call["ContentDisposition"] == record.content_disposition
    assert copy_call["Expires"] == datetime.fromisoformat(record.expires)
    assert copy_call["WebsiteRedirectLocation"] == record.website_redirect_location
    assert copy_call["MetadataDirective"] == "COPY"
    assert copy_call["TaggingDirective"] == "COPY"
    assert copy_call["ServerSideEncryption"] == "aws:kms"


def test_archive_manifest_load_binds_exact_version_and_digest() -> None:
    snapshot = _snapshot()
    kms_key_id = "arn:aws:kms:us-east-1:920534282028:key/retained"
    manifest: dict[str, Any] = {
        "manifest": "legacy-bucket-archive-v1",
        "account_id": module.PRODUCTION_ACCOUNT,
        "region": module.PRODUCTION_REGION,
        "source_snapshot_sha256": module._snapshot_digest(snapshot),
        "state_bucket": module.STATE_BUCKET,
        "archive_prefix": module.ARCHIVE_PREFIX,
        "kms_key_id": kms_key_id,
        "objects": [],
    }
    body = module._canonical(manifest).encode()
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeAWS:
        def call(
            self, _service: str, operation: str, **kwargs: object
        ) -> dict[str, object]:
            calls.append((operation, kwargs))
            if operation == "head_object":
                return {
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": kms_key_id,
                }
            if operation == "get_object":
                return {"Body": io.BytesIO(body)}
            raise AssertionError(operation)

    archive_state = {
        "manifest_key": module.archive_manifest_key(snapshot),
        "manifest_version_id": "manifest-v17",
        "manifest_sha256": hashlib.sha256(body).hexdigest(),
        "source_snapshot_sha256": module._snapshot_digest(snapshot),
        "kms_key_id": kms_key_id,
    }
    assert (
        module._load_archive_manifest(FakeAWS(), snapshot, kms_key_id, archive_state)
        == manifest
    )
    assert calls[0][1]["VersionId"] == "manifest-v17"
    assert calls[1][1]["VersionId"] == "manifest-v17"


def test_archive_state_must_bind_current_identity_and_mapping_evidence() -> None:
    with pytest.raises(module.RetirementError, match="different live evidence"):
        module._require_archive_evidence_binding(
            {"identity_sha256": "old", "mapping_sha256": "same"},
            {"identity_sha256": "new", "mapping_sha256": "same"},
        )


def test_purge_targets_are_fresh_inventory_minus_managed_keys() -> None:
    targets = module.purge_targets(_snapshot())
    assert {(record.bucket, record.key) for record in targets} == {
        (module.SITE_BUCKET, "unmanaged/a"),
        (module.MEASUREMENT_BUCKET, "unmanaged/b"),
    }
    assert all(record.version_id == "null" for record in targets)


def test_purge_verifies_archive_before_first_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAWS:
        def call(
            self, _service: str, operation: str, **_kwargs: object
        ) -> dict[str, object]:
            if operation == "delete_object":
                raise AssertionError("delete must follow archive verification")
            return {}

    def no_freeze(*_args: object, **_kwargs: object) -> None:
        return None

    def empty_manifest(*_args: object, **_kwargs: object) -> dict[str, list[object]]:
        return {"objects": []}

    def reject_archive(*_args: object, **_kwargs: object) -> None:
        raise module.RetirementError("bad archive")

    monkeypatch.setattr(module, "_require_freeze_evidence", no_freeze)
    monkeypatch.setattr(module, "_load_archive_manifest", empty_manifest)
    monkeypatch.setattr(module, "_verify_archive_objects", reject_archive)
    with pytest.raises(module.RetirementError, match="bad archive"):
        module.purge_snapshot(
            FakeAWS(),
            _snapshot(),
            "arn:aws:kms:us-east-1:920534282028:key/retained",
            {"drain_seconds": 900, "before": {}},
            {"manifest_version_id": "v1"},
        )


def test_purge_uses_exact_etag_and_stops_on_conditional_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    local_snapshot = copy.deepcopy(snapshot)
    local_records = [module._record_from_dict(raw) for raw in snapshot["objects"]]
    local_snapshot["objects"] = [
        record.snapshot_dict()
        for record in sorted(local_records, key=module._record_sort)
    ]

    class FakeAWS:
        def call(
            self, _service: str, operation: str, **kwargs: object
        ) -> dict[str, object]:
            if operation == "delete_object":
                assert kwargs["IfMatch"] == '"etag"'
                assert kwargs["ExpectedBucketOwner"] == module.EXPECTED_OWNER
                raise module.RetirementError("412 PreconditionFailed")
            raise AssertionError(operation)

    def no_freeze(*_args: object, **_kwargs: object) -> None:
        return None

    def empty_archive(*_args: object, **_kwargs: object) -> dict[str, Any]:
        return {}

    def no_archive_verify(*_args: object, **_kwargs: object) -> None:
        return None

    def frozen_capture(_aws: Any) -> dict[str, Any]:
        return local_snapshot

    monkeypatch.setattr(module, "_require_freeze_evidence", no_freeze)
    monkeypatch.setattr(module, "_load_archive_manifest", empty_archive)
    monkeypatch.setattr(module, "_verify_archive_objects", no_archive_verify)
    monkeypatch.setattr(module, "capture_snapshot", frozen_capture)
    with pytest.raises(module.RetirementError, match="outcome is unknown"):
        module.purge_snapshot(
            FakeAWS(),
            local_snapshot,
            "arn:aws:kms:us-east-1:920534282028:key/retained",
            {"drain_seconds": 900},
            {"manifest_version_id": "v1"},
        )


def test_changed_metadata_or_tags_with_same_etag_fails_stability() -> None:
    original = _snapshot()
    changed = copy.deepcopy(original)
    objects = changed["objects"]
    assert isinstance(objects, list)
    objects[0]["metadata"] = {"content-type": "text/plain"}
    with pytest.raises(module.RetirementError):
        module.assert_snapshot_stable(original, changed)

    changed = copy.deepcopy(original)
    objects = changed["objects"]
    assert isinstance(objects, list)
    objects[0]["tags"] = [{"Key": "environment", "Value": "changed"}]
    with pytest.raises(module.RetirementError):
        module.assert_snapshot_stable(original, changed)


@pytest.mark.parametrize(
    "bad_record",
    [
        _record("unexpected-bucket", "key"),
        _record(module.SHARED_ARTIFACT_BUCKET, "runtime/v2/other.zip", version_id="v1"),
        _record(
            module.SHARED_ARTIFACT_BUCKET,
            module.SHARED_KEYS[0],
            version_id="v1",
            marker=True,
        ),
    ],
)
def test_unknown_bucket_key_or_version_fails_closed(bad_record: object) -> None:
    with pytest.raises(module.RetirementError):
        module.validate_records([*_records(), bad_record])  # type: ignore[arg-type]


def test_waf_change_preserves_full_document_and_rejects_unknown_fields() -> None:
    config: dict[str, Any] = {
        "ResourceArn": "arn:aws:wafv2:us-east-1:920534282028:global/webacl/test/id",
        "LogDestinationConfigs": ["arn:aws:s3:::aws-waf-logs"],
        "RedactedFields": [{"QueryString": {}}],
        "ManagedByFirewallManager": False,
        "LogType": "WAF_LOGS",
        "LogScope": "CUSTOMER",
        "LoggingFilter": {
            "DefaultBehavior": "DROP",
            "Filters": [
                {
                    "Behavior": "KEEP",
                    "Requirement": "MEETS_ALL",
                    "Conditions": [
                        {"LabelNameCondition": {"LabelName": module.WAF_AGENT_LABEL}}
                    ],
                }
            ],
        },
    }
    changed = module._change_waf_filter(config)
    assert changed["LogDestinationConfigs"] == config["LogDestinationConfigs"]
    assert changed["RedactedFields"] == config["RedactedFields"]
    assert changed["ManagedByFirewallManager"] is False
    assert changed["LoggingFilter"]["DefaultBehavior"] == "DROP"
    assert changed["LoggingFilter"]["Filters"][0]["Behavior"] == "DROP"
    with pytest.raises(module.RetirementError):
        module._waf_request({**config, "Unexpected": True})


def test_lifecycle_change_preserves_transition_and_rule_fields() -> None:
    config = {
        "TransitionDefaultMinimumObjectSize": "all_storage_classes_128K",
        "Rules": [
            {
                "ID": "expire-raw-waf-logs",
                "Status": "Enabled",
                "Filter": {"Prefix": "AWSLogs/"},
            },
            {
                "ID": "expire-athena-results",
                "Status": "Enabled",
                "Expiration": {"Days": 7},
            },
        ],
    }
    changed = module._disable_lifecycle(config)
    assert changed["TransitionDefaultMinimumObjectSize"] == "all_storage_classes_128K"
    assert {rule["Status"] for rule in changed["Rules"]} == {"Disabled"}
    assert changed["Rules"][0]["Filter"] == {"Prefix": "AWSLogs/"}
    with pytest.raises(module.RetirementError):
        module._lifecycle_request({**config, "Unexpected": True})
    request = module._lifecycle_request(changed)
    assert request["LifecycleConfiguration"]["Rules"] == changed["Rules"]
    assert request["TransitionDefaultMinimumObjectSize"] == "all_storage_classes_128K"
    session: Any = get_session()
    service_model: Any = session.get_service_model("s3")
    operation_model: Any = service_model.operation_model(
        "PutBucketLifecycleConfiguration"
    )
    input_shape: Any = operation_model.input_shape
    validate_parameters({"Bucket": module.MEASUREMENT_BUCKET, **request}, input_shape)
    with pytest.raises(ParamValidationError):
        validate_parameters(
            {"Bucket": module.MEASUREMENT_BUCKET, "Rules": changed["Rules"]},
            input_shape,
        )


def test_draining_contract_is_exactly_900_seconds() -> None:
    assert module.DRAIN_SECONDS == 900
    assert module.HISTORICAL_UNMANAGED_COUNT == 1655
    assert module.HISTORICAL_SHARED_VERSION_COUNT == 5


def test_freeze_evidence_requires_elapsed_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.0)
    with pytest.raises(module.RetirementError, match="900-second drain"):
        module._require_freeze_evidence(
            object(),
            {
                "drain_seconds": module.DRAIN_SECONDS,
                "freeze_completed_monotonic": 1.0,
                "drain_completed_at": "2026-09-05T00:00:00+00:00",
            },
        )


def test_runbook_contract_mentions_bounded_phase_guards() -> None:
    runbook = (V2_ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    for required in (
        "retire_legacy_development_buckets.py",
        "tollchat-site-920534282028-dev",
        "aws-waf-logs-tollchat-agent-reports-920534282028-dev",
        "nova-toll-agentcore-920534282028",
        "runtime/v2/agentcore-dev.zip",
        "lambda/v2/chat-proxy-dev.zip",
        "22 site keys + 1 registry key",
        "1,655 unmanaged old objects",
        "5 shared versions",
        "900 seconds",
        "tollchat-agent-reports-dev",
        "If-Match",
        "ExpectedBucketOwner",
        "TransitionDefaultMinimumObjectSize",
        "ManagedByFirewallManager",
        "total_max_attempts=1",
        "exactly 162 deletes",
    ):
        assert required in runbook
    source = SCRIPT.read_text(encoding="utf-8")
    assert "delete_bucket" not in source.lower()
    assert "force_destroy" not in source
