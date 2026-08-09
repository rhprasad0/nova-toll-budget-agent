"""toll-fetcher Lambda.

Polls the two VDOT SmarterRoads feeds and lands raw payloads in S3. Per spec
(docs/poller-spec.md, §Lambda details / §Data sources):

- One attempt per feed per tick, no retries — WAF etiquette.
- Each feed is fetched, uploaded, and metriced independently: one feed
  failing must never stop the other's PUT.
- The token rides in the URL query string, so every error path scrubs it
  before the message can reach a log line or an exception.
"""

import logging
import os
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict, cast

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_DRILL_ID = re.compile(r"[a-f0-9]{16}\Z")


# tick_minutes is each feed's own publish cadence, measured against prod rather
# than assumed (docs/oracle-findings.md section 9): I-95 publishes a new interval every
# 10 minutes exactly, I-66 every 6 with a real 6-minute interval window. They
# ride separate EventBridge rules in infra/triggers.tf, and this is also the
# S3 key's bucket size -- keep the two in step or two polls of the same feed
# will floor into one key and overwrite each other.
class FeedConfig(TypedDict):
    url: str
    token_param_env: str
    extension: str
    tick_minutes: int


class SsmClient(Protocol):
    def get_parameter(self, *, Name: str, WithDecryption: bool) -> dict[str, Any]: ...


class S3Client(Protocol):
    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ServerSideEncryption: str,
        SSEKMSKeyId: str,
    ) -> object: ...


class CloudWatchClient(Protocol):
    def put_metric_data(
        self, *, Namespace: str, MetricData: list[dict[str, Any]]
    ) -> object: ...


FEEDS: dict[str, FeedConfig] = {
    "i95": {
        "url": (
            "https://data.511-atis-ttrip-prod.iteriscloud.com/smarterRoads/"
            "tollRoad/I95/current/tollingTripPricing_I95.csv"
        ),
        "token_param_env": "I95_TOKEN_PARAM",
        "extension": "csv",
        "tick_minutes": 10,
    },
    "i66": {
        "url": (
            "https://data.511-atis-ttrip-prod.iteriscloud.com/smarterRoads/"
            "tollRoad/I66/current/tollingTripPricing-I66.xml"
        ),
        "token_param_env": "I66_TOKEN_PARAM",
        "extension": "xml",
        "tick_minutes": 6,
    },
}

# Lazy singletons: created on first use, not at import time, so tests can
# stub them without a real AWS region/credentials configured.
_clients: dict[str, object] = {}
_tokens: dict[str, str] | None = None


def _client(name: str) -> object:
    if name not in _clients:
        _clients[name] = cast(
            object,
            boto3.client(name),  # pyright: ignore[reportUnknownMemberType]
        )
    return _clients[name]


def _load_tokens() -> dict[str, str]:
    """Read both feed tokens from SSM SecureString params, once per cold start."""
    global _tokens
    if _tokens is None:
        ssm = cast(SsmClient, _client("ssm"))
        _tokens = {
            feed: cast(
                str,
                ssm.get_parameter(
                    Name=os.environ[cfg["token_param_env"]], WithDecryption=True
                )["Parameter"]["Value"],
            )
            for feed, cfg in FEEDS.items()
        }
    return _tokens


def _scrub(text: str, token: str) -> str:
    """Strip a token value out of a string before it can reach a log/exception."""
    return text.replace(token, "***")


def _s3_key(
    feed: str,
    now: datetime,
    extension: str,
    tick_minutes: int,
    drill_id: str | None = None,
) -> str:
    """Build the tick-rounded raw key, with an optional unique drill suffix.

    tick_minutes is the feed's own cadence, so I-66's buckets are 6 minutes
    wide (…0000Z, 0006Z, 0012Z) and I-95's are 10.
    """
    tick_minute = (now.minute // tick_minutes) * tick_minutes
    tick = now.replace(minute=tick_minute, second=0, microsecond=0)
    date = tick.strftime("%Y-%m-%d")
    stamp = tick.strftime("%H%M") + "Z"
    suffix = f"-{drill_id}" if drill_id else ""
    return f"raw/feed={feed}/date={date}/{stamp}{suffix}.{extension}"


def _fetch_feed(feed: str, url: str, token: str) -> bytes:
    """Single-attempt GET, 30s timeout, response capped at 5 MB.

    Any exception raised out of here has the token scrubbed from its text —
    urllib exceptions can otherwise echo the request URL verbatim.
    """
    full_url = f"{url}?token={token}"
    try:
        with urllib.request.urlopen(full_url, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(_scrub(f"{feed} fetch failed: {exc}", token)) from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError(
            f"{feed} fetch failed: response exceeded {MAX_RESPONSE_BYTES} byte cap"
        )
    return body


def _poll_feed(
    feed: str,
    cfg: FeedConfig,
    token: str,
    now: datetime,
    drill_id: str | None = None,
) -> str:
    body = _fetch_feed(feed, cfg["url"], token)
    key = _s3_key(feed, now, cfg["extension"], cfg["tick_minutes"], drill_id)
    cast(S3Client, _client("s3")).put_object(
        Bucket=os.environ["RAW_BUCKET"],
        Key=key,
        Body=body,
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=os.environ["RAW_KMS_KEY_ARN"],
    )
    cast(CloudWatchClient, _client("cloudwatch")).put_metric_data(
        Namespace="NovaToll",
        MetricData=[
            {
                "MetricName": "PollSuccess",
                "Dimensions": [{"Name": "feed", "Value": feed}],
                "Value": 1,
                "Unit": "Count",
            }
        ],
    )
    logger.info("poll succeeded feed=%s key=%s", feed, key)
    return key


def handler(event: dict[str, Any] | None, _context: object) -> dict[str, list[str]]:
    """Poll the feeds named in event["feeds"], or every feed if unspecified.

    The two feeds publish on different cadences, so infra/triggers.tf gives
    each its own EventBridge rule and names the feed in the target input. An
    empty event still means "all feeds" -- that's what a manual invoke and
    scripts/smoke.sh --fire send.
    """
    tokens = _load_tokens()
    now = datetime.now(UTC)
    requested_value = (event or {}).get("feeds")
    if requested_value is None:
        requested = list(FEEDS)
    elif not isinstance(requested_value, list):
        raise RuntimeError("feeds must be a list of strings")
    else:
        requested_objects = cast(list[object], requested_value)
        if not all(isinstance(feed, str) for feed in requested_objects):
            raise RuntimeError("feeds must be a list of strings")
        requested = cast(list[str], requested_objects)
    unknown = [feed for feed in requested if feed not in FEEDS]
    if unknown:
        raise RuntimeError(f"unknown feed(s) requested: {', '.join(unknown)}")
    drill_id = (event or {}).get("drill_id")
    if drill_id is not None and (
        not isinstance(drill_id, str) or not _DRILL_ID.fullmatch(drill_id)
    ):
        raise RuntimeError("drill_id must be 16 lowercase hexadecimal characters")

    failed_feeds: list[str] = []
    keys: list[str] = []
    for feed in requested:
        cfg = FEEDS[feed]
        try:
            keys.append(_poll_feed(feed, cfg, tokens[feed], now, drill_id))
        except Exception as exc:
            logger.exception(
                "feed=%s poll failed: %s", feed, _scrub(str(exc), tokens[feed])
            )
            failed_feeds.append(feed)
    if failed_feeds:
        # Surfaces as a Lambda Errors metric (spec Observability alarm #1)
        # without ever touching the other feed's attempt above.
        raise RuntimeError(f"poll failed for feed(s): {', '.join(failed_feeds)}")
    return {"keys": keys}
