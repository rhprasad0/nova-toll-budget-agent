import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

Attribute = dict[str, str]
Item = dict[str, Attribute]

HANDLER_PATH = Path(__file__).resolve().parents[1] / "handler.py"
SPEC = importlib.util.spec_from_file_location("usage_publisher_handler", HANDLER_PATH)
assert SPEC and SPEC.loader
handler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handler)


class DynamoDb:
    def __init__(self, item: Item | None) -> None:
        self.item = item
        self.calls: list[dict[str, object]] = []

    def get_item(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"Item": self.item} if self.item is not None else {}


class S3:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def aggregate(**overrides: Attribute) -> Item:
    values: Item = {
        "credential_hash": {"S": "usage#all"},
        "engaged_sessions": {"N": "12"},
        "completed_responses": {"N": "34"},
        "collection_started_at": {"S": "2026-08-24T15:00:00Z"},
        "updated_at": {"S": "2026-08-24T16:00:00Z"},
    }
    values.update(overrides)
    return values


def test_publish_writes_exact_static_snapshot_and_metadata():
    dynamodb = DynamoDb(aggregate())
    s3 = S3()

    snapshot = handler.publish_usage(
        dynamodb=dynamodb,
        s3=s3,
        table_name="sessions",
        bucket="site",
        kms_key_arn="kms-arn",
        now=datetime(2026, 8, 25, 5, 15, tzinfo=UTC),
    )

    assert snapshot == {
        "schema_version": 1,
        "collection_started_on": "2026-08-24",
        "as_of": "2026-08-25T05:15:00Z",
        "engaged_sessions": 12,
        "completed_responses": 34,
    }
    assert dynamodb.calls == [
        {
            "TableName": "sessions",
            "Key": {"credential_hash": {"S": "usage#all"}},
            "ConsistentRead": True,
        }
    ]
    request = s3.calls[0]
    assert request["Bucket"] == "site"
    assert request["Key"] == "usage.json"
    assert request["ContentType"] == "application/json; charset=utf-8"
    assert request["CacheControl"] == "no-cache"
    assert request["ServerSideEncryption"] == "aws:kms"
    assert request["SSEKMSKeyId"] == "kms-arn"
    body = request["Body"]
    assert isinstance(body, bytes | bytearray | str)
    assert json.loads(body) == snapshot


def test_publish_is_a_noop_before_the_first_counted_session() -> None:
    s3 = S3()

    assert (
        handler.publish_usage(
            dynamodb=DynamoDb(None),
            s3=s3,
            table_name="sessions",
            bucket="site",
            kms_key_arn="kms-arn",
            now=datetime(2026, 8, 25, 5, 15, tzinfo=UTC),
        )
        is None
    )
    assert s3.calls == []


@pytest.mark.parametrize(
    "item",
    [
        aggregate(engaged_sessions={"N": "-1"}),
        aggregate(completed_responses={"N": "1.5"}),
        aggregate(collection_started_at={"S": "not-a-date"}),
    ],
)
def test_publish_fails_closed_for_malformed_aggregate(item: Item) -> None:
    with pytest.raises(ValueError, match="usage aggregate"):
        handler.publish_usage(
            dynamodb=DynamoDb(item),
            s3=S3(),
            table_name="sessions",
            bucket="site",
            kms_key_arn="kms-arn",
            now=datetime(2026, 8, 25, 5, 15, tzinfo=UTC),
        )
