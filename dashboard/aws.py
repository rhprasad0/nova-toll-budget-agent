import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import boto3
import psycopg

from dashboard import ingest, migrate, web
from dashboard.analytics import DEFAULT_WORKSPACE_ID, HttpAnalyticsClient

CA_BUNDLE = Path(__file__).resolve().parent.parent / "rds-ca-bundle.pem"


def connect(user: str) -> psycopg.Connection:
    host = os.environ["DB_HOST"]
    rds = cast(Any, boto3.client("rds"))  # pyright: ignore[reportUnknownMemberType]
    return psycopg.connect(
        host=host,
        port=5432,
        dbname=os.environ["DB_NAME"],
        user=user,
        password=rds.generate_db_auth_token(
            DBHostname=host, Port=5432, DBUsername=user
        ),
        sslmode="verify-full",
        sslrootcert=str(CA_BUNDLE),
        connect_timeout=5,
    )


def ingest_handler(event: object, context: object) -> dict[str, int]:
    ssm = cast(Any, boto3.client("ssm"))  # pyright: ignore[reportUnknownMemberType]
    key = ssm.get_parameter(
        Name=os.environ["ADMIN_KEY_PARAMETER"], WithDecryption=True
    )["Parameter"]["Value"]
    with connect(os.environ["DB_WRITER"]) as connection:
        migrate.apply(connection)
        result = ingest.run(
            HttpAnalyticsClient(key),
            connection,
            now=datetime.now(UTC),
            workspace_id=os.environ.get("FACTORY_WORKSPACE_ID") or DEFAULT_WORKSPACE_ID,
        )
    print(f"ingested {result.usage_rows} usage rows and {result.cost_rows} cost rows")
    return {"usage_rows": result.usage_rows, "cost_rows": result.cost_rows}


def web_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    status, body, content_type = web.respond(
        lambda: connect(os.environ["DB_READER"]),
        event.get("rawPath") or "/",
        event.get("rawQueryString") or "",
        datetime.now(UTC),
    )
    return {
        "statusCode": status,
        "headers": {
            "content-type": f"{content_type}; charset=utf-8",
            "cache-control": "max-age=300" if status == 200 else "no-store",
        },
        "body": body,
    }
