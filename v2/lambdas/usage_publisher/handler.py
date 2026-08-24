"""Publish cumulative, non-identifying TollChat usage as static JSON."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol, cast

import boto3

_AGGREGATE_KEY = "usage#all"


class _DynamoDbClient(Protocol):
    def get_item(self, **kwargs: object) -> dict[str, object]: ...


class _S3Client(Protocol):
    def put_object(self, **kwargs: object) -> object: ...


def _string_attribute(item: Mapping[object, object], name: str, kind: str) -> str:
    attribute_raw = item.get(name)
    if not isinstance(attribute_raw, Mapping):
        raise ValueError
    attribute = cast(Mapping[object, object], attribute_raw)
    value = attribute.get(kind)
    if not isinstance(value, str):
        raise ValueError
    return value


def _usage_aggregate(item: object) -> tuple[int, int, datetime]:
    if not isinstance(item, Mapping):
        raise ValueError("usage aggregate is missing")
    attributes = cast(Mapping[object, object], item)
    try:
        engaged_raw = _string_attribute(attributes, "engaged_sessions", "N")
        completed_raw = _string_attribute(attributes, "completed_responses", "N")
        started_raw = _string_attribute(attributes, "collection_started_at", "S")
        if not engaged_raw.isdigit() or not completed_raw.isdigit():
            raise ValueError
        started = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
        if started.tzinfo is None:
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("usage aggregate is malformed") from error
    return int(engaged_raw), int(completed_raw), started


def publish_usage(
    *,
    dynamodb: _DynamoDbClient,
    s3: _S3Client,
    table_name: str,
    bucket: str,
    kms_key_arn: str,
    now: datetime,
) -> dict[str, object] | None:
    """Read the permanent aggregate and replace the public static snapshot."""
    if now.tzinfo is None:
        raise ValueError("publication time must include a timezone")
    response = dynamodb.get_item(
        TableName=table_name,
        Key={"credential_hash": {"S": _AGGREGATE_KEY}},
        ConsistentRead=True,
    )
    if "Item" not in response:
        return None
    engaged, completed, started = _usage_aggregate(response["Item"])
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "collection_started_on": started.date().isoformat(),
        "as_of": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "engaged_sessions": engaged,
        "completed_responses": completed,
    }
    s3.put_object(
        Bucket=bucket,
        Key="usage.json",
        Body=json.dumps(snapshot, separators=(",", ":")).encode(),
        ContentType="application/json; charset=utf-8",
        CacheControl="no-cache",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=kms_key_arn,
    )
    return snapshot


def handler(event: object, context: object) -> dict[str, object] | None:
    del event, context
    return publish_usage(
        dynamodb=cast(
            _DynamoDbClient,
            boto3.client("dynamodb"),  # pyright: ignore[reportUnknownMemberType]
        ),
        s3=cast(
            _S3Client,
            boto3.client("s3"),  # pyright: ignore[reportUnknownMemberType]
        ),
        table_name=os.environ["SESSION_TABLE_NAME"],
        bucket=os.environ["SITE_BUCKET_NAME"],
        kms_key_arn=os.environ["SITE_KMS_KEY_ARN"],
        now=datetime.now(UTC),
    )
