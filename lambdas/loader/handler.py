"""toll-loader Lambda: S3 ObjectCreated -> parse -> idempotent upsert into RDS.

psycopg is only present in the deployed zip, not the dev/test venv, so the
connection is built with a lazy import inside _connect() -- everything else
here (routing, parsing) must stay importable without it.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
import urllib.parse
from typing import Any, LiteralString, cast

import boto3
from parse_csv import I95Row, parse_trip_pricing_csv
from parse_xml import I66Row, parse_trip_pricing_xml

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_RAW_OBJECT_BYTES = 5 * 1024 * 1024
_RAW_KEY_PATTERN = re.compile(
    r"raw/feed=(?P<feed>i95|i66)/date=\d{4}-\d{2}-\d{2}/\d{4}Z"
    r"(?:-[a-f0-9]{16})?\.(?:csv|xml)\Z"
)

# RDS CA bundle is dropped into the deployment zip next to this file by the
# Terraform/build step (WP1) -- verify-full needs it to authenticate the
# server, not just encrypt the connection.
CA_BUNDLE_PATH = os.path.join(os.path.dirname(__file__), "rds-ca-bundle.pem")

UPSERT_I95_SQL = """
INSERT INTO trip_pricing_i95 (
    interval_end_at,
    current_at,
    calculated_at,
    corridor_id,
    corridor_name,
    od_pair_id,
    od_pair_name,
    start_zone_id,
    start_zone_name,
    end_zone_id,
    end_zone_name,
    zone_toll_rate_usd,
    link_status,
    s3_key
) VALUES (
    %(interval_end_at)s,
    %(current_at)s,
    %(calculated_at)s,
    %(corridor_id)s,
    %(corridor_name)s,
    %(od_pair_id)s,
    %(od_pair_name)s,
    %(start_zone_id)s,
    %(start_zone_name)s,
    %(end_zone_id)s,
    %(end_zone_name)s,
    %(zone_toll_rate_usd)s,
    %(link_status)s,
    %(s3_key)s
)
ON CONFLICT (interval_end_at, start_zone_id, end_zone_id, od_pair_id) DO UPDATE
SET
    current_at = EXCLUDED.current_at,
    calculated_at = EXCLUDED.calculated_at,
    corridor_id = EXCLUDED.corridor_id,
    corridor_name = EXCLUDED.corridor_name,
    od_pair_name = EXCLUDED.od_pair_name,
    start_zone_name = EXCLUDED.start_zone_name,
    end_zone_name = EXCLUDED.end_zone_name,
    zone_toll_rate_usd = EXCLUDED.zone_toll_rate_usd,
    link_status = EXCLUDED.link_status,
    s3_key = EXCLUDED.s3_key -- gitleaks:allow (not a secret; Postgres EXCLUDED pseudo-table)
"""

UPSERT_I66_SQL = """
INSERT INTO trip_pricing_i66 (
    interval_start_at,
    interval_end_at,
    calculated_at,
    corridor_id,
    corridor_name,
    start_zone_id,
    start_zone_name,
    end_zone_id,
    end_zone_name,
    zone_toll_rate_usd,
    s3_key
) VALUES (
    %(interval_start_at)s,
    %(interval_end_at)s,
    %(calculated_at)s,
    %(corridor_id)s,
    %(corridor_name)s,
    %(start_zone_id)s,
    %(start_zone_name)s,
    %(end_zone_id)s,
    %(end_zone_name)s,
    %(zone_toll_rate_usd)s,
    %(s3_key)s
)
ON CONFLICT (interval_end_at, start_zone_id, end_zone_id) DO UPDATE
SET
    interval_start_at = EXCLUDED.interval_start_at,
    calculated_at = EXCLUDED.calculated_at,
    corridor_id = EXCLUDED.corridor_id,
    corridor_name = EXCLUDED.corridor_name,
    start_zone_name = EXCLUDED.start_zone_name,
    end_zone_name = EXCLUDED.end_zone_name,
    zone_toll_rate_usd = EXCLUDED.zone_toll_rate_usd,
    s3_key = EXCLUDED.s3_key -- gitleaks:allow (not a secret; Postgres EXCLUDED pseudo-table)
