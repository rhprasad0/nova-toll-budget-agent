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
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
TICK_MINUTES = 10

FEEDS = {
    "i95": {
        "url": (
            "https://data.511-atis-ttrip-prod.iteriscloud.com/smarterRoads/"
            "tollRoad/I95/current/tollingTripPricing_I95.csv"
        ),
        "token_param_env": "I95_TOKEN_PARAM",
        "extension": "csv",
    },
    "i66": {
        "url": (
            "https://data.511-atis-ttrip-prod.iteriscloud.com/smarterRoads/"
            "tollRoad/I66/current/tollingTripPricing-I66.xml"
        ),
        "token_param_env": "I66_TOKEN_PARAM",
        "extension": "xml",
    },
}

# Lazy singletons: created on first use, not at import time, so tests can
# stub them without a real AWS region/credentials configured.
_clients: dict[str, Any] = {}
_tokens: dict[str, str] | None = None


def _client(name: str):
    if name not in _clients:
        _clients[name] = boto3.client(name)
    return _clients[name]


def _load_tokens() -> dict[str, str]:
    """Read both feed tokens from SSM SecureString params, once per cold start."""
    global _tokens
    if _tokens is None:
        ssm = _client("ssm")
        _tokens = {
            feed: ssm.get_parameter(
                Name=os.environ[cfg["token_param_env"]], WithDecryption=True
            )["Parameter"]["Value"]
            for feed, cfg in FEEDS.items()
        }
    return _tokens


def _scrub(text: str, token: str) -> str:
    """Strip a token value out of a string before it can reach a log/exception."""
    return text.replace(token, "***")


def _s3_key(feed: str, now: datetime, extension: str) -> str:
    """raw/feed=<feed>/date=<YYYY-MM-DD>/<HHMM>Z.<ext>, tick-rounded per spec."""
    tick_minute = (now.minute // TICK_MINUTES) * TICK_MINUTES
    tick = now.replace(minute=tick_minute, second=0, microsecond=0)
    date = tick.strftime("%Y-%m-%d")
    stamp = tick.strftime("%H%M") + "Z"
    return f"raw/feed={feed}/date={date}/{stamp}.{extension}"


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


def _poll_feed(feed: str, cfg: dict, token: str, now: datetime) -> None:
    body = _fetch_feed(feed, cfg["url"], token)
    key = _s3_key(feed, now, cfg["extension"])
    _client("s3").put_object(Bucket=os.environ["RAW_BUCKET"], Key=key, Body=body)
    _client("cloudwatch").put_metric_data(
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


def handler(event, context):
    tokens = _load_tokens()
    now = datetime.now(UTC)
    failed_feeds = []
    for feed, cfg in FEEDS.items():
        try:
            _poll_feed(feed, cfg, tokens[feed], now)
        except Exception as exc:
            logger.error(
                "feed=%s poll failed: %s", feed, _scrub(str(exc), tokens[feed])
            )
            failed_feeds.append(feed)
    if failed_feeds:
        # Surfaces as a Lambda Errors metric (spec Observability alarm #1)
        # without ever touching the other feed's attempt above.
        raise RuntimeError(f"poll failed for feed(s): {', '.join(failed_feeds)}")
