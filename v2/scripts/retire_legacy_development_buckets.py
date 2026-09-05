#!/usr/bin/env python3
# ruff: noqa: ANN401
"""Archive and conditionally purge the fixed legacy development S3 objects.

The default phase is a read-only inventory.  Mutation phases intentionally
accept no bucket or key arguments: the allowlist below is the whole scope.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import ClientError

PRODUCTION_ACCOUNT = "920534282028"
PRODUCTION_REGION = "us-east-1"
PRODUCTION_PROFILE = "nova-toll-prod"
STATE_BUCKET = f"nova-toll-tfstate-{PRODUCTION_ACCOUNT}"
ARCHIVE_PREFIX = "nova-toll/v2/development/retirement-archives/"
SITE_BUCKET = f"tollchat-site-{PRODUCTION_ACCOUNT}-dev"
MEASUREMENT_BUCKET = f"aws-waf-logs-tollchat-agent-reports-{PRODUCTION_ACCOUNT}-dev"
SHARED_ARTIFACT_BUCKET = f"nova-toll-agentcore-{PRODUCTION_ACCOUNT}"
OLD_BUCKETS = (SITE_BUCKET, MEASUREMENT_BUCKET)
SHARED_KEYS = (
    "runtime/v2/agentcore-dev.zip",
    "lambda/v2/chat-proxy-dev.zip",
)
EXPECTED_OWNER = PRODUCTION_ACCOUNT
ATHENA_WORKGROUP = "tollchat-agent-reports-dev"
WAF_NAME = "tollchat-v2-public-chat-dev"
WAF_AGENT_LABEL = f"awswaf:{PRODUCTION_ACCOUNT}:webacl:{WAF_NAME}:agent-route-report"
DRAIN_SECONDS = 900
HISTORICAL_UNMANAGED_COUNT = 1655
HISTORICAL_MANAGED_OLD_COUNT = 23
HISTORICAL_SHARED_VERSION_COUNT = 5
EXPECTED_IDENTITY_MANIFEST = "legacy-live-identity-v1"
EXPECTED_IDENTITY_SOURCE = "account-scoped-live-api-v1"
EXPECTED_SOURCE_COMMIT = "4c1f684c02bf81187c2cc5f15883727cf15b11ee"
EXPECTED_SOURCE_REMOTES = frozenset(
    {
        "git@github.com:rhprasad0/nova-toll-budget-agent.git",
        "https://github.com/rhprasad0/nova-toll-budget-agent.git",
    }
)
LAMBDA_WRITERS = (
    ("toll-v2-report-publisher-dev", 900),
    ("tollchat-v2-usage-publisher-dev", 15),
    ("tollchat-v2-agent-usage-rollup-dev", 300),
)

# The 22 site objects and one measurement object are the only old-bucket
# objects Terraform owns.  The two shared package keys are handled separately.
MANAGED_OLD_OBJECTS: Mapping[str, frozenset[str]] = {
    SITE_BUCKET: frozenset(
        {
            "chat.mjs",
            "faq.html",
            "index.html",
            "privacy.txt",
            "robots.txt",
            "terms.txt",
            "usage.json",
            "assets/LICENSE.txt",
            "assets/chat-markdown.mjs",
            "assets/commute-estimates.json",
            "assets/commute-map.mjs",
            "assets/commute-routes.mjs",
            "assets/coverage-locations.json",
            "assets/favicon.png",
            "assets/maplibre-gl-6.0.0/LICENSE.txt",
            "assets/maplibre-gl-6.0.0/maplibre-gl-shared.mjs",
            "assets/maplibre-gl-6.0.0/maplibre-gl-worker.mjs",
            "assets/maplibre-gl-6.0.0/maplibre-gl.css",
            "assets/maplibre-gl-6.0.0/maplibre-gl.mjs",
            "assets/markdown-it.esm.min.mjs",
            "assets/tollchat-annual-commute-example.png",
            "assets/tollchat-logo.png",
        }
    ),
    MEASUREMENT_BUCKET: frozenset({"registry/agent_registry.ndjson"}),
}
if (
    sum(len(keys) for keys in MANAGED_OLD_OBJECTS.values())
    != HISTORICAL_MANAGED_OLD_COUNT
):
    raise AssertionError("managed old-object contract changed")


class RetirementError(RuntimeError):
    """A malformed, changed, or ambiguous retirement result."""


def _reject_ambient_credentials() -> None:
    allowed = {"AWS_PROFILE", "AWS_DEFAULT_REGION"}
    if any(name.startswith("AWS_") and name not in allowed for name in os.environ):
        raise RetirementError(
            "ambient AWS credentials or endpoint/config override is set"
        )
    if os.environ.get("AWS_PROFILE") not in (None, PRODUCTION_PROFILE):
        raise RetirementError("AWS_PROFILE is not the fixed production profile")
    if os.environ.get("AWS_DEFAULT_REGION") not in (None, PRODUCTION_REGION):
        raise RetirementError("AWS_DEFAULT_REGION is not the fixed production region")


@dataclass(frozen=True)
class ObjectRecord:
    bucket: str
    key: str
    version_id: str
    delete_marker: bool
    is_latest: bool | None
    etag: str | None
    size: int | None
    last_modified: str | None
    metadata: tuple[tuple[str, str], ...]
    tags: tuple[tuple[str, str], ...]
    sha256: str | None
    content_type: str | None = None
    content_encoding: str | None = None
    cache_control: str | None = None
    content_disposition: str | None = None
    expires: str | None = None
    website_redirect_location: str | None = None
    metadata_digest: str | None = None
    tags_digest: str | None = None
    http_metadata_digest: str | None = None

    @property
    def metadata_sha256(self) -> str:
        return (
            self.metadata_digest
            or hashlib.sha256(_canonical(dict(self.metadata)).encode()).hexdigest()
        )

    @property
    def tags_sha256(self) -> str:
        return (
            self.tags_digest
            or hashlib.sha256(_canonical(dict(self.tags)).encode()).hexdigest()
        )

    @property
    def http_metadata_sha256(self) -> str:
        return (
            self.http_metadata_digest
            or hashlib.sha256(
                _canonical(
                    {
                        "content_type": self.content_type,
                        "content_encoding": self.content_encoding,
                        "cache_control": self.cache_control,
                        "content_disposition": self.content_disposition,
                        "expires": self.expires,
                        "website_redirect_location": self.website_redirect_location,
                    }
                ).encode()
            ).hexdigest()
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "key": self.key,
            "version_id": self.version_id,
            "delete_marker": self.delete_marker,
            "is_latest": self.is_latest,
            "etag": self.etag,
            "size": self.size,
            "last_modified": self.last_modified,
            "metadata": dict(self.metadata),
            "tags": [{"Key": key, "Value": value} for key, value in self.tags],
            "metadata_sha256": self.metadata_sha256,
            "tags_sha256": self.tags_sha256,
            "http_metadata_sha256": self.http_metadata_sha256,
            "sha256": self.sha256,
            "content_type": self.content_type,
            "content_encoding": self.content_encoding,
            "cache_control": self.cache_control,
            "content_disposition": self.content_disposition,
            "expires": self.expires,
            "website_redirect_location": self.website_redirect_location,
        }

    def snapshot_dict(self) -> dict[str, Any]:
        value = self.as_dict()
        value.pop("metadata", None)
        value.pop("tags", None)
        for field in (
            "content_type",
            "content_encoding",
            "cache_control",
            "content_disposition",
            "expires",
            "website_redirect_location",
        ):
            value.pop(field, None)
        return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RetirementError(f"missing {field}")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _optional_timestamp(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _timestamp(value)


def _expires_value(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise RetirementError("object Expires metadata is malformed") from error


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RetirementError(f"malformed {field}")
    return cast(Mapping[str, Any], value)


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise RetirementError(f"malformed {field}")
    return cast(list[Any], value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Mapping):
        mapping = cast(Mapping[Any, Any], value)
        return {str(key): _jsonable(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        values = cast(Iterable[Any], value)
        return [_jsonable(item) for item in values]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return _text(value, "LastModified")


def _tags(response: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    raw = _list(response.get("TagSet", []), "object tags")
    values: list[tuple[str, str]] = []
    for item in raw:
        item = _mapping(item, "object tag")
        values.append(
            (_text(item.get("Key"), "tag key"), _text(item.get("Value"), "tag value"))
        )
    return tuple(sorted(values))


def _metadata(response: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    raw = response.get("Metadata", {})
    raw = _mapping(raw, "object metadata")
    values: list[tuple[str, str]] = []
    for key, value in raw.items():
        values.append((_text(key, "metadata key"), _text(value, "metadata value")))
    return tuple(sorted(values))


def _version_params(version_id: str) -> dict[str, str]:
    return {} if version_id == "null" else {"VersionId": version_id}


def _stream_digest(body: Any) -> str:
    digest = hashlib.sha256()
    if hasattr(body, "iter_chunks"):
        chunks: Iterable[Any] = body.iter_chunks(chunk_size=1024 * 1024)
    elif hasattr(body, "read"):

        def read_chunks() -> Iterable[Any]:
            while True:
                chunk = body.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk

        chunks = read_chunks()
    else:
        raise RetirementError("object body is not streamable")
    try:
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise RetirementError("object body returned a non-bytes chunk")
            digest.update(chunk)
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    return digest.hexdigest()


class GuardedAWS:
    """Small no-retry client wrapper with fixed account/region boundaries."""

    def __init__(
        self, clients: Mapping[str, Any], *, region: str = PRODUCTION_REGION
    ) -> None:
        self.clients = clients
        self.region = region

    @classmethod
    def live(cls, profile: str = PRODUCTION_PROFILE) -> GuardedAWS:
        _reject_ambient_credentials()
        if profile != PRODUCTION_PROFILE:
            raise RetirementError("only the fixed production profile is allowed")
        session: Any = Session(profile_name=profile, region_name=PRODUCTION_REGION)
        config = Config(retries={"mode": "standard", "total_max_attempts": 1})
        services = ("sts", "s3", "lambda", "wafv2", "athena")
        clients: dict[str, Any] = {
            service: session.client(service, config=config) for service in services
        }
        guarded = cls(clients)
        guarded._assert_account()
        return guarded

    def _assert_account(self) -> None:
        sts = self.clients.get("sts")
        if sts is None:
            raise RetirementError("STS client is missing")
        try:
            raw_identity: Any = sts.get_caller_identity()
        except Exception as error:
            raise RetirementError("caller identity check failed") from error
        if not isinstance(raw_identity, dict):
            raise RetirementError("production account check returned malformed data")
        identity = cast(dict[str, Any], raw_identity)
        if identity.get("Account") != PRODUCTION_ACCOUNT:
            raise RetirementError("production account check failed")

    def call(self, service: str, operation: str, **kwargs: Any) -> dict[str, Any]:
        if service != "s3":
            self._assert_account()
        if self.region != PRODUCTION_REGION:
            raise RetirementError("production region check failed")
        client = self.clients.get(service)
        if client is None:
            raise RetirementError(f"{service} client is missing")
        try:
            raw_result: Any = getattr(client, operation)(**kwargs)
        except Exception as error:
            raise RetirementError(f"{service} request failed") from error
        if not isinstance(raw_result, dict):
            raise RetirementError(f"{service} returned a malformed response")
        result = cast(dict[str, Any], raw_result)
        result.pop("ResponseMetadata", None)
        return result


def _s3(aws: GuardedAWS, operation: str, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("ExpectedBucketOwner", EXPECTED_OWNER) != EXPECTED_OWNER:
        raise RetirementError("S3 expected owner is not the production account")
    kwargs["ExpectedBucketOwner"] = EXPECTED_OWNER
    return aws.call("s3", operation, **kwargs)


def _required_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RetirementError(f"invalid {field}")
    return value


def _object_record(
    aws: GuardedAWS,
    *,
    bucket: str,
    key: str,
    version_id: str,
    is_latest: bool | None = None,
    listed_etag: str | None = None,
    listed_size: int | None = None,
) -> ObjectRecord:
    response = _s3(
        aws,
        "head_object",
        Bucket=bucket,
        Key=key,
        **_version_params(version_id),
    )
    etag = _text(response.get("ETag"), "ETag")
    size = _required_int(response.get("ContentLength"), "ContentLength")
    if listed_etag is not None and etag != listed_etag:
        raise RetirementError("version ETag changed during inventory")
    if listed_size is not None and size != listed_size:
        raise RetirementError("version size changed during inventory")
    tag_response = _s3(
        aws,
        "get_object_tagging",
        Bucket=bucket,
        Key=key,
        **_version_params(version_id),
    )
    body_response = _s3(
        aws,
        "get_object",
        Bucket=bucket,
        Key=key,
        **_version_params(version_id),
    )
    body = body_response.get("Body")
    digest = _stream_digest(body)
    return ObjectRecord(
        bucket=bucket,
        key=key,
        version_id=version_id,
        delete_marker=False,
        is_latest=is_latest,
        etag=etag,
        size=size,
        last_modified=_timestamp(response.get("LastModified")),
        metadata=_metadata(response),
        tags=_tags(tag_response),
        sha256=digest,
        content_type=_optional_text(response.get("ContentType"), "ContentType"),
        content_encoding=_optional_text(
            response.get("ContentEncoding"), "ContentEncoding"
        ),
        cache_control=_optional_text(response.get("CacheControl"), "CacheControl"),
        content_disposition=_optional_text(
            response.get("ContentDisposition"), "ContentDisposition"
        ),
        expires=_optional_timestamp(response.get("Expires"), "Expires"),
        website_redirect_location=_optional_text(
            response.get("WebsiteRedirectLocation"), "WebsiteRedirectLocation"
        ),
    )


def _bucket_configuration(aws: GuardedAWS, bucket: str) -> dict[str, Any]:
    versioning = _s3(aws, "get_bucket_versioning", Bucket=bucket)
    status = versioning.get("Status")
    if status not in (None, "Disabled"):
        raise RetirementError(f"{bucket} is versioned or suspended")
    encryption = _s3(aws, "get_bucket_encryption", Bucket=bucket)
    public_access = _s3(aws, "get_public_access_block", Bucket=bucket)
    ownership = _s3(aws, "get_bucket_ownership_controls", Bucket=bucket)
    multipart = _s3(aws, "list_multipart_uploads", Bucket=bucket)
    uploads = multipart.get("Uploads", [])
    if not isinstance(uploads, list) or uploads:
        raise RetirementError(f"{bucket} has multipart uploads")
    if not isinstance(multipart.get("IsTruncated"), bool):
        raise RetirementError(f"{bucket} multipart inventory is malformed")
    if multipart["IsTruncated"] is True:
        raise RetirementError(f"{bucket} multipart inventory is incomplete")
    return {
        "versioning": {"Status": status},
        "encryption": _jsonable(encryption),
        "public_access": _jsonable(public_access),
        "ownership": _jsonable(ownership),
        "multipart": {"Uploads": [], "IsTruncated": False},
    }


def _list_old_bucket(aws: GuardedAWS, bucket: str) -> list[ObjectRecord]:
    records: list[ObjectRecord] = []
    token: str | None = None
    seen: set[str] = set()
    page_tokens: set[str | None] = set()
    while True:
        if token in page_tokens:
            raise RetirementError("old-bucket pagination repeated a continuation token")
        page_tokens.add(token)
        params: dict[str, Any] = {"Bucket": bucket}
        if token is not None:
            params["ContinuationToken"] = token
        response = _s3(aws, "list_objects_v2", **params)
        contents = _list(response.get("Contents", []), "old-bucket inventory")
        for item in contents:
            item = _mapping(item, "old-bucket object")
            key = _text(item.get("Key"), "object key")
            if key in seen:
                raise RetirementError("duplicate old-bucket object")
            seen.add(key)
            records.append(
                _object_record(
                    aws,
                    bucket=bucket,
                    key=key,
                    version_id="null",
                    listed_etag=item.get("ETag"),
                    listed_size=item.get("Size"),
                )
            )
        truncated = response.get("IsTruncated")
        if not isinstance(truncated, bool):
            raise RetirementError("old-bucket pagination flag is malformed")
        if truncated is False:
            break
        token_value = response.get("NextContinuationToken")
        token = _text(token_value, "NextContinuationToken")
    return records


def _delete_marker(item: Mapping[str, Any], key: str) -> ObjectRecord:
    if item.get("Key") != key:
        raise RetirementError("shared version inventory widened beyond exact key")
    version_id = _text(item.get("VersionId"), "delete marker VersionId")
    if not isinstance(item.get("IsLatest"), bool):
        raise RetirementError("delete marker status is missing")
    return ObjectRecord(
        bucket=SHARED_ARTIFACT_BUCKET,
        key=key,
        version_id=version_id,
        delete_marker=True,
        is_latest=item["IsLatest"],
        etag=None,
        size=None,
        last_modified=_timestamp(item.get("LastModified")),
        metadata=(),
        tags=(),
        sha256=None,
    )


def _list_shared_key(aws: GuardedAWS, key: str) -> list[ObjectRecord]:
    records: list[ObjectRecord] = []
    key_marker: str | None = None
    version_marker: str | None = None
    seen: set[str] = set()
    page_markers: set[tuple[str | None, str | None]] = set()
    while True:
        page = (key_marker, version_marker)
        if page in page_markers:
            raise RetirementError("shared version pagination repeated a marker")
        page_markers.add(page)
        params: dict[str, Any] = {"Bucket": SHARED_ARTIFACT_BUCKET, "Prefix": key}
        if key_marker is not None:
            params["KeyMarker"] = key_marker
        if version_marker is not None:
            params["VersionIdMarker"] = version_marker
        response = _s3(aws, "list_object_versions", **params)
        versions = _list(response.get("Versions", []), "shared version inventory")
        for item in versions:
            item = _mapping(item, "shared object version")
            if item.get("Key") != key:
                raise RetirementError(
                    "shared version inventory widened beyond exact key"
                )
            version_id = _text(item.get("VersionId"), "object VersionId")
            if version_id in seen:
                raise RetirementError("duplicate shared object version")
            seen.add(version_id)
            records.append(
                _object_record(
                    aws,
                    bucket=SHARED_ARTIFACT_BUCKET,
                    key=key,
                    version_id=version_id,
                    is_latest=item.get("IsLatest")
                    if isinstance(item.get("IsLatest"), bool)
                    else None,
                    listed_etag=_text(item.get("ETag"), "object ETag"),
                    listed_size=_required_int(item.get("Size"), "object Size"),
                )
            )
        markers = _list(response.get("DeleteMarkers", []), "delete-marker inventory")
        for item in markers:
            item = _mapping(item, "delete marker")
            marker = _delete_marker(item, key)
            if marker.version_id in seen:
                raise RetirementError("duplicate shared delete marker")
            seen.add(marker.version_id)
            records.append(marker)
        truncated = response.get("IsTruncated")
        if not isinstance(truncated, bool):
            raise RetirementError("shared version pagination flag is malformed")
        if truncated is False:
            break
        key_marker = _text(response.get("NextKeyMarker"), "NextKeyMarker")
        version_marker = _text(
            response.get("NextVersionIdMarker"), "NextVersionIdMarker"
        )
    return records


def capture_snapshot(aws: GuardedAWS, *, raw: bool = False) -> dict[str, Any]:
    """Read all exact source objects and return a content-free snapshot."""
    buckets: dict[str, Any] = {}
    records: list[ObjectRecord] = []
    for bucket in OLD_BUCKETS:
        buckets[bucket] = _bucket_configuration(aws, bucket)
        records.extend(_list_old_bucket(aws, bucket))
    shared_config = {
        "versioning": _jsonable(
            _s3(aws, "get_bucket_versioning", Bucket=SHARED_ARTIFACT_BUCKET)
        ),
        "encryption": _jsonable(
            _s3(aws, "get_bucket_encryption", Bucket=SHARED_ARTIFACT_BUCKET)
        ),
        "public_access": _jsonable(
            _s3(aws, "get_public_access_block", Bucket=SHARED_ARTIFACT_BUCKET)
        ),
    }
    for key in SHARED_KEYS:
        records.extend(_list_shared_key(aws, key))
    validate_records(records)
    return {
        "manifest": "legacy-bucket-inventory-v1",
        "account_id": PRODUCTION_ACCOUNT,
        "region": PRODUCTION_REGION,
        "captured_at": datetime.now(UTC).isoformat(),
        "buckets": buckets,
        "shared_bucket": shared_config,
        "objects": [
            (record.as_dict() if raw else record.snapshot_dict())
            for record in sorted(records, key=_record_sort)
        ],
    }


def _record_sort(record: ObjectRecord | Mapping[str, Any]) -> tuple[str, str, str]:
    if isinstance(record, ObjectRecord):
        return record.bucket, record.key, record.version_id
    return (
        _text(record.get("bucket"), "bucket"),
        _text(record.get("key"), "key"),
        _text(record.get("version_id"), "version_id"),
    )


def _record_identity(record: ObjectRecord) -> tuple[Any, ...]:
    return (
        record.bucket,
        record.key,
        record.version_id,
        record.delete_marker,
        record.is_latest,
        record.etag,
        record.size,
        record.last_modified,
        record.metadata_sha256,
        record.tags_sha256,
        record.http_metadata_sha256,
        record.sha256,
    )


def _record_from_dict(raw: Any) -> ObjectRecord:
    if not isinstance(raw, Mapping):
        raise RetirementError("malformed object record")
    raw = cast(Mapping[str, Any], raw)
    raw_metadata = raw.get("metadata", {})
    raw_tags = raw.get("tags", [])
    has_metadata = "metadata" in raw
    has_tags = "tags" in raw
    raw_metadata = _mapping(raw_metadata, "object record metadata")
    raw_tags = _list(raw_tags, "object record tags")
    tags: list[tuple[str, str]] = []
    for item in raw_tags:
        item = _mapping(item, "object record tags")
        tags.append(
            (_text(item.get("Key"), "tag key"), _text(item.get("Value"), "tag value"))
        )
    metadata = tuple(
        sorted(
            (_text(key, "metadata key"), _text(value, "metadata value"))
            for key, value in raw_metadata.items()
        )
    )
    normalized_tags = tuple(sorted(tags))
    metadata_digest = raw.get("metadata_sha256")
    tags_digest = raw.get("tags_sha256")
    http_fields = (
        "content_type",
        "content_encoding",
        "cache_control",
        "content_disposition",
        "expires",
        "website_redirect_location",
    )
    has_http_metadata = any(field in raw for field in http_fields)
    http_metadata_digest = raw.get("http_metadata_sha256")
    if not isinstance(metadata_digest, str) or (
        has_metadata
        and metadata_digest
        != hashlib.sha256(_canonical(dict(metadata)).encode()).hexdigest()
    ):
        raise RetirementError("object metadata digest is missing or changed")
    if not isinstance(tags_digest, str) or (
        has_tags
        and tags_digest
        != hashlib.sha256(_canonical(dict(normalized_tags)).encode()).hexdigest()
    ):
        raise RetirementError("object tag digest is missing or changed")
    content_type = _optional_text(raw.get("content_type"), "content_type")
    content_encoding = _optional_text(raw.get("content_encoding"), "content_encoding")
    cache_control = _optional_text(raw.get("cache_control"), "cache_control")
    content_disposition = _optional_text(
        raw.get("content_disposition"), "content_disposition"
    )
    expires = _optional_timestamp(raw.get("expires"), "expires")
    website_redirect_location = _optional_text(
        raw.get("website_redirect_location"), "website_redirect_location"
    )
    actual_http_metadata_digest = hashlib.sha256(
        _canonical(
            {
                "content_type": content_type,
                "content_encoding": content_encoding,
                "cache_control": cache_control,
                "content_disposition": content_disposition,
                "expires": expires,
                "website_redirect_location": website_redirect_location,
            }
        ).encode()
    ).hexdigest()
    if not isinstance(http_metadata_digest, str) or (
        has_http_metadata and http_metadata_digest != actual_http_metadata_digest
    ):
        raise RetirementError("object HTTP metadata digest is missing or changed")
    return ObjectRecord(
        bucket=_text(raw.get("bucket"), "bucket"),
        key=_text(raw.get("key"), "key"),
        version_id=_text(raw.get("version_id"), "version_id"),
        delete_marker=raw.get("delete_marker") is True,
        is_latest=raw.get("is_latest")
        if isinstance(raw.get("is_latest"), bool)
        else None,
        etag=raw.get("etag") if isinstance(raw.get("etag"), str) else None,
        size=raw.get("size") if isinstance(raw.get("size"), int) else None,
        last_modified=raw.get("last_modified")
        if isinstance(raw.get("last_modified"), str)
        else None,
        metadata=metadata,
        tags=normalized_tags,
        sha256=raw.get("sha256") if isinstance(raw.get("sha256"), str) else None,
        content_type=content_type,
        content_encoding=content_encoding,
        cache_control=cache_control,
        content_disposition=content_disposition,
        expires=expires,
        website_redirect_location=website_redirect_location,
        metadata_digest=metadata_digest,
        tags_digest=tags_digest,
        http_metadata_digest=http_metadata_digest,
    )


def _snapshot_records(snapshot: Mapping[str, Any]) -> list[ObjectRecord]:
    if (
        snapshot.get("manifest") != "legacy-bucket-inventory-v1"
        or snapshot.get("account_id") != PRODUCTION_ACCOUNT
        or snapshot.get("region") != PRODUCTION_REGION
        or not isinstance(snapshot.get("objects"), list)
    ):
        raise RetirementError("invalid inventory snapshot")
    records = [_record_from_dict(raw) for raw in snapshot["objects"]]
    validate_records(records)
    return records


def validate_records(records: Iterable[ObjectRecord]) -> None:
    allowed = set(OLD_BUCKETS) | {SHARED_ARTIFACT_BUCKET}
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        if record.bucket not in allowed:
            raise RetirementError("inventory contains an out-of-scope bucket")
        identity = (record.bucket, record.key, record.version_id)
        if identity in seen:
            raise RetirementError("inventory contains a duplicate version")
        seen.add(identity)
        if record.bucket in OLD_BUCKETS:
            if record.key == "" or record.version_id != "null" or record.delete_marker:
                raise RetirementError("old-bucket inventory is not unversioned")
            if (
                record.etag is None
                or record.size is None
                or record.sha256 is None
                or record.last_modified is None
            ):
                raise RetirementError("old-bucket inventory is incomplete")
        else:
            if record.key not in SHARED_KEYS:
                raise RetirementError("shared inventory contains an out-of-scope key")
            if record.delete_marker:
                if (
                    record.sha256 is not None
                    or record.etag is not None
                    or record.size is not None
                    or record.last_modified is None
                    or record.is_latest is None
                ):
                    raise RetirementError("delete marker contains object content")
            elif (
                record.sha256 is None
                or record.etag is None
                or record.size is None
                or record.last_modified is None
            ):
                raise RetirementError("shared object version is incomplete")
    old_keys = {
        (record.bucket, record.key)
        for record in records
        if record.bucket in OLD_BUCKETS
    }
    for bucket, keys in MANAGED_OLD_OBJECTS.items():
        if not keys.issubset(
            {key for item_bucket, key in old_keys if item_bucket == bucket}
        ):
            raise RetirementError("managed Terraform object is missing")
    for key in SHARED_KEYS:
        if not any(
            record.bucket == SHARED_ARTIFACT_BUCKET and record.key == key
            for record in records
        ):
            raise RetirementError("managed shared object key is missing")


def assert_snapshot_stable(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> None:
    """Require the frozen object/configuration inventory to be byte-stable."""
    expected_value = dict(expected)
    actual_value = dict(actual)
    expected_value.pop("captured_at", None)
    actual_value.pop("captured_at", None)
    if isinstance(actual_value.get("objects"), list):
        actual_records = [_record_from_dict(item) for item in actual_value["objects"]]
        actual_value["objects"] = [
            record.snapshot_dict()
            for record in sorted(actual_records, key=_record_sort)
        ]
    if _canonical(expected_value) != _canonical(actual_value):
        raise RetirementError("source inventory or configuration changed after freeze")


def purge_targets(snapshot: Mapping[str, Any]) -> tuple[ObjectRecord, ...]:
    records = _snapshot_records(snapshot)
    targets = tuple(
        sorted(
            (
                record
                for record in records
                if record.bucket in OLD_BUCKETS
                and record.key not in MANAGED_OLD_OBJECTS[record.bucket]
            ),
            key=_record_sort,
        )
    )
    if any(record.delete_marker or record.version_id != "null" for record in targets):
        raise RetirementError("purge target is not an exact unversioned object")
    return targets


def _archive_key(record: ObjectRecord) -> str:
    identity = "\0".join((record.bucket, record.key, record.version_id))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{ARCHIVE_PREFIX}objects/{digest}"


def _snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    value = dict(snapshot)
    value.pop("captured_at", None)
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def archive_manifest_key(snapshot: Mapping[str, Any]) -> str:
    return f"{ARCHIVE_PREFIX}manifest-{_snapshot_digest(snapshot)}.json"


def _destination_ready(aws: GuardedAWS, kms_key_id: str) -> None:
    versioning = _s3(aws, "get_bucket_versioning", Bucket=STATE_BUCKET)
    if versioning.get("Status") != "Enabled":
        raise RetirementError("archive destination is not versioned")
    public = _s3(aws, "get_public_access_block", Bucket=STATE_BUCKET)
    config = _mapping(
        public.get("PublicAccessBlockConfiguration"), "public access configuration"
    )
    if not all(
        config.get(key) is True
        for key in (
            "BlockPublicAcls",
            "BlockPublicPolicy",
            "IgnorePublicAcls",
            "RestrictPublicBuckets",
        )
    ):
        raise RetirementError("archive destination is public")
    encryption = _s3(aws, "get_bucket_encryption", Bucket=STATE_BUCKET)
    encryption_config = _mapping(
        encryption.get("ServerSideEncryptionConfiguration", {}),
        "archive encryption configuration",
    )
    rules = _list(encryption_config.get("Rules", []), "archive encryption rules")
    if len(rules) != 1:
        raise RetirementError("archive destination encryption is ambiguous")
    default = _mapping(
        _mapping(rules[0], "archive encryption rule").get(
            "ApplyServerSideEncryptionByDefault", {}
        ),
        "archive encryption default",
    )
    if (
        default.get("SSEAlgorithm") != "aws:kms"
        or default.get("KMSMasterKeyID") != kms_key_id
    ):
        raise RetirementError("archive destination CMK is not the retained state CMK")
    ownership = _s3(aws, "get_bucket_ownership_controls", Bucket=STATE_BUCKET)
    ownership_config = _mapping(
        ownership.get("OwnershipControls", {}), "archive ownership controls"
    )
    owner_rules = ownership_config.get("Rules", [])
    if owner_rules != [{"ObjectOwnership": "BucketOwnerEnforced"}]:
        raise RetirementError("archive destination ownership is not enforced")
    policy_status = _s3(aws, "get_bucket_policy_status", Bucket=STATE_BUCKET)
    policy = _mapping(policy_status.get("PolicyStatus", {}), "archive policy status")
    if policy.get("IsPublic") is not False:
        raise RetirementError("archive destination policy is public or unknown")


def _archive_item(
    aws: GuardedAWS, record: ObjectRecord, kms_key_id: str
) -> dict[str, Any]:
    if record.delete_marker:
        return {
            **record.as_dict(),
            "archive_key": None,
            "archive_version_id": None,
            "archive_etag": None,
            "archive_size": None,
            "archive_sha256": None,
            "archived_delete_marker": True,
        }
    archive_key = _archive_key(record)
    copy_parameters: dict[str, Any] = {
        "Bucket": STATE_BUCKET,
        "Key": archive_key,
        "CopySource": {
            "Bucket": record.bucket,
            "Key": record.key,
            **_version_params(record.version_id),
        },
        "CopySourceIfMatch": _text(record.etag, "source ETag"),
        "MetadataDirective": "COPY",
        "TaggingDirective": "COPY",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": kms_key_id,
        "ExpectedSourceBucketOwner": EXPECTED_OWNER,
    }
    for name, value in (
        ("ContentType", record.content_type),
        ("ContentEncoding", record.content_encoding),
        ("CacheControl", record.cache_control),
        ("ContentDisposition", record.content_disposition),
        ("WebsiteRedirectLocation", record.website_redirect_location),
    ):
        if value is not None:
            copy_parameters[name] = value
    expires = _expires_value(record.expires)
    if expires is not None:
        copy_parameters["Expires"] = expires
    response = _s3(
        aws,
        "copy_object",
        **copy_parameters,
    )
    archive_version = _text(response.get("VersionId"), "archive VersionId")
    head = _s3(
        aws,
        "head_object",
        Bucket=STATE_BUCKET,
        Key=archive_key,
        VersionId=archive_version,
    )
    if (
        head.get("ServerSideEncryption") != "aws:kms"
        or head.get("SSEKMSKeyId") != kms_key_id
    ):
        raise RetirementError(
            "archive object is not encrypted with the retained state CMK"
        )
    archive_etag = _text(head.get("ETag"), "archive ETag")
    archive_size = _required_int(head.get("ContentLength"), "archive ContentLength")
    if archive_size != record.size:
        raise RetirementError("archive object size changed")
    if _metadata(head) != record.metadata:
        raise RetirementError("archive metadata changed")
    if (
        _optional_text(head.get("ContentType"), "archive ContentType")
        != record.content_type
        or _optional_text(head.get("ContentEncoding"), "archive ContentEncoding")
        != record.content_encoding
        or _optional_text(head.get("CacheControl"), "archive CacheControl")
        != record.cache_control
        or _optional_text(head.get("ContentDisposition"), "archive ContentDisposition")
        != record.content_disposition
        or _optional_timestamp(head.get("Expires"), "archive Expires") != record.expires
        or _optional_text(
            head.get("WebsiteRedirectLocation"), "archive WebsiteRedirectLocation"
        )
        != record.website_redirect_location
    ):
        raise RetirementError("archive HTTP metadata changed")
    tag_response = _s3(
        aws,
        "get_object_tagging",
        Bucket=STATE_BUCKET,
        Key=archive_key,
        VersionId=archive_version,
    )
    if _tags(tag_response) != record.tags:
        raise RetirementError("archive tags changed")
    body_response = _s3(
        aws,
        "get_object",
        Bucket=STATE_BUCKET,
        Key=archive_key,
        VersionId=archive_version,
    )
    archive_sha256 = _stream_digest(body_response.get("Body"))
    if archive_sha256 != record.sha256:
        raise RetirementError("archive plaintext digest changed")
    return {
        **record.as_dict(),
        "archive_key": archive_key,
        "archive_version_id": archive_version,
        "archive_etag": archive_etag,
        "archive_size": archive_size,
        "archive_sha256": archive_sha256,
        "archived_delete_marker": False,
    }


def archive_snapshot(
    aws: GuardedAWS,
    snapshot: Mapping[str, Any],
    kms_key_id: str,
    freeze_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy and readback every exact object/version before writing the KMS manifest."""
    if not kms_key_id:
        raise RetirementError("retained state CMK is required")
    if freeze_state is None:
        raise RetirementError("frozen writer evidence is required before archive")
    _require_freeze_evidence(aws, freeze_state)
    frozen = _snapshot_records(snapshot)
    current = capture_snapshot(aws)
    assert_snapshot_stable(snapshot, current)
    current_raw = capture_snapshot(aws, raw=True)
    assert_snapshot_stable(current, current_raw)
    raw_records = {
        (record.bucket, record.key, record.version_id): record
        for record in _snapshot_records(current_raw)
    }
    _destination_ready(aws, kms_key_id)
    try:
        archive_records = [
            raw_records[(record.bucket, record.key, record.version_id)]
            for record in frozen
        ]
    except KeyError as error:
        raise RetirementError("raw archive inventory is incomplete") from error
    archived = [_archive_item(aws, record, kms_key_id) for record in archive_records]
    manifest = {
        "manifest": "legacy-bucket-archive-v1",
        "account_id": PRODUCTION_ACCOUNT,
        "region": PRODUCTION_REGION,
        "source_snapshot_sha256": _snapshot_digest(snapshot),
        "state_bucket": STATE_BUCKET,
        "archive_prefix": ARCHIVE_PREFIX,
        "kms_key_id": kms_key_id,
        "objects": sorted(archived, key=_record_sort),
    }
    body = _canonical(manifest).encode("utf-8")
    manifest_key = archive_manifest_key(snapshot)
    response = _s3(
        aws,
        "put_object",
        Bucket=STATE_BUCKET,
        Key=manifest_key,
        Body=body,
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=kms_key_id,
    )
    version_id = _text(response.get("VersionId"), "archive manifest VersionId")
    head = _s3(
        aws, "head_object", Bucket=STATE_BUCKET, Key=manifest_key, VersionId=version_id
    )
    if (
        head.get("ServerSideEncryption") != "aws:kms"
        or head.get("SSEKMSKeyId") != kms_key_id
    ):
        raise RetirementError("archive manifest encryption is not verified")
    return {
        "manifest": manifest,
        "manifest_key": manifest_key,
        "manifest_version_id": version_id,
        "manifest_sha256": hashlib.sha256(body).hexdigest(),
    }


