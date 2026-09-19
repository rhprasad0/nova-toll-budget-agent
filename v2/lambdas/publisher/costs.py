"""Daily public billing aggregates. No database, model calls, or usage estimates."""

from __future__ import annotations

import copy
import json
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, getcontext
from typing import Any, cast

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

getcontext().prec = 80
DEVELOPMENT_URL = "https://dev.tollchat.ai/costs.json"
OPENAI_URL = "https://api.openai.com/v1/organization/costs"
BILLING_KEY = "/nova-toll/openai_billing_api_key"
ACCOUNTS = {"development": "903859731897", "production": "920534282028"}
SCOPES = {
    "aws_development": "development-account",
    "aws_production": "production-account",
    "openai": "organization",
}
ENVIRONMENTS = ("production", "development", "shared", "unallocated")
# Only provider service names become public labels; unknown services still count.
SERVICES = frozenset(
    {
        "Amazon Elastic Compute Cloud - Compute",
        "EC2 - Other",
        "Amazon Relational Database Service",
        "Amazon Virtual Private Cloud",
        "Amazon Simple Storage Service",
        "AmazonCloudWatch",
        "AWS Lambda",
        "Amazon Bedrock",
        "Amazon Bedrock AgentCore",
        "Amazon CloudFront",
        "AWS Key Management Service",
        "Amazon Route 53",
        "AWS WAF",
        "Amazon API Gateway",
        "Amazon DynamoDB",
        "Amazon Simple Queue Service",
        "Amazon Simple Notification Service",
        "Amazon EventBridge",
        "AWS CloudTrail",
        "AWS Cost Explorer",
        "Amazon Athena",
        "AWS Glue",
        "Amazon Kinesis Firehose",
        "Amazon Data Firehose",
        "AWS Systems Manager",
        "Tax",
        "Other AWS services",
    }
)
MAX_BODY = 2 * 1024 * 1024
AMOUNT = re.compile(r"-?(?:0|[1-9]\d{0,17})(?:\.\d{1,30})?\Z")


def require(condition: object) -> None:
    if not condition:
        raise ValueError("invalid_billing_data")


def keys(value: object, expected: str) -> None:
    require(
        isinstance(value, dict)
        and set(cast(dict[str, Any], value)) == set(expected.split())
    )


def amount(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("invalid_billing_data")
    require(AMOUNT.fullmatch(value))
    return Decimal(value)


def decimal_text(value: Decimal) -> str:
    result = format(value, "f")
    amount(result)
    return result


def total(values: Iterable[str]) -> str:
    return decimal_text(sum((amount(value) for value in values), Decimal(0)))


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid_billing_data")
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value))
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def dates(period: dict[str, str]) -> list[str]:
    keys(period, "start end_exclusive")
    start, end = (date.fromisoformat(period[key]) for key in ("start", "end_exclusive"))
    require(
        start.isoformat() == period["start"]
        and end.isoformat() == period["end_exclusive"]
    )
    require(0 <= (end - start).days <= 31)
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days)]


def periods(today: date) -> dict[str, dict[str, str]]:
    def period(start: date) -> dict[str, str]:
        return {"start": start.isoformat(), "end_exclusive": today.isoformat()}

    return {
        "month_to_date": period(today.replace(day=1)),
        "last_30_days": period(today - timedelta(days=30)),
    }


def requested(windows: dict[str, dict[str, str]]) -> dict[str, str]:
    return {
        "start": min(p["start"] for p in windows.values()),
        "end_exclusive": windows["month_to_date"]["end_exclusive"],
    }


def source_ids(environment: str) -> tuple[str, ...]:
    require(environment in ACCOUNTS)
    return (
        ("aws_production", "aws_development", "openai")
        if environment == "production"
        else ("aws_development", "openai")
    )


def blank_source(
    name: str, period: dict[str, str], disabled: bool = False
) -> dict[str, Any]:
    return {
        "status": "not_configured" if disabled else "unavailable",
        "scope": SCOPES[name],
        "requested": period,
        "retrieved_at": None,
        "finalized_through": None,
        "estimated": None,
        "currency": "USD",
        "daily": [],
        "aws_services": [],
        "aws_environments": [],
    }


