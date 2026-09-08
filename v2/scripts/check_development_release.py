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
from typing import Any, NoReturn, cast

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


_current_stage = "startup"
_current_subcheck = "startup"
_current_attempt = 0
_current_elapsed = 0


class CheckFailure(ValueError):
    """A bounded local failure that is safe to print in CI logs."""


def _select(stage: str, subcheck: str, attempt: int = 0, elapsed: int = 0) -> None:
    global _current_stage, _current_subcheck, _current_attempt, _current_elapsed
    _current_stage = stage
    _current_subcheck = subcheck
    _current_attempt = max(0, min(attempt, 900))
    _current_elapsed = max(0, min(elapsed, 900))


def _diagnostic(
    status: str,
    reason: str,
) -> None:
    """Print only fixed local identifiers and bounded numeric fields."""
    allowed = re.compile(r"^[a-z0-9:_-]+$")
    fields = {
        "stage": _current_stage,
        "subcheck": _current_subcheck,
        "status": status if status in {"pending", "pass", "fail"} else "fail",
        "attempt": max(0, min(_current_attempt, 900)),
        "elapsed": max(0, min(_current_elapsed, 900)),
        "reason": reason,
    }
    safe = {
        key: value
        if isinstance(value, int) or allowed.fullmatch(str(value))
        else "invalid"
        for key, value in fields.items()
    }
    print(" ".join(f"{key}={value}" for key, value in safe.items()), file=sys.stderr)


def _fail(reason: str) -> NoReturn:
    _diagnostic("fail", reason)
    raise CheckFailure(reason)


def require(condition: bool, reason: str = "contract") -> None:
    if not condition:
        _fail(reason)


def _field(response: dict[str, Any], name: str) -> object:
    if name not in response:
        _fail("malformed_response")
    return response[name]


def aws(*arguments: str) -> dict[str, Any]:
    try:
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
    except subprocess.TimeoutExpired:
        _fail("timeout")
    except OSError:
        _fail("cli")
    require(result.returncode == 0, "cli")
    require(len(result.stdout) <= MAX_BODY, "malformed_response")
    try:
        response = json.loads(result.stdout)
    except (TypeError, ValueError):
        _fail("malformed_response")
    require(isinstance(response, dict), "malformed_response")
    return response