def _load_archive_manifest(
    aws: GuardedAWS,
    snapshot: Mapping[str, Any],
    kms_key_id: str,
    archive_state: Mapping[str, Any],
) -> dict[str, Any]:
    key = archive_manifest_key(snapshot)
    if (
        archive_state.get("manifest_key") != key
        or archive_state.get("source_snapshot_sha256") != _snapshot_digest(snapshot)
        or archive_state.get("kms_key_id") != kms_key_id
    ):
        raise RetirementError("archive manifest key evidence does not match snapshot")
    version_id = _text(
        archive_state.get("manifest_version_id"), "archive manifest VersionId"
    )
    expected_digest = _text(
        archive_state.get("manifest_sha256"), "archive manifest digest"
    )
    response_head = _s3(
        aws, "head_object", Bucket=STATE_BUCKET, Key=key, VersionId=version_id
    )
    if (
        response_head.get("ServerSideEncryption") != "aws:kms"
        or response_head.get("SSEKMSKeyId") != kms_key_id
    ):
        raise RetirementError("archive manifest encryption is not verified")
    response = _s3(
        aws, "get_object", Bucket=STATE_BUCKET, Key=key, VersionId=version_id
    )
    body = response.get("Body")
    if body is None or not hasattr(body, "read"):
        raise RetirementError("archive manifest is unreadable")
    try:
        raw = body.read()
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    if not isinstance(raw, bytes):
        raise RetirementError("archive manifest is unreadable")
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise RetirementError("archive manifest digest changed")
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise RetirementError("archive manifest is malformed") from error
    if not isinstance(parsed, dict):
        raise RetirementError("archive manifest is malformed")
    document = cast(dict[str, Any], parsed)
    if (
        document.get("manifest") != "legacy-bucket-archive-v1"
        or document.get("state_bucket") != STATE_BUCKET
        or document.get("archive_prefix") != ARCHIVE_PREFIX
        or document.get("kms_key_id") != kms_key_id
        or document.get("source_snapshot_sha256") != _snapshot_digest(snapshot)
        or not isinstance(document.get("objects"), list)
    ):
        raise RetirementError("archive manifest does not match frozen inventory")
    return document