def rows(values: dict[str, Decimal]) -> list[dict[str, str]]:
    return [
        {"label": key, "usd": decimal_text(value)}
        for key, value in sorted(values.items())
    ]


def collect_aws(
    client: Any,  # noqa: ANN401 - boto3 service client
    account: str,
    period: dict[str, str],
    retrieved: str,
    budget: Callable[[], None] = lambda: None,
) -> dict[str, Any]:
    require(account in ACCOUNTS.values())
    days: dict[str, Decimal] = defaultdict(Decimal)
    services: dict[str, Decimal] = defaultdict(Decimal)
    environments: dict[str, Decimal] = defaultdict(Decimal)
    month = period["end_exclusive"][:7] + "-01"
    seen_groups: set[tuple[str, str, str]] = set()
    expected = set(dates(period))
    estimated = False
    query: dict[str, Any] = {
        "TimePeriod": {"Start": period["start"], "End": period["end_exclusive"]},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
        "Filter": {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": [account]}},
        "GroupBy": [
            {"Type": "DIMENSION", "Key": "SERVICE"},
            {"Type": "TAG", "Key": "environment"},
        ],
    }
    tokens: set[str] = set()
    while True:
        budget()
        response = client.get_cost_and_usage(**query)
        require(isinstance(response["ResultsByTime"], list))
        for bucket in response["ResultsByTime"]:
            day = bucket["TimePeriod"]["Start"]
            require(
                day in expected
                and bucket["TimePeriod"]["End"]
                == (date.fromisoformat(day) + timedelta(days=1)).isoformat()
            )
            require(type(bucket["Estimated"]) is bool)
            estimated |= bucket["Estimated"]
            days[day] += Decimal(0)
            require(isinstance(bucket["Groups"], list))
            for group in bucket["Groups"]:
                require(len(group["Keys"]) == 2)
                service, tag = group["Keys"]
                require(isinstance(service, str) and isinstance(tag, str))
                identity = (day, service, tag)
                require(identity not in seen_groups)
                seen_groups.add(identity)
                metric = group["Metrics"]["UnblendedCost"]
                require(metric["Unit"] == "USD")
                charge = amount(metric["Amount"])
                days[day] += charge
                if day >= month:
                    services[
                        service if service in SERVICES else "Other AWS services"
                    ] += charge
                    allocation = (
                        tag.removeprefix("environment$")
                        if tag.startswith("environment$")
                        else ""
                    )
                    environments[
                        allocation if allocation in ENVIRONMENTS else "unallocated"
                    ] += charge
            if bucket.get("Total"):
                metric = bucket["Total"]["UnblendedCost"]
                require(metric["Unit"] == "USD")
                charge = amount(metric["Amount"])
                if bucket["Groups"]:
                    require(
                        charge
                        == sum(
                            (
                                amount(group["Metrics"]["UnblendedCost"]["Amount"])
                                for group in bucket["Groups"]
                            ),
                            Decimal(0),
                        )
                    )
                else:
                    require((day, "total", "") not in seen_groups)
                    seen_groups.add((day, "total", ""))
                    days[day] += charge
                    if day >= month:
                        services["Other AWS services"] += charge
                        environments["unallocated"] += charge
        token = response.get("NextPageToken")
        if not token:
            break
        require(isinstance(token, str) and token not in tokens and len(tokens) < 100)
        tokens.add(token)
        query["NextPageToken"] = token
    require(set(days) == expected)
    return {
        "status": "available",
        "scope": SCOPES[
            "aws_" + next(env for env, value in ACCOUNTS.items() if value == account)
        ],
        "requested": period,
        "retrieved_at": retrieved,
        "finalized_through": None,
        "estimated": estimated,
        "currency": "USD",
        "daily": [
            {"date": day, "usd": decimal_text(days[day])} for day in sorted(days)
        ],
        "aws_services": rows(services),
        "aws_environments": rows(environments),
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        raise ValueError("billing_redirect")


def json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def decode(raw: bytes) -> dict[str, Any]:
    require(len(raw) <= MAX_BODY)
    result: object = json.loads(raw, parse_float=Decimal, object_pairs_hook=json_pairs)
    require(isinstance(result, dict))
    return cast(dict[str, Any], result)


def get_json(url: str, key: str | None = None) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    base = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    require(base in {DEVELOPMENT_URL, OPENAI_URL} and not parsed.fragment)
    require((base == OPENAI_URL) == (key is not None))
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}"} if key else {}
    )
    with urllib.request.build_opener(NoRedirect()).open(
        request, timeout=20
    ) as response:
        require(response.status == 200 and response.url == url)
        return decode(response.read(MAX_BODY + 1))


