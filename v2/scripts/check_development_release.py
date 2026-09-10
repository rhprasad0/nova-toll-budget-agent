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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, NoReturn, cast

profile_site = "https://dev.tollchat.ai"
profile_account = "903859731897"
profile_distribution = "E33DVF3KT7BTAC"
profile_runtime = "nova_toll_v2_development-Y69XBf88Bl"
profile_runtime_arn = (
    f"arn:aws:bedrock-agentcore:us-east-1:{profile_account}:runtime/{profile_runtime}"
)
COOKIE = "__Host-tollchat-session"
PROMPT = "Briefly explain what information you need to estimate a toll budget."
CANARY_PROMPT = "What is the current toll from the Leesburg Bypass entrance to Route 28 for a two-axle vehicle with E-ZPass?"
CANARY_MARKER = "greenway-canary-v1"
CANARY_DISCLAIMER = (
    "Estimates only. Verify current rates with the toll operator before travel."
)
_CANARY_MONEY = re.compile(
    r"(?i)(?<![\w.\-\u2212])(?:\$|usd\s*)(\d+(?:\.\d+)?)(?![\w]|\.\d)|"
    r"(?<![\w.\-\u2212])(\d+(?:\.\d+)?)\s*(?:usd|dollars?)\b"
)
_CURRENCY_CUE = re.compile(r"(?i)(?:\$|¢|\b(?:usd|dollars?|cents?)\b)")
_CANARY_DISCLAIMER_SUFFIX = re.compile(
    r"(?:^|\n[ \t]*\n)" + re.escape(CANARY_DISCLAIMER) + r"\s*\Z"
)
MAX_BODY = 8 * 1024 * 1024
profile_functions = {
    "loader": ("toll-v2-pricing-loader-dev", "loader.zip"),
    "publisher": ("toll-v2-report-publisher-dev", "publisher.zip"),
    "tollchat_proxy": ("tollchat-v2-chat-proxy-dev", "chat-proxy.zip"),
}
profile_production = False


def configure(profile: str) -> None:
    """Select one reviewed readiness target; callers cannot supply identifiers."""
    global \
        profile_site, \
        profile_account, \
        profile_distribution, \
        profile_runtime, \
        profile_runtime_arn, \
        profile_functions, \
        profile_production
    if profile not in {"development", "production"}:
        _fail("contract")
    profile_site = "https://dev.tollchat.ai"
    profile_account = "903859731897"
    profile_distribution = "E33DVF3KT7BTAC"
    profile_runtime = "nova_toll_v2_development-Y69XBf88Bl"
    profile_runtime_arn = f"arn:aws:bedrock-agentcore:us-east-1:{profile_account}:runtime/{profile_runtime}"
    profile_functions = {
        "loader": ("toll-v2-pricing-loader-dev", "loader.zip"),
        "publisher": ("toll-v2-report-publisher-dev", "publisher.zip"),
        "tollchat_proxy": ("tollchat-v2-chat-proxy-dev", "chat-proxy.zip"),
    }
    profile_production = False
    if profile == "development":
        return
    profile_site = "https://tollchat.ai"
    profile_account = "920534282028"
    profile_distribution = "E16XVTXNFUS8T4"
    profile_runtime = "nova_toll_v2-W6989LEw44"
    profile_runtime_arn = f"arn:aws:bedrock-agentcore:us-east-1:{profile_account}:runtime/{profile_runtime}"
    profile_functions = {
        "loader": ("toll-v2-pricing-loader", "loader.zip"),
        "publisher": ("toll-v2-report-publisher", "publisher.zip"),
        "tollchat_proxy": ("tollchat-v2-chat-proxy", "chat-proxy.zip"),
    }
    profile_production = True


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
    for _, (name, package) in profile_functions.items():
        if not profile_production:
            require(name.endswith("-dev"))
        require(
            re.fullmatch(r"[0-9a-f]{64}", hashes[f"v2/infra/build/{package}"])
            is not None
        )
    distribution_resource = resources["aws_cloudfront_distribution.site"]
    runtime_resource = resources["aws_bedrockagentcore_agent_runtime.tollchat"]
    endpoint = resources["aws_bedrockagentcore_agent_runtime_endpoint.tollchat"]
    alias = resources["aws_lambda_alias.tollchat_live"]
    require(distribution_resource["id"] == profile_distribution)
    require(
        runtime_resource["agent_runtime_id"] == profile_runtime
        and runtime_resource["agent_runtime_arn"] == profile_runtime_arn
    )
    version = runtime_resource["agent_runtime_version"]
    require(isinstance(version, str) and version.isdecimal() and int(version) > 0)
    require(
        endpoint["agent_runtime_id"] == profile_runtime
        and endpoint["name"] == "preview"
    )
    require(endpoint["agent_runtime_version"] == version)
    require(
        alias["name"] == "live"
        and alias["function_name"] == profile_functions["tollchat_proxy"][0]
    )
    require(
        isinstance(alias["function_version"], str)
        and alias["function_version"].isdecimal()
    )
    for resource, (name, package) in profile_functions.items():
        function = resources[f"aws_lambda_function.{resource}"]
        digest = base64.b64encode(
            bytes.fromhex(hashes[f"v2/infra/build/{package}"])
        ).decode()
        require(
            function["function_name"] == name and function["source_code_hash"] == digest
        )
        if resource == "tollchat_proxy":
            require(function["version"] == alias["function_version"])
    require(state["values"]["outputs"]["public_site"]["value"]["url"] == profile_site)
    values = {
        "hashes": hashes,
        "robots_hash": hashes.get("v2/agent/robots.txt"),
        "version": version,
        "alias_version": alias["function_version"],
    }
    _diagnostic("pass", "validated")
    return values