def _verify_archive_objects(
    aws: GuardedAWS,
    snapshot: Mapping[str, Any],
    archive: Mapping[str, Any],
    kms_key_id: str,
) -> None:
    expected = {
        (record.bucket, record.key, record.version_id): record
        for record in _snapshot_records(snapshot)
    }
    raw_objects = _list(archive.get("objects"), "archive manifest objects")
    if len(raw_objects) != len(expected):
        raise RetirementError("archive manifest object inventory is incomplete")
    seen: set[tuple[str, str, str]] = set()
    for raw_item in raw_objects:
        raw_item = _mapping(raw_item, "archive manifest object")
        source = _record_from_dict(raw_item)
        identity = (source.bucket, source.key, source.version_id)
        if identity in seen or identity not in expected:
            raise RetirementError("archive manifest selected an unknown object/version")
        seen.add(identity)
        if _record_identity(source) != _record_identity(expected[identity]):
            raise RetirementError("archive manifest source metadata changed")
        if source.delete_marker:
            if (
                raw_item.get("archived_delete_marker") is not True
                or raw_item.get("archive_key") is not None
                or raw_item.get("archive_version_id") is not None
                or raw_item.get("archive_etag") is not None
                or raw_item.get("archive_size") is not None
                or raw_item.get("archive_sha256") is not None
            ):
                raise RetirementError("delete marker archive identity is invalid")
            continue
        archive_key = raw_item.get("archive_key")
        archive_version = raw_item.get("archive_version_id")
        if archive_key != _archive_key(source) or not isinstance(archive_version, str):
            raise RetirementError("archive object identity is invalid")
        archive_etag = _text(raw_item.get("archive_etag"), "archive ETag")
        archive_size = _required_int(raw_item.get("archive_size"), "archive size")
        archive_sha256 = _text(raw_item.get("archive_sha256"), "archive digest")
        head = _s3(
            aws,
            "head_object",
            Bucket=STATE_BUCKET,
            Key=archive_key,
            VersionId=archive_version,
        )
        if (
            head.get("ServerSideEncryption") != "aws:kms"
            or head.get("SSEKMSKeyId") != kms_key_id
        ):
            raise RetirementError("archive object readback metadata failed")
        if (
            head.get("ETag") != archive_etag
            or head.get("ContentLength") != archive_size
            or archive_size != source.size
            or _metadata(head) != source.metadata
            or _optional_text(head.get("ContentType"), "archive ContentType")
            != source.content_type
            or _optional_text(head.get("ContentEncoding"), "archive ContentEncoding")
            != source.content_encoding
            or _optional_text(head.get("CacheControl"), "archive CacheControl")
            != source.cache_control
            or _optional_text(
                head.get("ContentDisposition"), "archive ContentDisposition"
            )
            != source.content_disposition
            or _optional_timestamp(head.get("Expires"), "archive Expires")
            != source.expires
            or _optional_text(
                head.get("WebsiteRedirectLocation"),
                "archive WebsiteRedirectLocation",
            )
            != source.website_redirect_location
        ):
            raise RetirementError("archive object readback metadata failed")
        tag_response = _s3(
            aws,
            "get_object_tagging",
            Bucket=STATE_BUCKET,
            Key=archive_key,
            VersionId=archive_version,
        )
        if _tags(tag_response) != source.tags:
            raise RetirementError("archive object readback tags failed")
        body_response = _s3(
            aws,
            "get_object",
            Bucket=STATE_BUCKET,
            Key=archive_key,
            VersionId=archive_version,
        )
        readback_sha256 = _stream_digest(body_response.get("Body"))
        if readback_sha256 != source.sha256 or readback_sha256 != archive_sha256:
            raise RetirementError("archive object readback digest failed")
    if seen != set(expected):
        raise RetirementError("archive manifest omitted an object/version")


