import json
import os
import time
import urllib.request
from collections.abc import Callable
from typing import Any, cast

import boto3
import jwt

GITHUB = "https://api.github.com"
LABEL = "factory"
type Json = Any
Api = Callable[[str, str, dict[str, Any] | None], Json]


def http_api(token: str, scheme: str = "token") -> Api:
    def call(method: str, path: str, body: dict[str, Any] | None) -> Json:
        request = urllib.request.Request(
            GITHUB + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": f"{scheme} {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or b"null")

    return call


def installation_api(client_id: str, private_key: str, repo: str) -> Api:
    now = int(time.time())
    app_jwt = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": client_id},
        private_key,
        algorithm="RS256",
    )
    app = http_api(app_jwt, "Bearer")
    installation = app("GET", f"/repos/{repo}/installation", None)["id"]
    token = app("POST", f"/app/installations/{installation}/access_tokens", None)
    return http_api(token["token"])


def issue_body(alarm: dict[str, Any]) -> str:
    return (
        "## Change\n\n"
        f"CloudWatch alarm `{alarm['AlarmName']}` went to ALARM at "
        f"{alarm.get('StateChangeTime', 'an unknown time')}.\n\n"
        f"Reason: {alarm.get('NewStateReason', 'none given')}\n\n"
        f"{alarm.get('AlarmDescription') or ''}\n\n"
        "Find the root cause in this repository's code and fix it there. If the "
        "cause is outside the code, say so on this issue and change nothing.\n\n"
        "## Done when\n\n"
        "A test reproduces the failure without AWS access and passes after the fix.\n\n"
        "## Needs a human\n\n"
        "Reading CloudWatch Logs and metrics, redeploying the Lambda functions, "
        "and closing this issue once the alarm returns to OK.\n"
    )


def file_issue(api: Api, repo: str, app_slug: str, alarm: dict[str, Any]) -> int | None:
    if alarm.get("NewStateValue") != "ALARM":
        return None
    title = f"Alarm: {alarm['AlarmName']}"
    open_issues = api(
        "GET",
        f"/repos/{repo}/issues?state=open&creator={app_slug}%5Bbot%5D&per_page=100",
        None,
    )
    if any(issue["title"] == title for issue in open_issues):
        return None
    number = api(
        "POST", f"/repos/{repo}/issues", {"title": title, "body": issue_body(alarm)}
    )["number"]
    api("POST", f"/repos/{repo}/issues/{number}/labels", {"labels": [LABEL]})
    return number


def handler(event: dict[str, Any], context: object) -> list[int]:
    ssm = cast(Any, boto3.client("ssm"))  # pyright: ignore[reportUnknownMemberType]
    private_key = ssm.get_parameter(
        Name=os.environ["APP_PRIVATE_KEY_PARAMETER"], WithDecryption=True
    )["Parameter"]["Value"]
    repo = os.environ["GITHUB_REPOSITORY"]
    api = installation_api(os.environ["APP_CLIENT_ID"], private_key, repo)
    filed = [
        file_issue(
            api, repo, os.environ["APP_SLUG"], json.loads(record["Sns"]["Message"])
        )
        for record in event["Records"]
    ]
    return [number for number in filed if number is not None]