def collect_openai(
    key: str,
    period: dict[str, str],
    retrieved: str,
    budget: Callable[[], None] = lambda: None,
) -> dict[str, Any]:
    query: dict[str, Any] = {
        "start_time": int(timestamp(period["start"] + "T00:00:00Z").timestamp()),
        "end_time": int(timestamp(period["end_exclusive"] + "T00:00:00Z").timestamp()),
        "bucket_width": "1d",
        "limit": 31,
    }
    days: dict[str, str] = {}
    tokens: set[str] = set()
    expected = set(dates(period))
    while True:
        budget()
        response = get_json(OPENAI_URL + "?" + urllib.parse.urlencode(query), key)
        require(isinstance(response["data"], list))
        for bucket in response["data"]:
            start, end = bucket["start_time"], bucket["end_time"]
            require(
                type(start) is int
                and type(end) is int
                and start % 86400 == 0
                and end == start + 86400
            )
            day = datetime.fromtimestamp(start, UTC).date().isoformat()
            require(
                day in expected
                and day not in days
                and isinstance(bucket["results"], list)
            )
            charges: list[str] = []
            for result in bucket["results"]:
                metric = result["amount"]
                require(
                    metric["currency"] == "usd"
                    and not isinstance(metric["value"], (float, bool))
                )
                charges.append(
                    format(metric["value"], "f")
                    if isinstance(metric["value"], Decimal)
                    else str(metric["value"])
                )
            days[day] = total(charges)
        require(type(response["has_more"]) is bool)
        if not response["has_more"]:
            require(response.get("next_page") is None)
            break
        token = response["next_page"]
        require(
            isinstance(token, str)
            and token
            and token not in tokens
            and len(tokens) < 100
        )
        tokens.add(token)
        query["page"] = token
    require(set(days) == expected)
    result = blank_source("openai", period)
    result.update(
        status="available",
        retrieved_at=retrieved,
        daily=[{"date": day, "usd": days[day]} for day in sorted(days)],
    )
    return result


def summarize(
    sources: dict[str, Any], windows: dict[str, dict[str, str]]
) -> dict[str, Any]:
    aws = [source for name, source in sources.items() if name.startswith("aws_")]
    openai = sources["openai"]

    def provider_total(group: list[Any], day: str | None = None) -> str | None:
        if not all(source["status"] == "available" for source in group):
            return None
        return total(
            row["usd"]
            for source in group
            for row in source["daily"]
            if row["date"] == day
            or (day is None and row["date"] >= windows["month_to_date"]["start"])
        )

    def combined(a: str | None, b: str | None) -> str | None:
        return total([a, b]) if a is not None and b is not None else None

    a, b = provider_total(aws), provider_total([openai])
    daily: list[dict[str, str | None]] = []
    for day in dates(windows["last_30_days"]):
        da, db = provider_total(aws, day), provider_total([openai], day)
        daily.append({"date": day, "aws": da, "openai": db, "total": combined(da, db)})
    result: dict[str, Any] = {
        "month_to_date": {"aws": a, "openai": b, "total": combined(a, b)},
        "daily": daily,
    }
    for field in ("aws_services", "aws_environments"):
        values: dict[str, Decimal] = defaultdict(Decimal)
        for source in aws:
            if source["status"] == "available":
                for row in source[field]:
                    values[row["label"]] += amount(row["usd"])
        result[field] = rows(values)
    return result