def _head_absent(aws: GuardedAWS, bucket: str, key: str) -> bool:
    try:
        _s3(aws, "head_object", Bucket=bucket, Key=key)
    except RetirementError as error:
        # GuardedAWS deliberately hides provider error bodies.  A HEAD failure
        # is therefore ambiguous unless the wrapped cause is the known 404.
        cause = error.__cause__
        if isinstance(cause, ClientError):
            raw_response: Any = cause.response  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            error_response = _mapping(raw_response, "S3 error response")
            error_details = _mapping(error_response.get("Error", {}), "S3 error")
            if error_details.get("Code") in ("404", "NoSuchKey", "NotFound"):
                return True
        raise RetirementError("post-delete HEAD is ambiguous") from error
    return False


def purge_snapshot(
    aws: GuardedAWS,
    snapshot: Mapping[str, Any],
    kms_key_id: str,
    freeze_state: Mapping[str, Any] | None = None,
    archive_state: Mapping[str, Any] | None = None,
) -> int:
    """Delete only frozen unmanaged objects using exact ETag and owner guards."""
    if freeze_state is None or archive_state is None:
        raise RetirementError("freeze and archive evidence are required before purge")
    _require_freeze_evidence(aws, freeze_state)
    archive = _load_archive_manifest(aws, snapshot, kms_key_id, archive_state)
    _verify_archive_objects(aws, snapshot, archive, kms_key_id)
    frozen_targets = purge_targets(snapshot)
    current = capture_snapshot(aws)
    assert_snapshot_stable(snapshot, current)
    for record in frozen_targets:
        try:
            _s3(
                aws,
                "delete_object",
                Bucket=record.bucket,
                Key=record.key,
                IfMatch=_text(record.etag, "target ETag"),
            )
        except RetirementError as error:
            raise RetirementError(
                "conditional purge failed; outcome is unknown"
            ) from error
        if not _head_absent(aws, record.bucket, record.key):
            raise RetirementError("conditional purge did not remove its exact object")
    return len(frozen_targets)


