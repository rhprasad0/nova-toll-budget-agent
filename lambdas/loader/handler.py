"""toll-loader Lambda: S3 ObjectCreated -> parse -> idempotent upsert into RDS.

psycopg is only present in the deployed zip, not the dev/test venv, so the
connection is built with a lazy import inside _connect() — everything else
here (routing, parsing) must stay importable without it.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import urllib.parse
from typing import Any

import boto3

from parse_csv import TripPricingRow, parse_trip_pricing_csv
from parse_xml import parse_trip_pricing_xml

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# RDS CA bundle is dropped into the deployment zip next to this file by the
# Terraform/build step (WP1) — verify-full needs it to authenticate the
# server, not just encrypt the connection.
CA_BUNDLE_PATH = os.path.join(os.path.dirname(__file__), "rds-ca-bundle.pem")

UPSERT_SQL = """
INSERT INTO trip_pricing (
    feed,
    interval_start_at,
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
    %(feed)s,
    %(interval_start_at)s,
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
ON CONFLICT (feed, interval_end_at, start_zone_id, end_zone_id, od_pair_id) DO UPDATE
SET
    interval_start_at = EXCLUDED.interval_start_at,
    current_at = EXCLUDED.current_at,
    calculated_at = EXCLUDED.calculated_at,
    corridor_id = EXCLUDED.corridor_id,
    corridor_name = EXCLUDED.corridor_name,
    od_pair_name = EXCLUDED.od_pair_name,
    start_zone_name = EXCLUDED.start_zone_name,
    end_zone_name = EXCLUDED.end_zone_name,
    zone_toll_rate_usd = EXCLUDED.zone_toll_rate_usd,
    link_status = EXCLUDED.link_status,
    s3_key = EXCLUDED.s3_key
"""


def _feed_from_key(key: str) -> str:
    """raw/feed=i95/date=2026-07-21/1440Z.csv -> "i95"."""
    for part in key.split("/"):
        if part.startswith("feed="):
            return part.removeprefix("feed=")
    raise ValueError(f"cannot determine feed from S3 key: {key}")


def _parse_payload(feed: str, body: str) -> list[TripPricingRow]:
    if feed == "i95":
        return parse_trip_pricing_csv(body)
    if feed == "i66":
        return parse_trip_pricing_xml(body)
    raise ValueError(f"unknown feed: {feed}")


def _row_params(row: TripPricingRow, *, s3_key: str) -> dict[str, Any]:
    params = dataclasses.asdict(row)
    params["s3_key"] = s3_key
    return params


def _connect(*, host: str, port: int, dbname: str, user: str):
    import psycopg  # type: ignore[import-not-found]  # deployed-zip-only dependency; see module docstring.

    token = boto3.client("rds").generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername=user
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


def _load(feed: str, rows: list[TripPricingRow], *, s3_key: str) -> None:
    conn = _connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
    )
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(UPSERT_SQL, _row_params(row, s3_key=s3_key))
    finally:
        conn.close()

    # Space-delimited (not JSON prose) because the CloudWatch Logs metric
    # filter that derives NovaToll/LoadSuccess{feed} only extracts dimensions
    # from JSON or space-delimited log lines.
    logger.info("LOAD_OK %s", feed)


def handler(event: dict[str, Any], _context: object) -> None:
    s3_client = boto3.client("s3")
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        feed = _feed_from_key(key)

        body = (
            s3_client.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
        )

        # On parse failure this raises: Lambda marks the invocation failed
        # (Errors alarm fires), the raw object in S3 is untouched, and the
        # exhausted async event lands in the OnFailure SQS queue for replay.
        rows = _parse_payload(feed, body)
        _load(feed, rows, s3_key=key)