def validate_snapshot(
    value: dict[str, Any], environment: str, now: datetime
) -> dict[str, Any]:
    keys(
        value,
        "schema_version kind environment scope currency periods requested published_at attempt sources month_to_date daily aws_services aws_environments",
    )
    require(
        type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and value["kind"] == "billing-costs"
    )
    require(value["environment"] == environment and value["currency"] == "USD")
    require(
        value["scope"]
        == (
            "aws-production+aws-development+openai-organization"
            if environment == "production"
            else "aws-development"
        )
    )
    published = timestamp(value["published_at"])
    require(published <= now)
    windows = periods(date.fromisoformat(value["requested"]["end_exclusive"]))
    require(value["periods"] == windows and value["requested"] == requested(windows))
    require(value["requested"]["end_exclusive"] <= published.date().isoformat())
    keys(value["sources"], " ".join(source_ids(environment)))
    keys(value["attempt"], "at status sources")
    require(published <= timestamp(value["attempt"]["at"]) <= now)
    keys(value["attempt"]["sources"], " ".join(source_ids(environment)))
    for name, source in value["sources"].items():
        keys(
            source,
            "status scope currency requested retrieved_at finalized_through estimated daily aws_services aws_environments",
        )
        disabled = name == "openai" and environment == "development"
        allowed = {"not_configured"} if disabled else {"available", "unavailable"}
        require(
            source["status"] in allowed and value["attempt"]["sources"][name] in allowed
        )
        require(
            source["scope"] == SCOPES[name]
            and source["currency"] == "USD"
            and source["requested"] == value["requested"]
        )
        require(source["finalized_through"] is None)
        if source["status"] != "available":
            require(source == blank_source(name, value["requested"], disabled))
            continue
        require(timestamp(source["retrieved_at"]) <= published)
        require(
            source["requested"]["end_exclusive"]
            <= timestamp(source["retrieved_at"]).date().isoformat()
        )
        require(
            (type(source["estimated"]) is bool)
            if name.startswith("aws_")
            else source["estimated"] is None
        )
        require(
            isinstance(source["daily"], list)
            and [row["date"] for row in source["daily"]] == dates(value["requested"])
        )
        for row in source["daily"]:
            keys(row, "date usd")
            amount(row["usd"])
        for field, labels in (
            ("aws_services", SERVICES),
            ("aws_environments", ENVIRONMENTS),
        ):
            entries = source[field]
            require(isinstance(entries, list))
            require(
                [row["label"] for row in entries]
                == sorted({row["label"] for row in entries})
            )
            for row in entries:
                keys(row, "label usd")
                require(row["label"] in labels)
                amount(row["usd"])
            if name.startswith("aws_"):
                require(
                    amount(total(row["usd"] for row in entries))
                    == amount(
                        total(
                            row["usd"]
                            for row in source["daily"]
                            if row["date"] >= windows["month_to_date"]["start"]
                        )
                    )
                )
            else:
                require(not entries)
    failed = "unavailable" in value["attempt"]["sources"].values()
    require(value["attempt"]["status"] == ("failed" if failed else "succeeded"))
    summary = summarize(value["sources"], windows)
    require(all(value[key] == expected for key, expected in summary.items()))
    return value


def development_source(
    value: dict[str, Any], period: dict[str, str], now: datetime
) -> dict[str, Any]:
    snapshot = validate_snapshot(value, "development", now)
    require(
        snapshot["requested"] == period and snapshot["attempt"]["status"] == "succeeded"
    )
    source = snapshot["sources"]["aws_development"]
    require(source["status"] == "available")
    require(now - timestamp(snapshot["published_at"]) <= timedelta(hours=48))
    require(now - timestamp(source["retrieved_at"]) <= timedelta(hours=48))
    return source