"""

# feed -> (parser, upsert SQL). Mirrors the fetcher's FEEDS dict -- one place
# to look for how a feed is routed end to end.
_FEED_CONFIG: dict[str, tuple[Any, str]] = {
    "i95": (parse_trip_pricing_csv, UPSERT_I95_SQL),
    "i66": (parse_trip_pricing_xml, UPSERT_I66_SQL),
}


def _feed_from_key(key: str) -> str:
    """raw/feed=i95/date=2026-07-21/1440Z.csv -> "i95"."""
    match = _RAW_KEY_PATTERN.fullmatch(key)
    if not match:
        raise ValueError(f"unsupported raw object key: {key}")
    feed = match["feed"]
    expected_extension = {"i95": "csv", "i66": "xml"}[feed]
    if not key.endswith(f".{expected_extension}"):
        raise ValueError(f"unexpected extension for feed {feed}: {key}")
    return feed


def _validate_record(bucket: str, key: str, size: object) -> str:
    """Fail closed before downloading an S3 event payload."""
    if bucket != os.environ["RAW_BUCKET"]:
        raise ValueError(f"unexpected source bucket: {bucket}")
    feed = _feed_from_key(key)
    if isinstance(size, bool) or not isinstance(size, (str, int)):
        raise TypeError(f"invalid S3 object size for {key}")
    try:
        size_int = int(size)
    except ValueError as exc:
        raise ValueError(f"invalid S3 object size for {key}") from exc
    if size_int < 0 or size_int > MAX_RAW_OBJECT_BYTES:
        raise ValueError(f"raw object size outside allowed range for {key}: {size_int}")
    return feed


def _parse_payload(feed: str, body: str) -> list[I95Row] | list[I66Row]:
    if feed not in _FEED_CONFIG:
        raise ValueError(f"unknown feed: {feed}")
    parse_fn, _ = _FEED_CONFIG[feed]
    return parse_fn(body)


def _row_params(row: I95Row | I66Row, *, s3_key: str) -> dict[str, Any]:
    """Dataclass fields plus raw-object provenance."""
    params = dataclasses.asdict(row)
    params["s3_key"] = s3_key
    return params


def _connect(*, host: str, port: int, dbname: str, user: str) -> object:
    import psycopg  # type: ignore[import-not-found]  # deployed-zip-only dependency; see module docstring.

    rds = cast(Any, boto3.client("rds"))  # pyright: ignore[reportUnknownMemberType]
    token = cast(
        str,
        rds.generate_db_auth_token(DBHostname=host, Port=port, DBUsername=user),
    )
    return psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=token,
        sslmode="verify-full",
        sslrootcert=CA_BUNDLE_PATH,
    )


def _load(feed: str, rows: list[I95Row] | list[I66Row], *, s3_key: str) -> None:
    _, upsert_sql = _FEED_CONFIG[feed]

    conn = cast(
        Any,
        _connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ["DB_PORT"]),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
        ),
    )
    try:
        with conn.transaction(), conn.cursor() as cur:
            for row in rows:
                # upsert_sql is one of the module-level UPSERT_*_SQL literals,
                # but _FEED_CONFIG's dict[str, ...] widens it to plain str --
                # cast back since psycopg's execute() requires LiteralString.
                cur.execute(
                    cast(LiteralString, upsert_sql),
                    _row_params(row, s3_key=s3_key),
                )
    finally:
        conn.close()

    # Space-delimited (not JSON prose) because the CloudWatch Logs metric
    # filter that derives NovaToll/LoadSuccess{feed} only extracts dimensions
    # from JSON or space-delimited log lines.
    logger.info("LOAD_OK %s", feed)
    logger.info("LOAD_OBJECT_OK %s %s", feed, s3_key)


def handler(event: dict[str, Any], _context: object) -> None:
    s3_client = cast(
        Any,
        boto3.client("s3"),  # pyright: ignore[reportUnknownMemberType]
    )
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        feed = _validate_record(bucket, key, record["s3"]["object"].get("size"))

        response = s3_client.get_object(Bucket=bucket, Key=key)
        content_length = response.get("ContentLength")
        if content_length is not None and content_length > MAX_RAW_OBJECT_BYTES:
            raise ValueError(f"raw object exceeds allowed size: {key}")
        raw_body = response["Body"].read(MAX_RAW_OBJECT_BYTES + 1)
        if len(raw_body) > MAX_RAW_OBJECT_BYTES:
            raise ValueError(f"raw object exceeds allowed size: {key}")
        body = raw_body.decode("utf-8")

        # On parse failure this raises: Lambda marks the invocation failed
        # (Errors alarm fires), the raw object in S3 is untouched, and the
        # exhausted async event lands in the OnFailure SQS queue for replay.
        rows = _parse_payload(feed, body)
        _load(feed, rows, s3_key=key)