def readiness(values: dict[str, Any]) -> None:
    _select("readiness", "identity", 1)
    caller_account = _field(aws("sts", "get-caller-identity"), "Account")
    require(
        isinstance(caller_account, str) and caller_account == profile_account,
        "identity_mismatch",
    )
    _diagnostic("pass", "validated")
    started = time.monotonic()
    deadline = started + 600
    for attempt in range(1, 61):
        now = time.monotonic()
        elapsed = max(0, min(int(now - started), 900))
        ready = True
        for resource, (name, package) in profile_functions.items():
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
                == f"arn:aws:lambda:us-east-1:{profile_account}:function:{name}",
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
            profile_functions["tollchat_proxy"][0],
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
            "cloudfront", "get-distribution", "--id", profile_distribution
        )
        deployed_distribution = _field(distribution_response, "Distribution")
        require(isinstance(deployed_distribution, dict), "malformed_response")
        deployed_distribution = cast(dict[str, Any], deployed_distribution)
        distribution_id = _field(deployed_distribution, "Id")
        require(
            isinstance(distribution_id, str)
            and distribution_id == profile_distribution,
            "identity_mismatch",
        )
        status = _field(deployed_distribution, "Status")
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
            profile_runtime,
            "--endpoint-name",
            "preview",
        )
        endpoint_runtime_arn = _field(endpoint, "agentRuntimeArn")
        endpoint_name = _field(endpoint, "name")
        require(
            isinstance(endpoint_runtime_arn, str)
            and endpoint_runtime_arn == profile_runtime_arn,
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
    origin: str | None = None,
    cookie: str | None = None,
    canary: bool = False,
) -> tuple[int, str, bytes]:
    require(
        path.startswith("/") and not path.startswith("//"),
        "request_path",
    )
    origin = profile_site if origin is None else origin
    headers = {
        "Origin": origin,
        "Sec-Fetch-Site": "same-origin",
        "Accept-Encoding": "identity",
    }
    if cookie is not None:
        headers["Cookie"] = f"{COOKIE}={cookie}"
    if canary:
        headers["x-tollchat-canary"] = CANARY_MARKER
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["x-amz-content-sha256"] = hashlib.sha256(data).hexdigest()
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPCookieProcessor(jar)
    )
    req = urllib.request.Request(profile_site + path, data=data, headers=headers)
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
        require(len(content) <= MAX_BODY, "response_size")
        code, kind = response.status, response.headers.get_content_type()
        if (
            not isinstance(code, int)
            or not isinstance(kind, str)
            or not isinstance(content, bytes)
        ):
            raise ValueError("invalid HTTP response")
        return code, kind, content


def answer(response: tuple[int, str, bytes]) -> dict[str, Any]:
    code, content_type, body = response
    require(code == 200, "answer_status")
    require(content_type == "application/x-ndjson", "answer_content_type")
    lines = body.decode().splitlines()
    require(0 < len(lines) <= 1000, "answer_lines")
    terminal: dict[str, Any] | None = None
    for line in lines:
        value = json.loads(line)
        require(isinstance(value, dict), "answer_event")
        item = cast(dict[str, Any], value)
        require(isinstance(item.get("type"), str) and terminal is None, "answer_event")
        require(item["type"] != "error", "answer_event")
        if item["type"] == "answer":
            require(
                isinstance(item.get("text"), str)
                and bool(item["text"].strip())
                and item.get("blocked") is False,
                "answer_content",
            )
            terminal = item
    require(terminal is not None, "answer_terminal")
    return cast(dict[str, Any], terminal)