def verify_post_purge(
    aws: GuardedAWS,
    snapshot: Mapping[str, Any],
    kms_key_id: str,
    freeze_state: Mapping[str, Any] | None = None,
    archive_state: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    if freeze_state is None or archive_state is None:
        raise RetirementError("freeze and archive evidence are required before verify")
    _require_freeze_evidence(aws, freeze_state)
    frozen = _snapshot_records(snapshot)
    current = capture_snapshot(aws)
    expected_managed = {
        (record.bucket, record.key, record.version_id): _record_identity(record)
        for record in frozen
        if record.bucket in OLD_BUCKETS
        and record.key in MANAGED_OLD_OBJECTS[record.bucket]
    }
    actual_old = {
        (record.bucket, record.key, record.version_id): _record_identity(record)
        for record in _snapshot_records(current)
        if record.bucket in OLD_BUCKETS
    }
    if actual_old != expected_managed:
        raise RetirementError(
            "managed old objects are missing or unmanaged objects remain"
        )
    expected_shared = {
        (record.bucket, record.key, record.version_id): _record_identity(record)
        for record in frozen
        if record.bucket == SHARED_ARTIFACT_BUCKET
    }
    actual_shared = {
        (record.bucket, record.key, record.version_id): _record_identity(record)
        for record in _snapshot_records(current)
        if record.bucket == SHARED_ARTIFACT_BUCKET
    }
    if actual_shared != expected_shared:
        raise RetirementError("shared key version inventory changed")
    archive = _load_archive_manifest(aws, snapshot, kms_key_id, archive_state)
    _verify_archive_objects(aws, snapshot, archive, kms_key_id)
    return {
        "managed_old_objects": len(expected_managed),
        "shared_versions": len(expected_shared),
        "unmanaged_purged": len(frozen) - len(expected_managed) - len(expected_shared),
    }


def _waf_configuration(aws: GuardedAWS) -> dict[str, Any]:
    response = aws.call("wafv2", "list_web_acls", Scope="CLOUDFRONT")
    items = _list(response.get("WebACLs", []), "WAF ACL inventory")
    matches: list[Mapping[str, Any]] = []
    for item in items:
        candidate = _mapping(item, "WAF ACL")
        if candidate.get("Name") == WAF_NAME:
            matches.append(candidate)
    if len(matches) != 1:
        raise RetirementError("exact WAF ACL is not unique")
    arn = _text(matches[0].get("ARN"), "WAF ARN")
    if f":{PRODUCTION_ACCOUNT}:" not in arn:
        raise RetirementError("WAF ARN account mismatch")
    response = aws.call("wafv2", "get_logging_configuration", ResourceArn=arn)
    config = response.get("LoggingConfiguration")
    config = _mapping(config, "WAF logging configuration")
    if config.get("ResourceArn") != arn:
        raise RetirementError("WAF logging configuration is unreadable")
    return _jsonable(config)


def _lifecycle_configuration(aws: GuardedAWS) -> dict[str, Any]:
    response = _s3(aws, "get_bucket_lifecycle_configuration", Bucket=MEASUREMENT_BUCKET)
    if not isinstance(response.get("Rules"), list):
        raise RetirementError("measurement lifecycle configuration is unreadable")
    response = dict(response)
    response.pop("ResponseMetadata", None)
    return _jsonable(response)


def writer_state(aws: GuardedAWS) -> dict[str, Any]:
    functions: list[dict[str, Any]] = []
    for name, timeout in LAMBDA_WRITERS:
        config_response = aws.call(
            "lambda", "get_function_configuration", FunctionName=name
        )
        config = dict(config_response)
        if config.get("FunctionName") != name or config.get("Timeout") != timeout:
            raise RetirementError("Lambda writer identity or timeout changed")
        arn = _text(config.get("FunctionArn"), "Lambda ARN")
        if f":{PRODUCTION_ACCOUNT}:" not in arn or f":{PRODUCTION_REGION}:" not in arn:
            raise RetirementError("Lambda writer ARN scope changed")
        concurrency = aws.call("lambda", "get_function_concurrency", FunctionName=name)
        functions.append(
            {
                "name": name,
                "timeout": timeout,
                "configuration_sha256": hashlib.sha256(
                    _canonical(config).encode("utf-8")
                ).hexdigest(),
                "concurrency": _jsonable(concurrency),
            }
        )
    return {
        "functions": functions,
        "waf": _waf_configuration(aws),
        "lifecycle": _lifecycle_configuration(aws),
    }


def _waf_request(config: Mapping[str, Any]) -> dict[str, Any]:
    mutable = {
        "ResourceArn",
        "LogDestinationConfigs",
        "LoggingFilter",
        "RedactedFields",
    }
    readonly = {"ManagedByFirewallManager", "LogType", "LogScope"}
    unknown = set(config) - mutable - readonly - {"ResponseMetadata"}
    if unknown or not mutable.issubset(config):
        raise RetirementError("WAF configuration contains an unknown or missing field")
    return {
        key: copy.deepcopy(config[key]) for key in mutable | readonly if key in config
    }


def _change_waf_filter(config: Mapping[str, Any]) -> dict[str, Any]:
    changed = copy.deepcopy(dict(config))
    logging_filter = _mapping(changed.get("LoggingFilter"), "WAF logging filter")
    if logging_filter.get("DefaultBehavior") != "DROP":
        raise RetirementError("WAF default behavior is not the reviewed DROP")
    filters = _list(logging_filter.get("Filters"), "WAF filters")
    matches: list[dict[str, Any]] = []
    for item in filters:
        item_mapping = _mapping(item, "WAF filter")
        item = cast(dict[str, Any], item_mapping)
        conditions = _list(item.get("Conditions"), "WAF filter conditions")
        if any(
            _mapping(condition, "WAF filter condition").get("LabelNameCondition")
            and _mapping(
                _mapping(condition, "WAF filter condition").get("LabelNameCondition"),
                "WAF label condition",
            ).get("LabelName")
            == WAF_AGENT_LABEL
            for condition in conditions
        ):
            matches.append(item)
    if len(matches) != 1 or matches[0].get("Behavior") != "KEEP":
        raise RetirementError("exact WAF agent filter is not the reviewed KEEP filter")
    matches[0]["Behavior"] = "DROP"
    return changed


def _lifecycle_request(config: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"Rules", "TransitionDefaultMinimumObjectSize"}
    unknown = set(config) - allowed - {"ResponseMetadata"}
    rules = config.get("Rules")
    if unknown or not isinstance(rules, list):
        raise RetirementError("lifecycle configuration contains an unknown field")
    request: dict[str, Any] = {
        "LifecycleConfiguration": {
            "Rules": copy.deepcopy(cast(list[dict[str, Any]], rules))
        }
    }
    if "TransitionDefaultMinimumObjectSize" in config:
        request["TransitionDefaultMinimumObjectSize"] = copy.deepcopy(
            config["TransitionDefaultMinimumObjectSize"]
        )
    return request


def _disable_lifecycle(config: Mapping[str, Any]) -> dict[str, Any]:
    changed = copy.deepcopy(dict(config))
    rules = _list(changed.get("Rules"), "lifecycle rules")
    ids = {"expire-raw-waf-logs", "expire-athena-results"}
    matches: list[dict[str, Any]] = []
    for raw_rule in rules:
        rule = cast(dict[str, Any], _mapping(raw_rule, "lifecycle rule"))
        if rule.get("ID") in ids:
            matches.append(rule)
    if len(matches) != 2 or {rule["ID"] for rule in matches} != ids:
        raise RetirementError("exact measurement lifecycle rules are not present")
    if any(rule.get("Status") != "Enabled" for rule in matches):
        raise RetirementError("measurement lifecycle rule is not currently Enabled")
    for rule in matches:
        rule["Status"] = "Disabled"
    return changed


def _verify_frozen_writers(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    before_functions: dict[str, Mapping[str, Any]] = {}
    for raw in _list(before.get("functions"), "writer functions"):
        item = _mapping(raw, "writer function")
        name = _text(item.get("name"), "writer function name")
        if name in before_functions:
            raise RetirementError("Lambda writer set contains a duplicate")
        before_functions[name] = item
    after_functions: dict[str, Mapping[str, Any]] = {}
    for raw in _list(after.get("functions"), "writer functions"):
        item = _mapping(raw, "writer function")
        name = _text(item.get("name"), "writer function name")
        if name in after_functions:
            raise RetirementError("Lambda writer set contains a duplicate")
        after_functions[name] = item
    if set(before_functions) != {name for name, _ in LAMBDA_WRITERS} or set(
        after_functions
    ) != set(before_functions):
        raise RetirementError("Lambda writer set changed")
    for name, item in before_functions.items():
        current = after_functions[name]
        if current.get("configuration_sha256") != item.get("configuration_sha256"):
            raise RetirementError("Lambda configuration changed outside concurrency")
        concurrency = _mapping(current.get("concurrency"), "writer concurrency")
        if concurrency.get("ReservedConcurrentExecutions") != 0:
            raise RetirementError("Lambda writer is not frozen")
    before_waf = _mapping(before.get("waf"), "WAF freeze baseline")
    after_waf = _mapping(after.get("waf"), "WAF freeze result")
    expected_waf = _change_waf_filter(before_waf)
    if after_waf != expected_waf:
        raise RetirementError("WAF drift is broader than the approved filter change")
    before_lifecycle = _mapping(before.get("lifecycle"), "lifecycle freeze baseline")
    expected_lifecycle = _disable_lifecycle(before_lifecycle)
    if after.get("lifecycle") != expected_lifecycle:
        raise RetirementError(
            "lifecycle drift is broader than the approved rule changes"
        )


def _require_freeze_evidence(aws: GuardedAWS, freeze_state: Mapping[str, Any]) -> None:
    if freeze_state.get("drain_seconds") != DRAIN_SECONDS:
        raise RetirementError(
            "writer freeze evidence does not prove the 900-second drain"
        )
    completed_at = freeze_state.get("drain_completed_at")
    completed_monotonic = freeze_state.get("freeze_completed_monotonic")
    if not isinstance(completed_at, str) or not isinstance(
        completed_monotonic, (int, float)
    ):
        raise RetirementError("writer freeze completion time is missing")
    if time.monotonic() - completed_monotonic < DRAIN_SECONDS:
        raise RetirementError("writer freeze has not completed the 900-second drain")
    try:
        completed_datetime = datetime.fromisoformat(completed_at)
    except ValueError as error:
        raise RetirementError("writer freeze completion time is malformed") from error
    if completed_datetime.tzinfo is None:
        raise RetirementError("writer freeze completion time has no timezone")
    before = _mapping(freeze_state.get("before"), "writer freeze baseline")
    _verify_frozen_writers(before, writer_state(aws))
    _athena_idle(aws)


def _athena_idle(aws: GuardedAWS) -> None:
    workgroup = aws.call("athena", "get_work_group", WorkGroup=ATHENA_WORKGROUP)
    workgroup_details = _mapping(workgroup.get("WorkGroup", {}), "Athena workgroup")
    actual = workgroup_details.get("Name")
    if actual != ATHENA_WORKGROUP:
        raise RetirementError("Athena workgroup identity changed")
    token: str | None = None
    while True:
        params: dict[str, Any] = {"WorkGroup": ATHENA_WORKGROUP}
        if token is not None:
            params["NextToken"] = token
        response = aws.call("athena", "list_query_executions", **params)
        ids = _list(response.get("QueryExecutionIds", []), "Athena query IDs")
        query_ids: list[str] = []
        for item in ids:
            if not isinstance(item, str) or not item:
                raise RetirementError("Athena query inventory is malformed")
            query_ids.append(item)
        if not query_ids:
            query_ids = []
        for query_id in query_ids:
            status_response = aws.call(
                "athena", "get_query_execution", QueryExecutionId=query_id
            )
            query = _mapping(status_response.get("QueryExecution", {}), "Athena query")
            status = _mapping(query.get("Status", {}), "Athena query status")
            state = status.get("State")
            if state in {"QUEUED", "RUNNING"}:
                raise RetirementError("Athena workgroup is not idle")
            if state not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                raise RetirementError("Athena query state is unknown")
        if response.get("NextToken") in (None, ""):
            return
        token = _text(response.get("NextToken"), "Athena NextToken")


def freeze_writers(
    aws: GuardedAWS,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    before = writer_state(aws)
    for name, _ in LAMBDA_WRITERS:
        aws.call(
            "lambda",
            "put_function_concurrency",
            FunctionName=name,
            ReservedConcurrentExecutions=0,
        )
    changed_waf = _change_waf_filter(before["waf"])
    aws.call(
        "wafv2",
        "put_logging_configuration",
        LoggingConfiguration=_waf_request(changed_waf),
    )
    changed_lifecycle = _disable_lifecycle(before["lifecycle"])
    request = _lifecycle_request(changed_lifecycle)
    request["Bucket"] = MEASUREMENT_BUCKET
    _s3(aws, "put_bucket_lifecycle_configuration", **request)
    freeze_completed = clock()
    sleep(DRAIN_SECONDS)
    _athena_idle(aws)
    after = writer_state(aws)
    _verify_frozen_writers(before, after)
    return {
        "before": before,
        "after": after,
        "drain_seconds": DRAIN_SECONDS,
        "freeze_completed_monotonic": freeze_completed,
        "drain_completed_at": datetime.now(UTC).isoformat(),
    }


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_jsonable(value), handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RetirementError("private evidence file is unreadable") from error
    if not isinstance(document, dict):
        raise RetirementError("private evidence file is malformed")
    return cast(dict[str, Any], document)


def _validate_execution_evidence(
    identity_path: Path, mapping_path: Path
) -> dict[str, str]:
    identity = _read_json(identity_path)
    if (
        identity.get("manifest") != EXPECTED_IDENTITY_MANIFEST
        or identity.get("account_id") != PRODUCTION_ACCOUNT
        or identity.get("source_remote") not in EXPECTED_SOURCE_REMOTES
        or identity.get("source_commit") != EXPECTED_SOURCE_COMMIT
        or identity.get("identity_source") != EXPECTED_IDENTITY_SOURCE
        or not isinstance(identity.get("resources"), list)
        or len(identity["resources"]) != 166
    ):
        raise RetirementError("fresh 166-entry identity evidence is not bound")
    identity_rows = _list(identity.get("resources"), "identity resources")
    identities: set[str] = set()
    for item in identity_rows:
        item = _mapping(item, "identity evidence")
        address = item.get("address")
        if not isinstance(address, str) or not address or address in identities:
            raise RetirementError(
                "identity evidence has duplicate or missing addresses"
            )
        if item.get("account_id") != PRODUCTION_ACCOUNT:
            raise RetirementError("identity evidence account mismatch")
        identities.add(address)

    mapping = _read_json(mapping_path)
    rows = _list(mapping.get("rows"), "object mapping rows")
    if mapping.get("total") != 25 or len(rows) != 25:
        raise RetirementError("fresh 25-object mapping evidence is not bound")
    expected_rows = {
        (bucket, key) for bucket, keys in MANAGED_OLD_OBJECTS.items() for key in keys
    } | {(SHARED_ARTIFACT_BUCKET, key) for key in SHARED_KEYS}
    actual_rows: set[tuple[str, str]] = set()
    for item in rows:
        item = _mapping(item, "object mapping evidence")
        bucket = item.get("bucket")
        key = item.get("key")
        if not isinstance(bucket, str) or not isinstance(key, str):
            raise RetirementError("object mapping evidence is malformed")
        actual_rows.add((bucket, key))
    if actual_rows != expected_rows:
        raise RetirementError("object mapping evidence widened or omitted scope")
    return {
        "identity_sha256": hashlib.sha256(identity_path.read_bytes()).hexdigest(),
        "mapping_sha256": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
    }


def _archive_state(document: Mapping[str, Any]) -> dict[str, Any]:
    required = ("manifest_key", "manifest_version_id", "manifest_sha256")
    if any(not isinstance(document.get(key), str) for key in required):
        raise RetirementError("exact archive manifest evidence is missing")
    return dict(document)


def _require_archive_evidence_binding(
    archive_state: Mapping[str, Any], evidence: Mapping[str, str]
) -> None:
    for name in ("identity_sha256", "mapping_sha256"):
        if archive_state.get(name) != evidence.get(name):
            raise RetirementError("archive state is bound to different live evidence")


def _summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    records = _snapshot_records(snapshot)
    counts: dict[str, int] = {}
    for record in records:
        counts[record.bucket] = counts.get(record.bucket, 0) + 1
    return {
        "manifest": snapshot["manifest"],
        "status": "pass",
        "account_id": PRODUCTION_ACCOUNT,
        "region": PRODUCTION_REGION,
        "objects": len(records),
        "counts": counts,
        "managed_old_objects": HISTORICAL_MANAGED_OLD_COUNT,
        "historical_unmanaged_objects": HISTORICAL_UNMANAGED_COUNT,
        "historical_shared_versions": HISTORICAL_SHARED_VERSION_COUNT,
        "snapshot_sha256": _snapshot_digest(snapshot),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("capture", "freeze", "archive", "purge", "verify"),
        default="capture",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--freeze-state", type=Path)
    parser.add_argument("--archive-state", type=Path)
    parser.add_argument("--identity-manifest", type=Path)
    parser.add_argument("--managed-object-mapping", type=Path)
    parser.add_argument("--state-kms-key-id")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.phase in {"freeze", "archive", "purge"} and not args.execute:
            raise RetirementError("mutation phase requires the reviewed --execute flag")
        evidence: dict[str, str] = {}
        if args.phase != "capture":
            if args.identity_manifest is None or args.managed_object_mapping is None:
                raise RetirementError(
                    "fresh identity and object mapping evidence are required"
                )
            evidence = _validate_execution_evidence(
                args.identity_manifest, args.managed_object_mapping
            )
        aws = GuardedAWS.live()
        if args.phase == "capture":
            snapshot = capture_snapshot(aws)
            if args.output is not None:
                _write_private(args.output, snapshot)
            print(json.dumps(_summary(snapshot), sort_keys=True, separators=(",", ":")))
            return 0
        if args.snapshot is None:
            raise RetirementError("--snapshot is required for this phase")
        snapshot = _read_json(args.snapshot)
        if args.phase == "freeze":
            if args.output is None or args.freeze_state is None:
                raise RetirementError(
                    "--output and --freeze-state are required for freeze evidence"
                )
            assert_snapshot_stable(snapshot, capture_snapshot(aws))
            state = freeze_writers(aws)
            frozen_snapshot = capture_snapshot(aws)
            _write_private(args.output, frozen_snapshot)
            _write_private(args.freeze_state, state)
            print(
                json.dumps(
                    _summary(frozen_snapshot), sort_keys=True, separators=(",", ":")
                )
            )
            return 0
        kms_key_id = _text(args.state_kms_key_id, "state CMK")
        if args.freeze_state is None or args.archive_state is None:
            raise RetirementError("freeze and archive evidence paths are required")
        freeze_state = _read_json(args.freeze_state)
        if args.phase == "archive":
            result = archive_snapshot(aws, snapshot, kms_key_id, freeze_state)
            _write_private(
                args.archive_state,
                {
                    "manifest_key": result["manifest_key"],
                    "manifest_version_id": result["manifest_version_id"],
                    "manifest_sha256": result["manifest_sha256"],
                    "source_snapshot_sha256": _snapshot_digest(snapshot),
                    "kms_key_id": kms_key_id,
                    **evidence,
                },
            )
            print(
                json.dumps(
                    {"status": "pass", "manifest_key": result["manifest_key"]},
                    separators=(",", ":"),
                )
            )
            return 0
        if args.phase == "purge":
            archive_state = _archive_state(_read_json(args.archive_state))
            _require_archive_evidence_binding(archive_state, evidence)
            count = purge_snapshot(
                aws, snapshot, kms_key_id, freeze_state, archive_state
            )
            print(
                json.dumps({"status": "pass", "purged": count}, separators=(",", ":"))
            )
            return 0
        if args.phase == "verify":
            archive_state = _archive_state(_read_json(args.archive_state))
            _require_archive_evidence_binding(archive_state, evidence)
            result = verify_post_purge(
                aws, snapshot, kms_key_id, freeze_state, archive_state
            )
            print(json.dumps({"status": "pass", **result}, separators=(",", ":")))
            return 0
        raise RetirementError("unsupported phase")
    except RetirementError:
        print("legacy bucket retirement rejected", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
