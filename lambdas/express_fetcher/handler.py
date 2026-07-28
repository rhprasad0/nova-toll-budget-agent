"""toll-express-fetcher Lambda.

Polls Transurban's own live Express Lanes snapshot and lands the raw payload
in S3, to fill od_pair_ids VDOT's feed never publishes (see
docs/oracle-findings.md section 2 and docs/poller-spec.md's "Secondary live
source" section). Unlike toll-fetcher there's a single unauthenticated URL and
no SSM token lookup, but it shares I-95's EventBridge tick -- which also makes
the two feeds' captures directly alignable.

The payload changes on every 10-minute tick, around the clock (measured
2026-07-28 over 272 consecutive captures), so polling is never a no-op.

Same single-attempt, no-retry etiquette as toll-fetcher: this endpoint sits
behind the same WAF class as VDOT's, so it gets the same courtesy even though
it isn't known to be blocked.
"""

import logging
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
TICK_MINUTES = 10  # matches toll-fetcher's tick -- same EventBridge rule

URL = "https://www.expresslanes.com/maps-api/infra-price-confirmed-all"
FEED = "i95-live"

# Lazy singletons: created on first use, not at import time, so tests can
# stub them without a real AWS region/credentials configured.
_clients: dict[str, Any] = {}


def _client(name: str):
    if name not in _clients:
        _clients[name] = boto3.client(name)
    return _clients[name]


def _s3_key(now: datetime) -> str:
    """raw/feed=i95-live/date=<YYYY-MM-DD>/<HHMM>Z.json, tick-rounded per spec."""
    tick_minute = (now.minute // TICK_MINUTES) * TICK_MINUTES
    tick = now.replace(minute=tick_minute, second=0, microsecond=0)
    date = tick.strftime("%Y-%m-%d")
    stamp = tick.strftime("%H%M") + "Z"
    return f"raw/feed={FEED}/date={date}/{stamp}.json"


def _fetch() -> bytes:
    """Single-attempt GET, 30s timeout, response capped at 5 MB."""
    try:
        with urllib.request.urlopen(URL, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"{FEED} fetch failed: {exc}") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError(
            f"{FEED} fetch failed: response exceeded {MAX_RESPONSE_BYTES} byte cap"
        )
    return body


def handler(event: dict[str, Any], _context: object) -> None:
    now = datetime.now(UTC)
    body = _fetch()
    key = _s3_key(now)
    _client("s3").put_object(
        Bucket=os.environ["RAW_BUCKET"],
        Key=key,
        Body=body,
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=os.environ["RAW_KMS_KEY_ARN"],
    )
    _client("cloudwatch").put_metric_data(
        Namespace="NovaToll",
        MetricData=[
            {
                "MetricName": "PollSuccess",
                "Dimensions": [{"Name": "feed", "Value": FEED}],
                "Value": 1,
                "Unit": "Count",
            }
        ],
    )
    logger.info("poll succeeded feed=%s key=%s", FEED, key)