def _canary_contract() -> dict[str, str]:
    """Read the deployed source contracts that the candidate artifact binds."""
    root = Path(__file__).parents[1]
    source = (root / "agent" / "toll_agent.py").read_text(encoding="utf-8")
    manifest = cast(
        dict[str, object],
        json.loads(
            (root / "agent_tools" / "contract-manifest.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    matches = {
        key: re.search(pattern, source)
        for key, pattern in {
            "model": r'model_id="([^"]+)"',
            "prompt_version": r'SYSTEM_PROMPT_VERSION = "([^"]+)"',
            "renderer_version": r'SYSTEM_PROMPT_RENDERER_VERSION = "([^"]+)"',
        }.items()
    }
    raw_tool = manifest.get("get_current_toll_price")
    tool = cast(dict[str, object], raw_tool) if isinstance(raw_tool, dict) else None
    require(
        all(match is not None for match in matches.values())
        and tool is not None
        and isinstance(tool.get("current"), str),
        "canary_contract",
    )
    if tool is None:
        _fail("canary_contract")
    return {
        "model": cast(re.Match[str], matches["model"]).group(1),
        "tool_contract": cast(str, tool["current"]),
        "prompt_version": cast(re.Match[str], matches["prompt_version"]).group(1),
        "renderer_version": cast(re.Match[str], matches["renderer_version"]).group(1),
    }


def canary(values: dict[str, Any]) -> dict[str, Any]:
    """Run the one fixed synthetic request and return bounded release evidence."""
    started = time.monotonic()
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def expired(_signum: int, _frame: object) -> None:
        raise TimeoutError("canary deadline exceeded")

    try:
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, 60)
        jar = http.cookiejar.CookieJar()
        code, content_type, body = request(
            jar, "/api/chat", {"message": CANARY_PROMPT}, canary=True
        )
        require(code == 200 and content_type == "application/x-ndjson", "canary_http")
        evidence: dict[str, Any] | None = None
        terminal: dict[str, Any] | None = None
        for line in body.decode().splitlines():
            value = json.loads(line)
            require(isinstance(value, dict) and terminal is None, "canary_event")
            item = cast(dict[str, Any], value)
            if item.get("type") == "canary":
                require(evidence is None, "canary_event")
                expected = {
                    "type",
                    "schema_version",
                    "call_count",
                    "tool_name_match",
                    "route_profile_match",
                    "correlation_match",
                    "result_success",
                    "total_usd",
                    "success",
                }
                require(
                    set(item) == expected
                    and type(item.get("schema_version")) is int
                    and item.get("schema_version") == 1,
                    "canary_evidence",
                )
                require(
                    type(item.get("call_count")) is int and item.get("call_count") == 1,
                    "canary_evidence",
                )
                require(
                    all(
                        item.get(key) is True
                        for key in (
                            "tool_name_match",
                            "route_profile_match",
                            "correlation_match",
                            "result_success",
                            "success",
                        )
                    ),
                    "canary_evidence",
                )
                require(
                    isinstance(item.get("total_usd"), str)
                    and re.fullmatch(r"\d{1,4}\.\d{2}", item["total_usd"]) is not None,
                    "canary_evidence",
                )
                evidence = item
            elif item.get("type") == "answer":
                require(
                    isinstance(item.get("text"), str) and item.get("blocked") is False,
                    "canary_answer",
                )
                require(evidence is not None, "canary_evidence")
                evidence = cast(dict[str, Any], evidence)
                try:
                    expected_total = Decimal(evidence["total_usd"])
                    money_tokens = list(_CANARY_MONEY.finditer(item["text"]))
                    amounts = [
                        Decimal(amount)
                        for match in money_tokens
                        for amount in match.groups()
                        if amount
                    ]
                except (InvalidOperation, ValueError):
                    _fail("canary_grounding")
                require(
                    bool(amounts) and all(value == expected_total for value in amounts),
                    "canary_grounding",
                )
                require(
                    _CURRENCY_CUE.search(_CANARY_MONEY.sub("", item["text"])) is None,
                    "canary_grounding",
                )
                require(
                    _CANARY_DISCLAIMER_SUFFIX.search(item["text"]) is not None,
                    "canary_disclaimer",
                )
                terminal = item
            elif item.get("type") == "tool":
                continue
            else:
                _fail("canary_event")
        require(evidence is not None and terminal is not None, "canary_terminal")
        evidence = cast(dict[str, Any], evidence)
        elapsed = time.monotonic() - started
        require(elapsed <= 60, "canary_timeout")
        record: dict[str, Any] = {
            "schema_version": 1,
            "runtime_version": values["version"],
            "proxy_version": values["alias_version"],
            "call_count": evidence["call_count"],
            "total_usd": evidence["total_usd"],
            "elapsed_ms": max(0, int(elapsed * 1000)),
            **_canary_contract(),
            "success": True,
        }
        identity = {
            "commit": os.environ.get("CANARY_COMMIT"),
            "run_id": os.environ.get("CANARY_RUN_ID"),
            "attempt": os.environ.get("CANARY_ATTEMPT"),
            "deployment_id": os.environ.get("CANARY_DEPLOYMENT_ID"),
            "artifact_id": os.environ.get("CANARY_ARTIFACT_ID"),
            "artifact_digest": os.environ.get("CANARY_ARTIFACT_DIGEST"),
        }
        if all(value is not None for value in identity.values()):
            record.update(identity)
        return record
    except TimeoutError:
        _fail("canary_timeout")
    finally:
        signal.signal(signal.SIGALRM, previous_handler)
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def token(jar: http.cookiejar.CookieJar) -> str:
    cookies = [item for item in jar if item.name == COOKIE]
    require(len(cookies) == 1, "session_cookie_count")
    item = cookies[0]
    require(
        item.secure
        and item.path == "/"
        and item.domain == "dev.tollchat.ai"
        and not item.domain_specified,
        "session_cookie_attributes",
    )
    require(
        item.has_nonstandard_attr("HttpOnly") and bool(item.value),
        "session_cookie_value",
    )
    value = item.value
    if not isinstance(value, str):
        _fail("session_cookie_value")
    return value


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
    expected_robots = b"User-agent: *\nDisallow: /\n"
    if profile_production:
        expected_robots = Path("v2/agent/robots.txt").read_bytes()
        require(
            isinstance(values["robots_hash"], str)
            and hashlib.sha256(expected_robots).hexdigest() == values["robots_hash"],
            "http",
        )
    require(code == 200 and body == expected_robots, "http")
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
    select("canary")
    evidence = canary(values)
    output = os.environ.get("CANARY_EVIDENCE_FILE")
    if output:
        Path(output).write_text(
            json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8"
        )
    _diagnostic("pass", "validated")
    if profile_production:
        return
    first, second = http.cookiejar.CookieJar(), http.cookiejar.CookieJar()
    try:
        select("session_first")
        answer(request(first, "/api/chat", {"message": PROMPT}))
        first_token = token(first)
        _diagnostic("pass", "created")
        select("session_second")
        answer(request(second, "/api/chat", {"message": PROMPT}))
        require(token(second) != first_token, "session_distinct")
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
            "session_revocation",
        )
        _diagnostic("pass", "revoked")
        select("session_second")
        answer(request(second, "/api/chat", {"message": PROMPT}))
        _diagnostic("pass", "reused")
    finally:
        # Attempt cleanup of both jars even when a prior request or reset failed.
        had_failure = sys.exc_info()[0] is not None
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
                    if had_failure:
                        _diagnostic("fail", "reset_failed")
                    errors.append(True)
        _select(*original_context)
        if errors and not had_failure:
            _fail("reset_failed")


def reset(jar: http.cookiejar.CookieJar) -> None:
    code, _, body = request(jar, "/api/reset", {})
    try:
        response = json.loads(body)
    except (TypeError, ValueError):
        _fail("malformed_response")
    require(isinstance(response, dict), "malformed_response")
    response = cast(dict[str, Any], response)
    require(code == 200 and response.get("ok") is True, "reset_response")
    require(not any(item.name == COOKIE for item in jar), "reset_cookie")


def main() -> int:
    def expired(_signum: int, _frame: object) -> None:
        raise TimeoutError("release check deadline exceeded")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(900)
    try:
        profile = "development"
        arguments = sys.argv[1:]
        if arguments[:2] == ["--profile", "production"]:
            profile, arguments = "production", arguments[2:]
        require(len(arguments) == 2, "contract")
        configure(profile)
        state_path, manifest_path = map(Path, arguments)
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