def expected(state: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    _select("state", "identity")
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
    values = {
        "hashes": hashes,
        "version": version,
        "alias_version": alias["function_version"],
    }
    _diagnostic("pass", "validated")
    return values


def readiness(values: dict[str, Any]) -> None:
    _select("readiness", "identity", 1)
    account = _field(aws("sts", "get-caller-identity"), "Account")
    require(isinstance(account, str) and account == ACCOUNT, "identity_mismatch")
    _diagnostic("pass", "validated")
    started = time.monotonic()
    deadline = started + 600
    for attempt in range(1, 61):
        now = time.monotonic()
        elapsed = max(0, min(int(now - started), 900))
        ready = True
        for resource, (name, package) in FUNCTIONS.items():
            subcheck = f"lambda:{resource}"
            _select("readiness", subcheck, attempt, elapsed)
            function = aws(
                "lambda", "get-function-configuration", "--function-name", name
            )
            function_name = _field(function, "FunctionName")
            function_arn = _field(function, "FunctionArn")
            require(
                isinstance(function_name, str) and function_name == name,
                "identity_mismatch",
            )
            require(
                isinstance(function_arn, str)
                and function_arn
                == f"arn:aws:lambda:us-east-1:{ACCOUNT}:function:{name}",
                "identity_mismatch",
            )
            state = _field(function, "State")
            update_status = _field(function, "LastUpdateStatus")
            require(
                isinstance(state, str) and isinstance(update_status, str),
                "malformed_response",
            )
            require(state in {"Pending", "Active"}, "invalid_state")
            require(update_status in {"InProgress", "Successful"}, "invalid_state")
            digest = base64.b64encode(
                bytes.fromhex(values["hashes"][f"v2/infra/build/{package}"])
            ).decode()
            code_sha = _field(function, "CodeSha256")
            require(isinstance(code_sha, str), "malformed_response")
            function_ready = (
                state == "Active"
                and update_status == "Successful"
                and code_sha == digest
            )
            ready &= function_ready
            _diagnostic(
                "pass" if function_ready else "pending",
                "validated" if function_ready else "not_ready",
            )
        _select("readiness", "alias", attempt, elapsed)
        alias = aws(
            "lambda",
            "get-alias",
            "--function-name",
            FUNCTIONS["tollchat_proxy"][0],
            "--name",
            "live",
        )
        alias_name = _field(alias, "Name")
        require(
            isinstance(alias_name, str) and alias_name == "live", "identity_mismatch"
        )
        alias_version = _field(alias, "FunctionVersion")
        require(isinstance(alias_version, str), "malformed_response")
        alias_ready = alias_version == values["alias_version"]
        routing = alias.get("RoutingConfig", {})
        require(isinstance(routing, dict), "malformed_response")
        weights = routing.get("AdditionalVersionWeights", {})
        require(isinstance(weights, dict), "malformed_response")
        require(not weights, "weighted_routing")
        ready &= alias_ready
        _diagnostic(
            "pass" if alias_ready else "pending",
            "validated" if alias_ready else "not_ready",
        )
        _select("readiness", "cloudfront", attempt, elapsed)
        distribution_response = aws(
            "cloudfront", "get-distribution", "--id", DISTRIBUTION
        )
        distribution = _field(distribution_response, "Distribution")
        require(isinstance(distribution, dict), "malformed_response")
        distribution = cast(dict[str, Any], distribution)
        distribution_id = _field(distribution, "Id")
        require(
            isinstance(distribution_id, str) and distribution_id == DISTRIBUTION,
            "identity_mismatch",
        )
        status = _field(distribution, "Status")
        require(isinstance(status, str), "malformed_response")
        require(status in {"InProgress", "Deployed"}, "invalid_state")
        distribution_ready = status == "Deployed"
        ready &= distribution_ready
        _diagnostic(
            "pass" if distribution_ready else "pending",
            "validated" if distribution_ready else "not_ready",
        )
        _select("readiness", "agentcore", attempt, elapsed)
        endpoint = aws(
            "bedrock-agentcore-control",
            "get-agent-runtime-endpoint",
            "--agent-runtime-id",
            RUNTIME,
            "--endpoint-name",
            "preview",
        )
        runtime_arn = _field(endpoint, "agentRuntimeArn")
        endpoint_name = _field(endpoint, "name")
        require(
            isinstance(runtime_arn, str) and runtime_arn == RUNTIME_ARN,
            "identity_mismatch",
        )
        require(
            isinstance(endpoint_name, str) and endpoint_name == "preview",
            "identity_mismatch",
        )
        status = _field(endpoint, "status")
        require(isinstance(status, str), "malformed_response")
        require(status in {"CREATING", "UPDATING", "READY"}, "invalid_state")
        if status == "READY":
            live_version = _field(endpoint, "liveVersion")
            require(isinstance(live_version, str), "malformed_response")
            require(live_version == values["version"], "version_mismatch")
            if "targetVersion" in endpoint:
                require(
                    isinstance(endpoint["targetVersion"], str)
                    and endpoint["targetVersion"] == values["version"],
                    "version_mismatch",
                )
            endpoint_ready = True
        else:
            for version_name in ("liveVersion", "targetVersion"):
                if version_name in endpoint:
                    require(
                        isinstance(endpoint[version_name], str), "malformed_response"
                    )
            endpoint_ready = False
        ready &= endpoint_ready
        _diagnostic(
            "pass" if endpoint_ready else "pending",
            "validated" if endpoint_ready else "transitioning",
        )
        if ready:
            _select("readiness", "complete", attempt, elapsed)
            _diagnostic("pass", "validated")
            return
        require(now < deadline, "readiness_timeout")
        time.sleep(5)
    _select("readiness", "complete", 60, 600)
    _fail("readiness_timeout")


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
    except TimeoutError:
        _fail("timeout")
    except (urllib.error.URLError, OSError):
        _fail("http")
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
    started = time.monotonic()

    def select(subcheck: str, attempt: int = 0) -> None:
        elapsed = max(0, min(int(time.monotonic() - started), 900))
        _select("smoke", subcheck, attempt, elapsed)

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
        for attempt in range(1, 13):
            select("static_bytes", attempt)
            code, _, body = request(jar, path)
            if (
                code == 200
                and hashlib.sha256(body).hexdigest() == values["hashes"][source]
            ):
                _diagnostic("pass", "validated")
                break
            _diagnostic("pending", "content_mismatch")
            require(attempt < 12, "content_mismatch")
            time.sleep(5)
    select("robots")
    code, _, body = request(jar, "/robots.txt")
    require(code == 200 and body == b"User-agent: *\nDisallow: /\n", "http")
    _diagnostic("pass", "validated")
    select("config")
    code, kind, body = request(jar, "/api/config")
    try:
        config = json.loads(body)
    except (TypeError, ValueError):
        _fail("malformed_response")
    require(isinstance(config, dict), "malformed_response")
    config = cast(dict[str, Any], config)
    require(
        code == 200
        and kind == "application/json"
        and config.get("chatEnabled") is True
        and config.get("maxTurns") == 5
        and type(config.get("maxMessageChars")) is int
        and config["maxMessageChars"] > 0,
        "malformed_response",
    )
    _diagnostic("pass", "validated")
    select("origin")
    require(
        request(
            jar, "/api/chat", {"message": PROMPT}, origin="https://invalid.example"
        )[0]
        == 403,
        "http",
    )
    _diagnostic("pass", "validated")
    first, second = http.cookiejar.CookieJar(), http.cookiejar.CookieJar()
    try:
        select("session_first")
        answer(request(first, "/api/chat", {"message": PROMPT}))
        first_token = token(first)
        _diagnostic("pass", "created")
        select("session_second")
        answer(request(second, "/api/chat", {"message": PROMPT}))
        require(token(second) != first_token)
        _diagnostic("pass", "created")
        select("session_reuse")
        reset(first)
        code, _, body = request(
            http.cookiejar.CookieJar(),
            "/api/chat",
            {"message": PROMPT},
            cookie=first_token,
        )
        require(
            code == 401 and json.loads(body)["error"]["code"] == "session_expired",
            "http",
        )
        _diagnostic("pass", "revoked")
        select("session_second")
        answer(request(second, "/api/chat", {"message": PROMPT}))
        _diagnostic("pass", "reused")
    finally:
        # Attempt cleanup of both jars even when a prior request or reset failed.
        original_context = (
            _current_stage,
            _current_subcheck,
            _current_attempt,
            _current_elapsed,
        )
        errors: list[bool] = []
        for session in (first, second):
            if any(item.name == COOKIE for item in session):
                try:
                    select("reset")
                    reset(session)
                    _diagnostic("pass", "cleared")
                except (ValueError, KeyError, OSError):
                    _diagnostic("fail", "reset_failed")
                    errors.append(True)
        if not errors:
            _select(*original_context)
        require(not errors, "reset_failed")


def reset(jar: http.cookiejar.CookieJar) -> None:
    code, _, body = request(jar, "/api/reset", {})
    try:
        response = json.loads(body)
    except (TypeError, ValueError):
        _fail("malformed_response")
    require(isinstance(response, dict), "malformed_response")
    response = cast(dict[str, Any], response)
    require(code == 200 and response.get("ok") is True, "http")
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
    except CheckFailure:
        # _fail already emitted the bounded diagnostic before raising.
        return 1
    except subprocess.TimeoutExpired:
        _diagnostic("fail", "timeout")
        return 1
    except subprocess.SubprocessError:
        _diagnostic("fail", "cli")
        return 1
    except TimeoutError:
        _diagnostic("fail", "timeout")
        return 1
    except (urllib.error.URLError, OSError):
        _diagnostic("fail", "http" if _current_stage == "smoke" else "io")
        return 1
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError, UnicodeError):
        _diagnostic("fail", "malformed_response")
        return 1
    except Exception:
        _diagnostic("fail", "contract")
        return 1
    finally:
        signal.alarm(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
