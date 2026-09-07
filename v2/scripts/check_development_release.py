#!/usr/bin/env python3
"""Bounded, private readiness and public-path checks for the fixed dev release."""

from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

SITE = "https://dev.tollchat.ai"
ACCOUNT = "903859731897"
DISTRIBUTION = "E33DVF3KT7BTAC"
RUNTIME = "nova_toll_v2_development-Y69XBf88Bl"
RUNTIME_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/{RUNTIME}"
COOKIE = "__Host-tollchat-session"
PROMPT = "Briefly explain what information you need to estimate a toll budget."
MAX_BODY = 8 * 1024 * 1024
FUNCTIONS = {
    "loader": ("toll-v2-pricing-loader-dev", "loader.zip"),
    "publisher": ("toll-v2-report-publisher-dev", "publisher.zip"),
    "tollchat_proxy": ("tollchat-v2-chat-proxy-dev", "chat-proxy.zip"),
}


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("development release check failed")


def aws(*arguments: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "aws",
            *arguments,
            "--region",
            "us-east-1",
            "--output",
            "json",
            "--no-cli-pager",
            "--cli-connect-timeout",
            "10",
            "--cli-read-timeout",
            "20",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    require(result.returncode == 0 and len(result.stdout) <= MAX_BODY)
    response = json.loads(result.stdout)
    require(isinstance(response, dict))
    return response


def expected(state: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    resources = {
        item["address"]: item["values"]
        for item in state["values"]["root_module"]["resources"]
    }
    require(manifest["commit_sha"] == os.environ["GITHUB_SHA"])
    hashes = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    for _, (name, package) in FUNCTIONS.items():
        require(name.endswith("-dev"))
        require(
            re.fullmatch(r"[0-9a-f]{64}", hashes[f"v2/infra/build/{package}"])
            is not None
        )
    distribution = resources["aws_cloudfront_distribution.site"]
    runtime = resources["aws_bedrockagentcore_agent_runtime.tollchat"]
    endpoint = resources["aws_bedrockagentcore_agent_runtime_endpoint.tollchat"]
    alias = resources["aws_lambda_alias.tollchat_live"]
    require(distribution["id"] == DISTRIBUTION)
    require(
        runtime["agent_runtime_id"] == RUNTIME
        and runtime["agent_runtime_arn"] == RUNTIME_ARN
    )
    version = runtime["agent_runtime_version"]
    require(isinstance(version, str) and version.isdecimal() and int(version) > 0)
    require(endpoint["agent_runtime_id"] == RUNTIME and endpoint["name"] == "preview")
    require(endpoint["agent_runtime_version"] == version)
    require(
        alias["name"] == "live"
        and alias["function_name"] == FUNCTIONS["tollchat_proxy"][0]
    )
    require(
        isinstance(alias["function_version"], str)
        and alias["function_version"].isdecimal()
    )
    for resource, (name, package) in FUNCTIONS.items():
        function = resources[f"aws_lambda_function.{resource}"]
        digest = base64.b64encode(
            bytes.fromhex(hashes[f"v2/infra/build/{package}"])
        ).decode()
        require(
            function["function_name"] == name and function["source_code_hash"] == digest
        )
        if resource == "tollchat_proxy":
            require(function["version"] == alias["function_version"])
    require(state["values"]["outputs"]["public_site"]["value"]["url"] == SITE)
    return {
        "hashes": hashes,
        "version": version,
        "alias_version": alias["function_version"],
    }


def readiness(values: dict[str, Any]) -> None:
    require(aws("sts", "get-caller-identity")["Account"] == ACCOUNT)
    deadline = time.monotonic() + 600
    for _ in range(60):
        ready = True
        for name, package in FUNCTIONS.values():
            function = aws(
                "lambda", "get-function-configuration", "--function-name", name
            )
            require(function["FunctionName"] == name)
            require(
                function["FunctionArn"]
                == f"arn:aws:lambda:us-east-1:{ACCOUNT}:function:{name}"
            )
            require(function["State"] in {"Pending", "Active"})
            require(function["LastUpdateStatus"] in {"InProgress", "Successful"})
            digest = base64.b64encode(
                bytes.fromhex(values["hashes"][f"v2/infra/build/{package}"])
            ).decode()
            ready &= (
                function["State"] == "Active"
                and function["LastUpdateStatus"] == "Successful"
                and function["CodeSha256"] == digest
            )
        alias = aws(
            "lambda",
            "get-alias",
            "--function-name",
            FUNCTIONS["tollchat_proxy"][0],
            "--name",
            "live",
        )
        require(alias["Name"] == "live")
        ready &= alias["FunctionVersion"] == values["alias_version"]
        require(not alias.get("RoutingConfig", {}).get("AdditionalVersionWeights"))
        distribution = aws("cloudfront", "get-distribution", "--id", DISTRIBUTION)[
            "Distribution"
        ]
        require(distribution["Id"] == DISTRIBUTION)
        require(distribution["Status"] in {"InProgress", "Deployed"})
        ready &= distribution["Status"] == "Deployed"
        endpoint = aws(
            "bedrock-agentcore-control",
            "get-agent-runtime-endpoint",
            "--agent-runtime-id",
            RUNTIME,
            "--endpoint-name",
            "preview",
        )
        require(endpoint["agentRuntimeArn"] == RUNTIME_ARN)
        require(
            endpoint["name"] == "preview"
            and endpoint["status"] in {"CREATING", "UPDATING", "READY"}
        )
        ready &= (
            endpoint["status"] == "READY"
            and endpoint["liveVersion"] == values["version"]
            and endpoint["targetVersion"] == values["version"]
        )
        if ready:
            return
        require(time.monotonic() < deadline)
        time.sleep(5)
    raise ValueError("readiness deadline exceeded")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: object, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        raise ValueError("redirect rejected")


def request(
    jar: http.cookiejar.CookieJar,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    origin: str = SITE,
    cookie: str | None = None,
) -> tuple[int, str, bytes]:
    require(path.startswith("/") and not path.startswith("//"))
    headers = {
        "Origin": origin,
        "Sec-Fetch-Site": "same-origin",
        "Accept-Encoding": "identity",
    }
    if cookie is not None:
        headers["Cookie"] = f"{COOKIE}={cookie}"
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPCookieProcessor(jar)
    )
    req = urllib.request.Request(SITE + path, data=data, headers=headers)
    try:
        response = opener.open(req, timeout=90 if path == "/api/chat" else 20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        content = response.read(MAX_BODY + 1)
        require(len(content) <= MAX_BODY)
        code, kind = response.status, response.headers.get_content_type()
        if (
            not isinstance(code, int)
            or not isinstance(kind, str)
            or not isinstance(content, bytes)
        ):
            raise ValueError("invalid HTTP response")
        return code, kind, content


def answer(response: tuple[int, str, bytes]) -> None:
    code, content_type, body = response
    require(code == 200 and content_type == "application/x-ndjson")
    lines = body.decode().splitlines()
    require(0 < len(lines) <= 1000)
    terminal = False
    for line in lines:
        value = json.loads(line)
        require(isinstance(value, dict))
        item = cast(dict[str, Any], value)
        require(isinstance(item.get("type"), str) and not terminal)
        require(item["type"] != "error")
        if item["type"] == "answer":
            require(
                isinstance(item.get("text"), str)
                and bool(item["text"].strip())
                and item.get("blocked") is False
            )
            terminal = True
    require(terminal)


def token(jar: http.cookiejar.CookieJar) -> str:
    cookies = [item for item in jar if item.name == COOKIE]
    require(len(cookies) == 1)
    item = cookies[0]
    require(
        item.secure
        and item.path == "/"
        and item.domain == "dev.tollchat.ai"
        and not item.domain_specified
    )
    require(item.has_nonstandard_attr("HttpOnly") and bool(item.value))
    if not isinstance(item.value, str):
        raise ValueError("invalid session cookie")
    return item.value


def smoke(values: dict[str, Any]) -> None:
    jar = http.cookiejar.CookieJar()
    mapping = {"/": "v2/agent/dev_chat.html", "/chat.mjs": "v2/agent/public_chat.mjs"}
    for name in ("faq.html", "privacy.txt", "terms.txt"):
        mapping[f"/{name}"] = f"v2/agent/{name}"
    mapping.update(
        {
            "/assets/" + path.removeprefix("v2/agent/assets/"): path
            for path in values["hashes"]
            if path.startswith("v2/agent/assets/")
        }
    )
    for path, source in mapping.items():
        for attempt in range(12):
            code, _, body = request(jar, path)
            if (
                code == 200
                and hashlib.sha256(body).hexdigest() == values["hashes"][source]
            ):
                break
            require(attempt < 11)
            time.sleep(5)
    code, _, body = request(jar, "/robots.txt")
    require(code == 200 and body == b"User-agent: *\nDisallow: /\n")
    code, kind, body = request(jar, "/api/config")
    config = json.loads(body)
    require(
        code == 200
        and kind == "application/json"
        and config["chatEnabled"] is True
        and config["maxTurns"] == 5
        and type(config["maxMessageChars"]) is int
        and config["maxMessageChars"] > 0
    )
    require(
        request(
            jar, "/api/chat", {"message": PROMPT}, origin="https://invalid.example"
        )[0]
        == 403
    )
    first, second = http.cookiejar.CookieJar(), http.cookiejar.CookieJar()
    try:
        answer(request(first, "/api/chat", {"message": PROMPT}))
        first_token = token(first)
        answer(request(second, "/api/chat", {"message": PROMPT}))
        require(token(second) != first_token)
        reset(first)
        code, _, body = request(
            http.cookiejar.CookieJar(),
            "/api/chat",
            {"message": PROMPT},
            cookie=first_token,
        )
        require(code == 401 and json.loads(body)["error"]["code"] == "session_expired")
        answer(request(second, "/api/chat", {"message": PROMPT}))
    finally:
        # Attempt cleanup of both jars even when a prior request or reset failed.
        errors: list[bool] = []
        for session in (first, second):
            if any(item.name == COOKIE for item in session):
                try:
                    reset(session)
                except (ValueError, KeyError, OSError):
                    errors.append(True)
        require(not errors)


def reset(jar: http.cookiejar.CookieJar) -> None:
    code, _, body = request(jar, "/api/reset", {})
    require(code == 200 and json.loads(body).get("ok") is True)
    require(not any(item.name == COOKIE for item in jar))


def main() -> int:
    def expired(_signum: int, _frame: object) -> None:
        raise TimeoutError("release check deadline exceeded")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(900)
    try:
        state_path, manifest_path = map(Path, sys.argv[1:])
        require(state_path.stat().st_size <= 32 * 1024 * 1024)
        values = expected(
            json.loads(state_path.read_text()), json.loads(manifest_path.read_text())
        )
        readiness(values)
        smoke(values)
        print("development readiness and public smoke passed")
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OSError,
        subprocess.SubprocessError,
    ):
        print("development readiness or public smoke failed closed", file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