def build_snapshot(
    environment: str,
    now: datetime,
    sources: dict[str, Any],
    previous: dict[str, Any] | None = None,
    *,
    published_at: datetime | None = None,
) -> dict[str, Any]:
    published_at = published_at or now
    statuses = {name: source["status"] for name, source in sources.items()}
    attempt = {
        "at": utc_text(published_at),
        "status": "failed" if "unavailable" in statuses.values() else "succeeded",
        "sources": statuses,
    }
    if previous is not None and attempt["status"] == "failed":
        result = copy.deepcopy(validate_snapshot(previous, environment, published_at))
        result["attempt"] = attempt
    else:
        windows = periods(now.date())
        result = {
            "schema_version": 1,
            "kind": "billing-costs",
            "environment": environment,
            "scope": "aws-production+aws-development+openai-organization"
            if environment == "production"
            else "aws-development",
            "currency": "USD",
            "periods": windows,
            "requested": requested(windows),
            "published_at": utc_text(published_at),
            "attempt": attempt,
            "sources": sources,
            **summarize(sources, windows),
        }
    return validate_snapshot(result, environment, published_at)


def handler(_event: dict[str, Any], context: object) -> dict[str, str]:
    runtime_context = cast(Any, context)
    environment = os.environ["DEPLOYMENT_ENVIRONMENT"]
    account = ACCOUNTS[environment]
    require(runtime_context.invoked_function_arn.split(":")[4] == account)
    bucket = os.environ["COST_BUCKET"]
    require(
        bucket
        == f"tollchat-site-{account}" + ("-dev" if environment == "development" else "")
    )
    config = Config(
        connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 2}
    )
    s3 = cast(Any, boto3).client("s3", config=config)
    previous = None
    try:
        # A prefix-scoped ListBucket grant does not guarantee GetObject returns
        # 404 for missing keys. Check existence explicitly before reading.
        objects = s3.list_objects_v2(Bucket=bucket, Prefix="costs.json", MaxKeys=1)
        if any(row["Key"] == "costs.json" for row in objects.get("Contents", [])):
            stored = s3.get_object(Bucket=bucket, Key="costs.json")["Body"]
            try:
                previous = validate_snapshot(
                    decode(stored.read(MAX_BODY + 1)), environment, datetime.now(UTC)
                )
            finally:
                stored.close()
    except ClientError:
        raise RuntimeError("cost_snapshot_read_failed") from None
    except (ValueError, KeyError, TypeError):
        # Invalid prior public data cannot become a last-valid snapshot.
        previous = None
    now = datetime.now(UTC).replace(microsecond=0)
    period = requested(periods(now.date()))
    sources = {
        name: blank_source(
            name, period, environment == "development" and name == "openai"
        )
        for name in source_ids(environment)
    }

    def budget() -> None:
        # Reserve time to publish a sanitized failed attempt after provider I/O.
        require(runtime_context.get_remaining_time_in_millis() >= 60000)

    for name in sources:
        if sources[name]["status"] == "not_configured":
            continue
        try:
            budget()
            if name == "aws_" + environment:
                sources[name] = collect_aws(
                    cast(Any, boto3).client(
                        "ce", region_name="us-east-1", config=config
                    ),
                    account,
                    period,
                    utc_text(now),
                    budget,
                )
            elif name == "aws_development":
                sources[name] = development_source(
                    get_json(DEVELOPMENT_URL), period, now
                )
            else:
                secret = (
                    cast(Any, boto3)
                    .client("ssm", config=config)
                    .get_parameter(Name=BILLING_KEY, WithDecryption=True)["Parameter"][
                        "Value"
                    ]
                )
                sources[name] = collect_openai(secret, period, utc_text(now), budget)
            completed = datetime.now(UTC).replace(microsecond=0)
            if name != "aws_development" or environment == "development":
                sources[name]["retrieved_at"] = utc_text(completed)
            build_snapshot(environment, now, sources, published_at=completed)
        except Exception:
            # Provider exceptions can contain credentials, URLs, IDs, or raw bodies.
            sources[name] = blank_source(name, period)
    result = build_snapshot(
        environment,
        now,
        sources,
        previous,
        published_at=datetime.now(UTC).replace(microsecond=0),
    )
    s3.put_object(
        Bucket=bucket,
        Key="costs.json",
        Body=json.dumps(result, separators=(",", ":")).encode(),
        ContentType="application/json; charset=utf-8",
        CacheControl="no-cache",
    )
    return {"status": result["attempt"]["status"]}
